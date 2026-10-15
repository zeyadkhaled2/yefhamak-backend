"""Database tables for Yefhamak (SQLAlchemy 2.0 style).

Every business table carries seller_id so one database serves many sellers
and queries are always filtered by seller.
"""
import enum
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Numeric,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import String

from app.db import Base


# ---------- Small helpers (so columns below stay short) ----------

def uuid_pk():
    return mapped_column(primary_key=True, default=uuid.uuid4)


def created_at_col():
    return mapped_column(DateTime(timezone=True), server_default=func.now())


def pg_enum(enum_cls):
    """Store the enum's values (e.g. 'PILOT') in a native Postgres enum type."""
    return Enum(
        enum_cls,
        name=enum_cls.__name__.lower(),
        values_callable=lambda e: [m.value for m in e],
    )


# ---------- Enums ----------

class SellerStatus(str, enum.Enum):
    PILOT = "PILOT"
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"


class ChannelType(str, enum.Enum):
    WHATSAPP = "WHATSAPP"
    INSTAGRAM = "INSTAGRAM"  # later; the same tables already support it


class ConversationStatus(str, enum.Enum):
    BOT = "BOT"            # the bot is handling it
    HANDOFF = "HANDOFF"    # a human took over, the bot stays silent
    CLOSED = "CLOSED"


class MessageDirection(str, enum.Enum):
    IN = "IN"    # customer -> bot
    OUT = "OUT"  # bot or seller -> customer


class ReservationStatus(str, enum.Enum):
    ACTIVE = "ACTIVE"        # item is held, waiting for the customer
    CONFIRMED = "CONFIRMED"  # attached to a real order
    EXPIRED = "EXPIRED"      # hold ran out, stock released
    RELEASED = "RELEASED"    # cancelled manually, stock released


class OrderStatus(str, enum.Enum):
    PENDING = "PENDING"      # collected by the bot, waiting for the seller
    CONFIRMED = "CONFIRMED"
    CANCELLED = "CANCELLED"


# ---------- Sellers and channels ----------

class Seller(Base):
    __tablename__ = "sellers"

    id: Mapped[uuid.UUID] = uuid_pk()
    name: Mapped[str]
    status: Mapped[SellerStatus] = mapped_column(
        pg_enum(SellerStatus), default=SellerStatus.PILOT, server_default=SellerStatus.PILOT.value
    )
    tone: Mapped[str] = mapped_column(default="friendly", server_default="friendly")
    working_hours: Mapped[str | None]
    payment_info: Mapped[str | None] = mapped_column(Text)
    return_policy: Mapped[str | None] = mapped_column(Text)
    delivery_policy: Mapped[str | None] = mapped_column(Text)
    sheet_id: Mapped[str | None]
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = created_at_col()

    channels: Mapped[list["Channel"]] = relationship(back_populates="seller", cascade="all, delete-orphan")
    products: Mapped[list["Product"]] = relationship(back_populates="seller", cascade="all, delete-orphan")


