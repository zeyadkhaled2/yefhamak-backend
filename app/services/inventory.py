"""Stock reservation. All rules about 'who gets the last item' live here, not in the LLM.

Key idea: the check and the change happen in ONE SQL statement, so two customers can never both get the last piece.
Every function commits its own work (fine for now; we can group them later if needed).
"""
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.models import Conversation, Reservation, ReservationStatus, Variant

RESERVATION_MINUTES = 20


def _now() -> datetime:
    return datetime.now(timezone.utc)


def available_quantity(db: Session, seller_id: uuid.UUID, variant_id: uuid.UUID) -> int:
    row = db.execute(
        select(Variant.stock - Variant.reserved).where(Variant.id == variant_id, Variant.seller_id == seller_id)
    ).first()
    return max(row[0], 0) if row else 0


def reserve_item(
    db: Session,
    seller_id: uuid.UUID,
    variant_id: uuid.UUID,
    conversation_id: uuid.UUID,
    quantity: int = 1,
    minutes: int = RESERVATION_MINUTES,
) -> Reservation | None:
    """Hold an item for this customer. Returns the reservation, or None if there is not enough stock."""
    if quantity < 1:
        return None
    try:
        result = db.execute(
            update(Variant)
            .where(
                Variant.id == variant_id,
                Variant.seller_id == seller_id,
                Variant.stock - Variant.reserved >= quantity,  # the check...
                select(Conversation.id).where(
                    Conversation.id == conversation_id,
                    Conversation.seller_id == seller_id,
                ).exists(),
            )
            .values(reserved=Variant.reserved + quantity)       # ...and the change, in one statement
            .execution_options(synchronize_session=False)
        )
        if result.rowcount != 1:
            db.rollback()
            return None

        reservation = Reservation(
            seller_id=seller_id,
            variant_id=variant_id,
            conversation_id=conversation_id,
            quantity=quantity,
            expires_at=_now() + timedelta(minutes=minutes),
        )
        db.add(reservation)
        db.commit()
        return reservation
    except Exception:
        db.rollback()
        raise


def _release(db: Session, reservation_id: uuid.UUID, new_status: ReservationStatus) -> bool:
    """Free a held item. Safe to call twice: only the first call does anything."""
    try:
        row = db.execute(
            update(Reservation)
            .where(Reservation.id == reservation_id, Reservation.status == ReservationStatus.ACTIVE)
            .values(status=new_status)
            .returning(Reservation.variant_id, Reservation.quantity)
            .execution_options(synchronize_session=False)
        ).first()
        if row is None:
            db.rollback()
            return False
        db.execute(
            update(Variant)
            .where(Variant.id == row.variant_id)
            .values(reserved=Variant.reserved - row.quantity)
            .execution_options(synchronize_session=False)
        )
        db.commit()
        return True
    except Exception:
        db.rollback()
        raise


def release_reservation(db: Session, reservation_id: uuid.UUID) -> bool:
    return _release(db, reservation_id, ReservationStatus.RELEASED)


def confirm_reservation(db: Session, reservation_id: uuid.UUID, order_id: uuid.UUID) -> bool:
    """Attach a still-valid hold to a real order."""
    try:
        result = db.execute(
            update(Reservation)
            .where(
                Reservation.id == reservation_id,
                Reservation.status == ReservationStatus.ACTIVE,
                Reservation.expires_at > _now(),
            )
            .values(status=ReservationStatus.CONFIRMED, order_id=order_id)
            .execution_options(synchronize_session=False)
        )
        db.commit()
        return result.rowcount == 1
    except Exception:
        db.rollback()
        raise


def expire_reservations(db: Session) -> int:
    """Release every hold whose time ran out. A background job will call this every minute."""
    ids = db.scalars(
        select(Reservation.id).where(Reservation.status == ReservationStatus.ACTIVE, Reservation.expires_at <= _now())
    ).all()
    return sum(1 for rid in ids if _release(db, rid, ReservationStatus.EXPIRED))
