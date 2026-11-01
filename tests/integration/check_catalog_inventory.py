"""Checks that search and reservations behave. Run after seeding:

    python -m app.demo.seed
    python -m tests.integration.check_catalog_inventory
"""
import threading
from concurrent.futures import ThreadPoolExecutor

from sqlalchemy import select

from app.demo.fixtures import make_conversation
from app.db.session import SessionLocal
from app.models import Product, Reservation, ReservationStatus, Seller, Variant
from app.demo.seed import DEMO_NAME
from app.services.catalog import search_products
from app.services.inventory import (
    available_quantity,
    expire_reservations,
    release_reservation,
    reserve_item,
)

failures = 0


def check(ok: bool, label: str) -> None:
    global failures
    print(("PASS  " if ok else "FAIL  ") + label)
    if not ok:
        failures += 1


def run_search_checks(db, seller) -> None:
    print("\n--- Search ---")
    cases = [
        ("عندكم الهودي البني مقاس M؟ وبكام؟", {"H-014", "H-022"}, True),   # two matches -> must ask
        ("عايز هودي اسود", {"H-031"}, False),
        ("عندكم بنطلون؟", {"T-005"}, False),
        ("hodi aswad", {"H-031"}, False),                                   # Franco-Arabic
        ("عندكم جاكيت؟", set(), False),                                     # not in the catalog
    ]
    for query, expected_codes, expect_clarify in cases:
        result = search_products(db, seller.id, query)
        codes = {m["code"] for m in result["matches"]}
        ok = codes == expected_codes and result["needs_clarification"] == expect_clarify
        check(ok, f"{query!r} -> {sorted(codes)} (needs_clarification={result['needs_clarification']})")


def run_reservation_checks(db, seller) -> None:
    print("\n--- Reservations ---")
    variant = db.scalar(
        select(Variant).join(Product)
        .where(Product.seller_id == seller.id, Product.code == "H-022", Variant.color == "brown", Variant.size == "M")
    )
    conv_a, conv_b = make_conversation(db, seller.id), make_conversation(db, seller.id)
    check(available_quantity(db, seller.id, variant.id) == 1, "last item starts with 1 available")

    # Two customers try to take the last piece at the same moment.
    barrier = threading.Barrier(2)

    def attempt(conversation_id):
        session = SessionLocal()
        try:
            barrier.wait()
            return reserve_item(session, seller.id, variant.id, conversation_id) is not None
        finally:
            session.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt, [conv_a.id, conv_b.id]))
    check(sum(results) == 1, f"two simultaneous reservations: exactly one wins (results={results})")

    db.refresh(variant)
    check(variant.reserved == 1, f"reserved count is 1 (got {variant.reserved})")
    check(reserve_item(db, seller.id, variant.id, conv_a.id) is None, "a third customer is refused")

    winner = db.scalar(select(Reservation).where(Reservation.variant_id == variant.id, Reservation.status == ReservationStatus.ACTIVE))
    check(release_reservation(db, winner.id) is True, "release works")
    check(release_reservation(db, winner.id) is False, "releasing twice does nothing")
    db.refresh(variant)
    check(variant.reserved == 0, f"reserved back to 0 (got {variant.reserved})")

    check(reserve_item(db, seller.id, variant.id, conv_a.id, quantity=2) is None, "asking for more than the stock is refused")

    # Expiry: a hold that has already run out gets released by the job.
    reserve_item(db, seller.id, variant.id, conv_b.id, minutes=0)
    check(expire_reservations(db) >= 1, "expiry job releases an expired hold")
    db.refresh(variant)
    check(variant.reserved == 0, f"reserved back to 0 after expiry (got {variant.reserved})")


def main() -> None:
    db = SessionLocal()
    try:
        seller = db.scalar(select(Seller).where(Seller.name == DEMO_NAME))
        if seller is None:
            print("Demo store not found. Run:  python -m app.demo.seed")
            return
        run_search_checks(db, seller)
        run_reservation_checks(db, seller)
        print("\nAll checks passed." if failures == 0 else f"\n{failures} check(s) failed.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