class Channel(Base):
    """A connected WhatsApp number (or later an Instagram page). Incoming messages are matched to a seller by external_id."""
    __tablename__ = "channels"
    __table_args__ = (UniqueConstraint("type", "external_id", name="uq_channel_type_external"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    seller_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sellers.id", ondelete="CASCADE"), index=True)
    type: Mapped[ChannelType] = mapped_column(pg_enum(ChannelType))
    external_id: Mapped[str]  # WhatsApp phone_number_id (from Meta), or an Instagram page id
    access_token_enc: Mapped[str | None] = mapped_column(Text)  # ENCRYPT before saving
    active: Mapped[bool] = mapped_column(default=True, server_default=text("true"))
    created_at: Mapped[datetime] = created_at_col()

    seller: Mapped["Seller"] = relationship(back_populates="channels")


# ---------- Catalog and stock ----------

class Product(Base):
    __tablename__ = "products"
    __table_args__ = (
        UniqueConstraint("seller_id", "code", name="uq_product_seller_code"),
        Index("ix_products_seller_active", "seller_id", "active"),
        CheckConstraint("price >= 0", name="product_price_ok"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    seller_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sellers.id", ondelete="CASCADE"))
    code: Mapped[str]  # internal id like H-014, customers never see it
    name: Mapped[str]
    nicknames: Mapped[list[str]] = mapped_column(ARRAY(String), default=list, server_default=text("'{}'"))
    category: Mapped[str | None]
    description: Mapped[str | None] = mapped_column(Text)
    price: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    photo_url: Mapped[str | None]
    active: Mapped[bool] = mapped_column(default=True, server_default=text("true"))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    seller: Mapped["Seller"] = relationship(back_populates="products")
    variants: Mapped[list["Variant"]] = relationship(back_populates="product", cascade="all, delete-orphan")


class Variant(Base):
    """Stock lives here (product + color + size). available = stock - reserved."""
    __tablename__ = "variants"
    __table_args__ = (
        UniqueConstraint("product_id", "color", "size", name="uq_variant_product_color_size"),
        # Makes bad stock numbers impossible, even if our code has a bug.
        CheckConstraint("stock >= 0 AND reserved >= 0 AND reserved <= stock", name="variant_stock_ok"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    seller_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sellers.id", ondelete="CASCADE"), index=True)
    product_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"))
    color: Mapped[str] = mapped_column(default="", server_default="")
    size: Mapped[str] = mapped_column(default="", server_default="")
    stock: Mapped[int] = mapped_column(default=0, server_default="0")     # set by the Sheet sync
    reserved: Mapped[int] = mapped_column(default=0, server_default="0")  # changed ONLY by reservation logic
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    product: Mapped["Product"] = relationship(back_populates="variants")


class DeliveryZone(Base):
    __tablename__ = "delivery_zones"
    __table_args__ = (UniqueConstraint("seller_id", "area", name="uq_zone_seller_area"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    seller_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sellers.id", ondelete="CASCADE"))
    area: Mapped[str]
    fee: Mapped[Decimal] = mapped_column(Numeric(10, 2))


class Faq(Base):
    __tablename__ = "faqs"

    id: Mapped[uuid.UUID] = uuid_pk()
    seller_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sellers.id", ondelete="CASCADE"), index=True)
    question: Mapped[str] = mapped_column(Text)
    answer: Mapped[str] = mapped_column(Text)


# ---------- Customers and conversations ----------

class Customer(Base):
    __tablename__ = "customers"
    __table_args__ = (
        UniqueConstraint("seller_id", "channel_type", "external_id", name="uq_customer_seller_channel_ext"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    seller_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sellers.id", ondelete="CASCADE"))
    channel_type: Mapped[ChannelType] = mapped_column(pg_enum(ChannelType))
    external_id: Mapped[str]  # the customer's WhatsApp number (wa_id), or an Instagram user id
    name: Mapped[str | None]
    created_at: Mapped[datetime] = created_at_col()


class Conversation(Base):
    __tablename__ = "conversations"
    __table_args__ = (Index("ix_conversations_seller_status", "seller_id", "status"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    seller_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sellers.id", ondelete="CASCADE"))
    customer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("customers.id", ondelete="CASCADE"), index=True)
    status: Mapped[ConversationStatus] = mapped_column(
        pg_enum(ConversationStatus),
        default=ConversationStatus.BOT,
        server_default=ConversationStatus.BOT.value,
    )
    # Bot memory, e.g. {"current_variant_id": "...", "draft_order": {...}}
    state: Mapped[dict] = mapped_column(JSONB, default=dict, server_default=text("'{}'::jsonb"))
    # Needed for WhatsApp's 24-hour customer service window (replies inside it are free)
    last_customer_message_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = created_at_col()

    messages: Mapped[list["Message"]] = relationship(back_populates="conversation", cascade="all, delete-orphan")


class Message(Base):
    __tablename__ = "messages"
    __table_args__ = (Index("ix_messages_conversation_created", "conversation_id", "created_at"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    conversation_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("conversations.id", ondelete="CASCADE"))
    direction: Mapped[MessageDirection] = mapped_column(pg_enum(MessageDirection))
    # WhatsApp message id (wamid...); unique, so a webhook delivered twice is only stored once.
    channel_message_id: Mapped[str | None] = mapped_column(unique=True)
    body: Mapped[str] = mapped_column(Text)

    # Cost tracking per message (feeds your pricing and eval numbers)
    model: Mapped[str | None]
    tokens_in: Mapped[int | None]
    tokens_out: Mapped[int | None]
    latency_ms: Mapped[int | None]

    created_at: Mapped[datetime] = created_at_col()

    conversation: Mapped["Conversation"] = relationship(back_populates="messages")


# ---------- Reservations and orders ----------

class Order(Base):
    __tablename__ = "orders"
    __table_args__ = (Index("ix_orders_seller_status_created", "seller_id", "status", "created_at"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    seller_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sellers.id", ondelete="CASCADE"))
    customer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("customers.id"))
    conversation_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("conversations.id"))
    status: Mapped[OrderStatus] = mapped_column(
        pg_enum(OrderStatus), default=OrderStatus.PENDING, server_default=OrderStatus.PENDING.value
    )

    customer_name: Mapped[str]
    phone: Mapped[str]
    address: Mapped[str] = mapped_column(Text)
    area: Mapped[str | None]
    delivery_fee: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=0, server_default="0")
    total: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = created_at_col()

    items: Mapped[list["OrderItem"]] = relationship(back_populates="order", cascade="all, delete-orphan")


class OrderItem(Base):
    __tablename__ = "order_items"
    __table_args__ = (CheckConstraint("quantity > 0", name="order_item_qty_ok"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    order_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("orders.id", ondelete="CASCADE"), index=True)
    variant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("variants.id"))
    quantity: Mapped[int]
    unit_price: Mapped[Decimal] = mapped_column(Numeric(10, 2))

    order: Mapped["Order"] = relationship(back_populates="items")


class Reservation(Base):
    __tablename__ = "reservations"
    __table_args__ = (
        Index("ix_reservations_status_expires", "status", "expires_at"),  # the expiry job scans this
        CheckConstraint("quantity > 0", name="reservation_qty_ok"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    seller_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sellers.id", ondelete="CASCADE"), index=True)
    variant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("variants.id"))
    conversation_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("conversations.id"))
    order_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("orders.id"))
    quantity: Mapped[int] = mapped_column(default=1, server_default="1")
    status: Mapped[ReservationStatus] = mapped_column(
        pg_enum(ReservationStatus),
        default=ReservationStatus.ACTIVE,
        server_default=ReservationStatus.ACTIVE.value,
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = created_at_col()