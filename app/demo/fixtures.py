"""Shared database fixtures for demo checks and evaluations."""
import uuid

from app.models import ChannelType, Conversation, Customer


def make_conversation(db, seller_id) -> Conversation:
    customer = Customer(seller_id=seller_id, channel_type=ChannelType.WHATSAPP, external_id=f"test-{uuid.uuid4().hex[:8]}")
    db.add(customer)
    db.flush()
    conversation = Conversation(seller_id=seller_id, customer_id=customer.id)
    db.add(conversation)
    db.commit()
    return conversation
