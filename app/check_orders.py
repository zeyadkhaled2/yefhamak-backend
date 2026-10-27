"""Tests the order flow WITHOUT the LLM: validation, preview/confirm rules, atomic order creation.

    python -m app.seed
    python -m app.check_orders
"""
import json
from decimal import Decimal

from sqlalchemy import select

from app.agent.tools import run_tool
from app.check1 import make_conversation
from app.db import SessionLocal
from app.models import (
    DeliveryZone,
    Message,
    MessageDirection,
    Order,
    Product,
    Reservation,
    ReservationStatus,
    Seller,
    ShopQuestion,
    Variant,
)
from app.seed import DEMO_NAME
from app.services.inventory import reserve_item
from app.services.orders import match_zone, normalize_phone

failures = 0


def check(ok: bool, label: str) -> None:
    global failures
    print(("PASS  " if ok else "FAIL  ") + label)
    if not ok:
        failures += 1


def run_pure_checks() -> None:
    print("--- Phone and area validation ---")
    check(normalize_phone("01012345678") == "01012345678", "normal mobile number")
    check(normalize_phone("+20 101 234 5678") == "01012345678", "+20 prefix and spaces")
    check(normalize_phone("٠١٠١٢٣٤٥٦٧٨") == "01012345678", "Arabic digits")
    check(normalize_phone("12345678") is None, "too short / not a mobile number")
    check(normalize_phone("01312345678") is None, "wrong operator prefix")

    zones = [DeliveryZone(area="Cairo", fee=Decimal("50")), DeliveryZone(area="Alexandria", fee=Decimal("80"))]
    check(match_zone("Cairo", zones).area == "Cairo", "area: English name")
    check(match_zone("القاهرة", zones).area == "Cairo", "area: Arabic name")
    check(match_zone("الإسكندرية", zones).area == "Alexandria", "area: Arabic name with hamza")
    check(match_zone("Mars", zones) is None, "area: unknown city")


def run_flow_checks(db, seller) -> None:
    print("\n--- Order flow (reserve -> preview -> confirm) ---")
    conv = make_conversation(db, seller.id)
    variant = db.scalar(
        select(Variant).join(Product)
        .where(Product.seller_id == seller.id, Product.code == "H-014", Variant.color == "brown", Variant.size == "M")
    )
    check(reserve_item(db, seller.id, variant.id, conv.id) is not None, "an item is held for the customer")

    good = {
        "customer_name": "Ahmed Test",
        "phone": "01012345678",
        "address": "12 Street 9, Maadi, building 4",
        "area": "Cairo",
    }

    def order_call(**overrides) -> dict:
        return run_tool(db, seller, conv, "create_order", json.dumps({**good, **overrides}))

    check(order_call(confirmed=True).get("reason") == "details_not_previewed", "confirming without a preview is refused")
    check(order_call(phone="12345678").get("reason") == "invalid_phone", "invalid phone is refused")
    check(order_call(area="Mars").get("reason") == "area_not_covered", "uncovered area is refused")

    preview = order_call(confirmed=False)
    check(preview.get("preview") is True and preview.get("total_egp") == 500.0, f"preview total = 450 + 50 delivery (got {preview.get('total_egp')})")
    check(order_call(confirmed=True).get("reason") == "customer_has_not_confirmed_yet", "confirming in the same turn is refused")

    db.add(Message(conversation_id=conv.id, direction=MessageDirection.IN, body="ايوه اكد"))  # the customer's yes
    db.commit()
    done = order_call(confirmed=True)
    check(done.get("ok") is True and "order_ref" in done, f"after the customer replies, the order is created ({done.get('order_ref')})")

    orders = db.scalars(select(Order).where(Order.conversation_id == conv.id)).all()
    check(len(orders) == 1 and orders[0].total == Decimal("500.00"), "exactly one order saved with total 500")
    reservation = db.scalar(select(Reservation).where(Reservation.conversation_id == conv.id))
    check(reservation.status == ReservationStatus.CONFIRMED, "the held item is now CONFIRMED")
    check(order_call(confirmed=True).get("already_created") is True, "asking again does not create a second order")

    print("\n--- Questions for the team ---")
    result = run_tool(db, seller, conv, "ask_shop_team", json.dumps({"question": "الهودي خامته ايه؟"}))
    saved = db.scalars(select(ShopQuestion).where(ShopQuestion.conversation_id == conv.id)).all()
    check(result.get("ok") is True and len(saved) == 1, "a question is saved for the team")


def main() -> None:
    run_pure_checks()
    db = SessionLocal()
    try:
        seller = db.scalar(select(Seller).where(Seller.name == DEMO_NAME))
        if seller is None:
            print("\nDemo store not found. Run:  python -m app.seed")
            return
        run_flow_checks(db, seller)
        print("\nAll checks passed." if failures == 0 else f"\n{failures} check(s) failed.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
