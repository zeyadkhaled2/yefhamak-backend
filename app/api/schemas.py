"""Public HTTP contracts; internal agent state and provider traces stay private."""
from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models import ConversationStatus, MessageDirection, OrderStatus


class PublicModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class ConversationOut(PublicModel):
    id: UUID
    status: ConversationStatus
    created_at: datetime


class MessageIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: UUID
    text: str = Field(min_length=1, max_length=600)

    @field_validator("text")
    @classmethod
    def nonblank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Message cannot be blank")
        return value


class MessageOut(PublicModel):
    id: UUID
    direction: MessageDirection
    body: str
    created_at: datetime


class MessagePage(BaseModel):
    items: list[MessageOut]
    limit: int
    offset: int


class ChatOut(BaseModel):
    request_id: UUID
    conversation_id: UUID
    status: ConversationStatus
    reply: str | None
    outcome: Literal["reply", "handoff", "provider_error", "application_error"]
    rate_limited: bool = False


class OrderOut(PublicModel):
    id: UUID
    conversation_id: UUID
    status: OrderStatus
    customer_name: str
    phone: str
    address: str
    area: str | None
    delivery_fee: Decimal
    total: Decimal
    created_at: datetime


class OrderItemOut(BaseModel):
    product_name: str
    product_code: str
    color: str
    size: str
    quantity: int
    unit_price: Decimal


class OrderDetail(OrderOut):
    items: list[OrderItemOut]


class OrderPage(BaseModel):
    items: list[OrderOut]
    total: int
    limit: int
    offset: int
