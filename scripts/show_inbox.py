"""The shop's view for now: prints the orders and the questions waiting for the team.

    python -m scripts.show_inbox
"""
from sqlalchemy import select

from app.db.session import SessionLocal
from app.models import Order, Product, Seller, ShopQuestion, ShopQuestionStatus, Variant
from app.demo.seed import DEMO_NAME


def main() -> None:
    db = SessionLocal()
    try:
        seller = db.scalar(select(Seller).where(Seller.name == DEMO_NAME))
        if seller is None:
            print("Demo store not found. Run:  python -m app.demo.seed")
            return

        orders = db.scalars(select(Order).where(Order.seller_id == seller.id).order_by(Order.created_at.desc())).all()
        print(f"=== ORDERS ({len(orders)}) ===")
        for order in orders:
            print(f"\n#{str(order.id)[:8]}  {order.status.value}  {order.created_at:%Y-%m-%d %H:%M}")
            print(f"  Customer: {order.customer_name}  {order.phone}")
            print(f"  Deliver to: {order.address} ({order.area})")
            for item in order.items:
                variant = db.get(Variant, item.variant_id)
                product = db.get(Product, variant.product_id)
                print(f"  - {item.quantity} x {product.name} {variant.color} {variant.size} @ {item.unit_price}")
            print(f"  Delivery fee: {order.delivery_fee}   TOTAL: {order.total} EGP")

        questions = db.scalars(
            select(ShopQuestion)
            .where(ShopQuestion.seller_id == seller.id, ShopQuestion.status == ShopQuestionStatus.OPEN)
            .order_by(ShopQuestion.created_at.desc())
        ).all()
        print(f"\n=== QUESTIONS FOR THE TEAM ({len(questions)}) ===")
        for q in questions:
            print(f"  [{q.created_at:%Y-%m-%d %H:%M}] {q.question}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
