"""Creates a fake store for testing. Safe to run again: it wipes and recreates the demo store.

Run from the project root:  python -m app.seed
"""
from decimal import Decimal

from sqlalchemy import delete, select

from app.db import SessionLocal
from app.models import (
    Channel,
    ChannelType,
    DeliveryZone,
    Faq,
    Order,
    OrderItem,
    Product,
    Reservation,
    Seller,
    Variant,
)

DEMO_NAME = "Demo Store"

# Colors are stored in English (lowercase). Arabic/Franco color words are mapped in services/catalog.py.
PRODUCTS = [
    {
        "code": "H-014", "name": "Q1 Long Sleeve Hoodie", "category": "hoodies", "price": "450",
        "nicknames": ["هودي كيو وان", "q1 hoodie"],
        "variants": [("brown", "M", 3), ("brown", "L", 0)],
    },
    {
        "code": "H-022", "name": "Oversized Hoodie", "category": "hoodies", "price": "520",
        "nicknames": ["هودي اوفر سايز", "اوفرسايز"],
        "variants": [("brown", "M", 1), ("brown", "L", 2)],   # M has ONE piece: used by the concurrency test
    },
    {
        "code": "H-031", "name": "Basic Black Hoodie", "category": "hoodies", "price": "380",
        "nicknames": ["هودي اسود بيسك"],
        "variants": [("black", "M", 5), ("black", "L", 3)],
    },
    {
        "code": "T-005", "name": "Wide Leg Open Trousers", "category": "trousers", "price": "799",
        "nicknames": ["بنطلون واسع"],
        "variants": [("black", "30", 4), ("black", "32", 2), ("beige", "30", 3)],
    },
]


def seed(quiet: bool = False) -> None:
    db = SessionLocal()
    try:
        # Wipe the old demo store. Orders and reservations point at variants, customers and conversations with
        # "no cascade" links (on purpose: deleting a product must never silently delete real orders), so we remove
        # them first, children before parents. Everything else is removed by the seller's cascade.
        old_seller_ids = select(Seller.id).where(Seller.name == DEMO_NAME)
        db.execute(delete(Reservation).where(Reservation.seller_id.in_(old_seller_ids)))
        old_order_ids = select(Order.id).where(Order.seller_id.in_(old_seller_ids))
        db.execute(delete(OrderItem).where(OrderItem.order_id.in_(old_order_ids)))
        db.execute(delete(Order).where(Order.seller_id.in_(old_seller_ids)))
        db.execute(delete(Seller).where(Seller.name == DEMO_NAME))

        seller = Seller(
            name=DEMO_NAME,
            tone="friendly",
            working_hours="10:00 - 22:00 يوميا",
            payment_info="الدفع عند الاستلام أو انستاباي",
            return_policy="الاستبدال خلال 14 يوم لو المنتج بحالته",
            delivery_policy="التوصيل خلال 2 الى 4 ايام عمل",
        )
        db.add(seller)
        db.flush()  # gives the seller its id

        db.add(Channel(seller_id=seller.id, type=ChannelType.WHATSAPP, external_id="TEST_PHONE_NUMBER_ID"))

        for item in PRODUCTS:
            product = Product(
                seller_id=seller.id,
                code=item["code"],
                name=item["name"],
                category=item["category"],
                price=Decimal(item["price"]),
                nicknames=item["nicknames"],
            )
            for color, size, stock in item["variants"]:
                product.variants.append(Variant(seller_id=seller.id, color=color, size=size, stock=stock))
            db.add(product)

        for area, fee in [("Cairo", "50"), ("Giza", "50"), ("Alexandria", "80")]:
            db.add(DeliveryZone(seller_id=seller.id, area=area, fee=Decimal(fee)))

        db.add(Faq(seller_id=seller.id, question="ينفع استبدل؟", answer="ايوه، الاستبدال متاح خلال 14 يوم لو المنتج بحالته."))
        db.add(Faq(seller_id=seller.id, question="الدفع ازاي؟", answer="الدفع عند الاستلام او انستاباي."))

        db.commit()
        variants = sum(len(p["variants"]) for p in PRODUCTS)
        if not quiet:
            print(f"Seeded '{DEMO_NAME}': {len(PRODUCTS)} products, {variants} variants. seller_id={seller.id}")
    finally:
        db.close()


if __name__ == "__main__":
    seed()