"""Queries for the demo HTTP workspace, always scoped to one seller."""
from uuid import UUID, uuid4

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models import (
    ChannelType, Conversation, ConversationStatus, Customer, Message,
    Order, OrderItem, OrderStatus, Product, Seller, Variant,
)


class WorkspaceNotFound(LookupError):
    """A requested resource does not exist in the selected seller workspace."""


def create_conversation(db: Session, seller: Seller) -> Conversation:
    # Reuse the existing demo channel representation; no WhatsApp transport is involved.
    customer = Customer(seller_id=seller.id, channel_type=ChannelType.WHATSAPP, external_id=f"web-demo-{uuid4()}")
    conversation = Conversation(seller_id=seller.id, status=ConversationStatus.BOT)
    try:
        db.add(customer)
        db.flush()
        conversation.customer_id = customer.id
        db.add(conversation)
        db.commit()
        db.refresh(conversation)
        return conversation
    except Exception:
        db.rollback()
        raise


def get_conversation(db: Session, seller_id: UUID, conversation_id: UUID) -> Conversation:
    conversation = db.scalar(select(Conversation).where(Conversation.id == conversation_id, Conversation.seller_id == seller_id))
    if conversation is None:
        raise WorkspaceNotFound("conversation_not_found")
    return conversation


def messages(db: Session, conversation: Conversation, limit: int, offset: int):
    return db.scalars(select(Message).where(Message.conversation_id == conversation.id)
                      .order_by(Message.created_at, Message.id).limit(limit).offset(offset)).all()


def list_orders(db: Session, seller_id: UUID, status: OrderStatus | None, query: str | None, limit: int, offset: int):
    filters = [Order.seller_id == seller_id]
    if status:
        filters.append(Order.status == status)
    if query:
        filters.append(or_(Order.customer_name.icontains(query, autoescape=True), Order.phone.icontains(query, autoescape=True)))
    total = db.scalar(select(func.count()).select_from(Order).where(*filters)) or 0
    orders = db.scalars(select(Order).where(*filters).order_by(Order.created_at.desc(), Order.id.desc()).limit(limit).offset(offset)).all()
    return orders, total


def get_order(db: Session, seller_id: UUID, order_id: UUID):
    order = db.scalar(select(Order).where(Order.id == order_id, Order.seller_id == seller_id))
    if order is None:
        raise WorkspaceNotFound("order_not_found")
    items = db.execute(select(OrderItem, Variant, Product)
                       .join(Variant, Variant.id == OrderItem.variant_id)
                       .join(Product, Product.id == Variant.product_id)
                       .where(OrderItem.order_id == order.id, Variant.seller_id == seller_id, Product.seller_id == seller_id)
                       .order_by(OrderItem.id)).all()
    return order, items
