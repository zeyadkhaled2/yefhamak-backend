"""Order logic: validate the customer's details, build the summary from held items, and create the order atomically."""
import re
import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.models import (
    Conversation,
    DeliveryZone,
    Message,
    MessageDirection,
    Order,
    OrderItem,
    Product,
    Reservation,
    ReservationStatus,
    Seller,
    Variant,
)
from app.services.catalog import normalize

_ARABIC_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")

# City names in Arabic -> the English name stored in delivery_zones (keys are normalized, without the "ال")
_AREA_ALIASES = {"قاهره": "cairo", "جيزه": "giza", "اسكندريه": "alexandria", "سكندريه": "alexandria"}


def normalize_phone(raw: str) -> str | None:
    """Egyptian mobile numbers only: 01[0125] + 8 digits. Accepts +20 / 0020 / 20 prefixes and Arabic digits."""
    digits = re.sub(r"[\s\-().]", "", raw.translate(_ARABIC_DIGITS))
    if digits.startswith("+20"):
        digits = "0" + digits[3:]
    elif digits.startswith("0020"):
        digits = "0" + digits[4:]
    elif digits.startswith("20") and len(digits) == 12:
        digits = "0" + digits[2:]
    return digits if re.fullmatch(r"01[0125]\d{8}", digits) else None


def match_zone(area: str, zones: list[DeliveryZone]) -> DeliveryZone | None:
    key = normalize(area).replace(" ", "")
    if key.startswith("ال") and len(key) > 4:
        key = key[2:]
    key = _AREA_ALIASES.get(key, key)
    for zone in zones:
        if normalize(zone.area).replace(" ", "") == key:
            return zone
    return None


def validate_details(name: str, phone: str, address: str, area: str, zones: list[DeliveryZone]):
    """Returns (details, zone, error). error is a small dict the model can read and act on."""
    phone_ok = normalize_phone(phone)
    if phone_ok is None:
        return None, None, {"ok": False, "reason": "invalid_phone", "hint": "Ask for an Egyptian mobile number like 01012345678."}
    zone = match_zone(area, zones)
    if zone is None:
        return None, None, {"ok": False, "reason": "area_not_covered", "covered_areas": [z.area for z in zones]}
    details = {"name": " ".join(name.split()), "phone": phone_ok, "address": " ".join(address.split()), "area": zone.area}
    return details, zone, None


def count_customer_messages(db: Session, conversation_id: uuid.UUID) -> int:
    return db.scalar(
        select(func.count()).select_from(Message).where(
            Message.conversation_id == conversation_id, Message.direction == MessageDirection.IN
        )
    ) or 0


def order_summary(db: Session, conversation: Conversation, zone: DeliveryZone) -> dict | None:
    """Everything currently held for this customer (still valid), with prices from the database."""
    now = datetime.now(timezone.utc)
    rows = db.execute(
        select(Reservation, Variant, Product)
        .join(Variant, Reservation.variant_id == Variant.id)
        .join(Product, Variant.product_id == Product.id)
        .where(
            Reservation.conversation_id == conversation.id,
            Reservation.status == ReservationStatus.ACTIVE,
            Reservation.expires_at > now,
        )
    ).all()
    if not rows:
        return None

    items = [
        {
            "reservation_id": res.id,
            "variant_id": var.id,
            "name": prod.name,
            "color": var.color,
            "size": var.size,
            "quantity": res.quantity,
            "unit_price": prod.price,
        }
        for res, var, prod in rows
    ]
    subtotal = sum((it["unit_price"] * it["quantity"] for it in items), Decimal("0"))
    return {"items": items, "subtotal": subtotal, "delivery_fee": zone.fee, "total": subtotal + zone.fee}


def public_summary(summary: dict, area: str) -> dict:
    """The version the LLM sees: no database ids, plain numbers."""
    return {
        "items": [
            {
                "name": it["name"],
                "color": it["color"],
                "size": it["size"],
                "quantity": it["quantity"],
                "unit_price_egp": float(it["unit_price"]),
            }
            for it in summary["items"]
        ],
        "subtotal_egp": float(summary["subtotal"]),
        "delivery_fee_egp": float(summary["delivery_fee"]),
        "total_egp": float(summary["total"]),
        "area": area,
    }


def create_order(db: Session, seller: Seller, conversation: Conversation, details: dict, summary: dict) -> Order | None:
    """Creates the order and confirms every held item in ONE transaction. None = a hold expired meanwhile (nothing saved)."""
    now = datetime.now(timezone.utc)
    try:
        order = Order(
            seller_id=seller.id,
            customer_id=conversation.customer_id,
            conversation_id=conversation.id,
            customer_name=details["name"],
            phone=details["phone"],
            address=details["address"],
            area=details["area"],
            delivery_fee=summary["delivery_fee"],
            total=summary["total"],
        )
        db.add(order)
        db.flush()

        for it in summary["items"]:
            db.add(OrderItem(order_id=order.id, variant_id=it["variant_id"], quantity=it["quantity"], unit_price=it["unit_price"]))

        ids = [it["reservation_id"] for it in summary["items"]]
        result = db.execute(
            update(Reservation)
            .where(Reservation.id.in_(ids), Reservation.status == ReservationStatus.ACTIVE, Reservation.expires_at > now)
            .values(status=ReservationStatus.CONFIRMED, order_id=order.id)
            .execution_options(synchronize_session=False)
        )
        if result.rowcount != len(ids):
            db.rollback()
            return None

        db.commit()
        return order
    except Exception:
        db.rollback()
        raise
