"""Chat with the bot in your terminal.

    python -m scripts.chat          continue the last test conversation
    python -m scripts.chat --new    start a fresh conversation

Type 'exit' to quit. Lines starting with [tool] show what the bot looked up.
Held items stay reserved for 20 minutes; run `python -m app.demo.seed` to reset the whole demo store.
"""
import sys

from sqlalchemy import select

from app.agent.loop import handle_message
from app.db.session import SessionLocal
from app.models import ChannelType, Conversation, ConversationStatus, Customer, Seller
from app.demo.seed import DEMO_NAME

CLI_CUSTOMER_ID = "cli-test"


def main() -> None:
    db = SessionLocal()
    try:
        seller = db.scalar(select(Seller).where(Seller.name == DEMO_NAME))
        if seller is None:
            print("Demo store not found. Run:  python -m app.demo.seed")
            return

        customer = db.scalar(
            select(Customer).where(
                Customer.seller_id == seller.id,
                Customer.channel_type == ChannelType.WHATSAPP,
                Customer.external_id == CLI_CUSTOMER_ID,
            )
        )
        if customer is None:
            customer = Customer(seller_id=seller.id, channel_type=ChannelType.WHATSAPP, external_id=CLI_CUSTOMER_ID)
            db.add(customer)
            db.flush()

        conversation = None
        if "--new" not in sys.argv:
            conversation = db.scalar(
                select(Conversation)
                .where(Conversation.customer_id == customer.id)
                .order_by(Conversation.created_at.desc())
                .limit(1)
            )
        if conversation is None or conversation.status != ConversationStatus.BOT:
            conversation = Conversation(seller_id=seller.id, customer_id=customer.id)
            db.add(conversation)
        db.commit()

        print(f"Chatting with '{seller.name}'. Type 'exit' to quit.\n")
        while True:
            text = input("You: ").strip()
            if text.lower() in {"exit", "quit"}:
                break
            if not text:
                continue
            reply = handle_message(db, seller, conversation, text, debug=True)
            print(f"Bot: {reply or '(a human has taken over this chat)'}\n")
    finally:
        db.close()


if __name__ == "__main__":
    main()
