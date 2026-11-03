"""Atomic seller review: pending holds become sales or are returned to availability."""
from collections import Counter
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.models import Order, OrderItem, OrderStatus, Reservation, ReservationStatus, Variant
from app.services.workspace import WorkspaceNotFound


class OrderConflict(ValueError):
    pass


def review_order(db: Session, seller_id: UUID, order_id: UUID, target: OrderStatus) -> Order:
    """Serialize review on the order row; commit status and every stock change together.

    Repeating the current terminal status is a no-op. Confirm consumes stock and
    its reserved counter. Cancel pending releases holds; cancel confirmed returns
    sold stock. Cancellation is terminal. No model or message calls are involved.
    """
    try:
        order = db.scalar(select(Order).where(Order.id == order_id, Order.seller_id == seller_id)
                          .with_for_update().execution_options(populate_existing=True))
        if order is None:
            raise WorkspaceNotFound('order_not_found')
        if target not in (OrderStatus.CONFIRMED, OrderStatus.CANCELLED):
            raise OrderConflict('invalid_order_transition')
        if order.status == target:
            db.commit()
            return order
        if order.status == OrderStatus.CANCELLED:
            raise OrderConflict('invalid_order_transition')

        items = db.scalars(select(OrderItem).where(OrderItem.order_id == order.id)).all()
        holds = db.scalars(select(Reservation).where(Reservation.order_id == order.id)
                           .order_by(Reservation.id).with_for_update()).all()
        quantities = Counter()
        held = Counter()
        for item in items:
            quantities[item.variant_id] += item.quantity
        for hold in holds:
            if (hold.seller_id != seller_id or hold.conversation_id != order.conversation_id
                    or hold.status != ReservationStatus.CONFIRMED):
                raise OrderConflict('order_inventory_conflict')
            held[hold.variant_id] += hold.quantity
        if not quantities or quantities != held:
            raise OrderConflict('order_inventory_conflict')

        # Consistent ordering avoids deadlocks when different orders share variants.
        for variant_id in sorted(quantities, key=str):
            quantity = quantities[variant_id]
            statement = update(Variant).where(Variant.id == variant_id, Variant.seller_id == seller_id)
            if order.status == OrderStatus.PENDING:
                statement = statement.where(Variant.reserved >= quantity)
                values = {'reserved': Variant.reserved - quantity}
                if target == OrderStatus.CONFIRMED:
                    values['stock'] = Variant.stock - quantity
            else:  # CONFIRMED -> CANCELLED: those units were already sold.
                values = {'stock': Variant.stock + quantity}
            result = db.execute(statement.values(**values).execution_options(synchronize_session=False))
            if result.rowcount != 1:
                raise OrderConflict('order_inventory_conflict')
        if target == OrderStatus.CANCELLED:
            for hold in holds:
                hold.status = ReservationStatus.RELEASED
        order.status = target
        db.commit()
        return order
    except Exception:
        db.rollback()
        raise
