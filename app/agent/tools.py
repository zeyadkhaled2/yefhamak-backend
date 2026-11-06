"""The tools the LLM is allowed to use. Each tool is just a normal function that calls our services.

The LLM never sees database ids. After a search, each variant gets a short reference like "v1", "v2".
The model passes that reference back when it wants to reserve something, and we translate it to the real id.
"""
import json
import logging
import uuid

from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    Conversation,
    ConversationStatus,
    DeliveryZone,
    Reservation,
    ReservationStatus,
    Seller,
    ShopQuestion,
)
from app.services.catalog import search_products
from app.services.knowledge import search_knowledge
from app.services.inventory import RESERVATION_MINUTES, available_quantity, reserve_item
from app.services.orders import (
    count_customer_messages,
    create_order,
    order_summary,
    public_summary,
    validate_details,
)

logger = logging.getLogger(__name__)


# ---------- What the model must send (Pydantic checks it before our code runs) ----------

class SearchArgs(BaseModel):
    query: str = Field(min_length=1, max_length=200)


class ReserveArgs(BaseModel):
    variant_ref: str = Field(pattern=r"^v\d{1,3}$")
    quantity: int = Field(default=1, ge=1, le=5)


class CreateOrderArgs(BaseModel):
    customer_name: str = Field(min_length=2, max_length=60)
    phone: str = Field(min_length=8, max_length=20)
    address: str = Field(min_length=8, max_length=300)
    area: str = Field(min_length=2, max_length=60)
    confirmed: bool = False


class AskTeamArgs(BaseModel):
    question: str = Field(min_length=3, max_length=500)


class HandoffArgs(BaseModel):
    reason: str = Field(max_length=300)


def _tool(name: str, description: str, model: type[BaseModel]) -> dict:
    schema = model.model_json_schema()
    schema.pop("title", None)
    return {"type": "function", "function": {"name": name, "description": description, "parameters": schema}}


# The list we send to the LLM so it knows what it can do
TOOLS = [
    _tool("search_store_knowledge", "Retrieve store document passages about care, materials, sizing guidance and policies. "
          "Use before answering these questions or escalating missing product information. "
          "Include the product name and the customer question. Never use this for live price or stock.", SearchArgs),
    _tool(
        "search_products",
        "Search the shop's catalog. Pass what the customer asked for in their own words (product type, color, size). "
        "ALWAYS use this for any question about a product, price, size or stock.",
        SearchArgs,
    ),
    _tool(
        "reserve_item",
        "Hold one item for the customer for a short time. Only call this AFTER the customer clearly confirmed the "
        "product, color, size and quantity. variant_ref must be a ref (like v2) from a search result.",
        ReserveArgs,
    ),
    _tool(
        "create_order",
        "Create the customer's order from the items currently held for them. First call with confirmed=false to get a "
        "summary with prices and the delivery fee, read it back, and wait for the customer's reply. Only after their "
        "clear yes call again with confirmed=true and the same details. area is the delivery city (for example Cairo, Giza, Alexandria).",
        CreateOrderArgs,
    ),
    _tool(
        "ask_shop_team",
        "Save a question for the shop team when the customer asks something you cannot answer from the tools or the shop info "
        "(material, discounts, custom requests). Pass the customer's question in their own words.",
        AskTeamArgs,
    ),
    _tool(
        "handoff_to_human",
        "Pass the chat to a human at the shop. Use when the customer is upset, or the request is about refunds, "
        "complaints, or anything beyond product questions, reservations and orders.",
        HandoffArgs,
    ),
]


# ---------- The functions behind each tool ----------

def _search(db: Session, seller: Seller, conversation: Conversation, args: SearchArgs) -> dict:
    result = search_products(db, seller.id, args.query)

    refs: dict[str, str] = {}   # "v1" -> real variant id (kept in our database, never shown to the model)
    matches = []
    for m in result["matches"]:
        variants = []
        for v in m["variants"]:
            ref = f"v{len(refs) + 1}"
            refs[ref] = v["variant_id"]
            variants.append({"ref": ref, "color": v["color"], "size": v["size"], "available": v["available"]})
        matches.append({
            "name": m["name"],
            "price_egp": m["price"],
            "variants": variants,
            "matches_requested_options": m["matches_requested_options"],
        })

    if matches:  # remember what we showed, so "yes, reserve it" works on the next turn
        conversation.state = {**(conversation.state or {}), "last_search": matches, "refs": refs}
        db.commit()

    if not matches:
        instruction = "Nothing matches. Tell the customer you don't have it, and call ask_shop_team with what they wanted."
    elif result["needs_clarification"]:
        instruction = "More than one product matches. Ask the customer which one they mean. Do not choose for them."
    else:
        instruction = "One product matches. Confirm details with the customer."

    return {
        "count": len(matches),
        "needs_clarification": result["needs_clarification"],
        "requested_sizes": result.get("requested_sizes", []),
        "matches": matches,
        "instruction": instruction,
    }


def _reserve(db: Session, seller: Seller, conversation: Conversation, args: ReserveArgs) -> dict:
    refs = (conversation.state or {}).get("refs", {})
    variant_id_str = refs.get(args.variant_ref)
    if variant_id_str is None:
        return {"ok": False, "reason": "unknown_variant_ref"}  # the model invented a ref, or never searched
    variant_id = uuid.UUID(variant_id_str)

    # Already holding this exact item for this customer? Don't reserve twice.
    existing = db.scalar(
        select(Reservation).where(
            Reservation.conversation_id == conversation.id,
            Reservation.variant_id == variant_id,
            Reservation.status == ReservationStatus.ACTIVE,
        )
    )
    if existing:
        return {"ok": True, "already_reserved": True, "held_for_minutes": RESERVATION_MINUTES}

    reservation = reserve_item(db, seller.id, variant_id, conversation.id, args.quantity)
    if reservation is None:
        return {"ok": False, "reason": "not_enough_stock", "available": available_quantity(db, seller.id, variant_id)}
    return {"ok": True, "held_for_minutes": RESERVATION_MINUTES}


def _create_order(db: Session, seller: Seller, conversation: Conversation, args: CreateOrderArgs) -> dict:
    state = conversation.state or {}
    zones = list(db.scalars(select(DeliveryZone).where(DeliveryZone.seller_id == seller.id)).all())

    details, zone, error = validate_details(args.customer_name, args.phone, args.address, args.area, zones)
    if error:
        return error

    summary = order_summary(db, conversation, zone)
    if summary is None:
        last = state.get("last_order")
        if last and args.confirmed:  # the order was already created; don't create it twice
            return {"ok": True, "already_created": True, **last}
        return {"ok": False, "reason": "nothing_reserved", "hint": "Reserve an item for the customer first."}

    customer_messages = count_customer_messages(db, conversation.id)

    if not args.confirmed:  # step 1: preview. Nothing is saved except a note of what was previewed.
        conversation.state = {**state, "order_preview": {"details": details, "customer_messages": customer_messages}}
        db.commit()
        return {
            "ok": True,
            "preview": True,
            **public_summary(summary, zone.area),
            "next_step": "Read this summary back to the customer and ask them to confirm. "
                         "After their yes, call create_order again with confirmed=true.",
        }

    # step 2: commit. Two rules enforced here in code, whatever the model says:
    preview = state.get("order_preview")
    if not preview or preview["details"] != details:
        return {"ok": False, "reason": "details_not_previewed",
                "hint": "Call create_order with confirmed=false first and read the summary to the customer."}
    if customer_messages <= preview["customer_messages"]:
        return {"ok": False, "reason": "customer_has_not_confirmed_yet",
                "hint": "Ask the customer to confirm and wait for their reply."}

    order = create_order(db, seller, conversation, details, summary)
    if order is None:
        conversation.state = {k: v for k, v in state.items() if k != "order_preview"}
        db.commit()
        return {"ok": False, "reason": "reservation_expired",
                "hint": "The hold ran out. Offer to reserve the item again."}

    totals = {
        "order_ref": str(order.id)[:8],
        "subtotal_egp": float(summary["subtotal"]),
        "delivery_fee_egp": float(summary["delivery_fee"]),
        "total_egp": float(summary["total"]),
    }
    conversation.state = {**{k: v for k, v in state.items() if k != "order_preview"}, "last_order": totals}
    db.commit()
    return {"ok": True, **totals, "note": "Order sent to the shop team for review. Do not promise a delivery date. Payment is arranged by the team."}


def _ask_team(db: Session, seller: Seller, conversation: Conversation, args: AskTeamArgs) -> dict:
    db.add(ShopQuestion(seller_id=seller.id, conversation_id=conversation.id, question=args.question))
    db.commit()
    return {
        "ok": True,
        "note": "Saved for the shop team. Tell the customer their question was passed on. "
                "Do not offer to wait, and do not promise when the team will answer. Keep helping with anything else.",
    }


def _handoff(db: Session, seller: Seller, conversation: Conversation, args: HandoffArgs) -> dict:
    conversation.status = ConversationStatus.HANDOFF
    db.commit()
    return {"ok": True, "note": "A human from the shop will take over. Tell the customer the team will reply soon."}


def _knowledge(db: Session, seller: Seller, conversation: Conversation, args: SearchArgs) -> dict:
    return search_knowledge(db, seller.id, args.query)


HANDLERS = {
    "search_store_knowledge": (SearchArgs, _knowledge),
    "search_products": (SearchArgs, _search),
    "reserve_item": (ReserveArgs, _reserve),
    "create_order": (CreateOrderArgs, _create_order),
    "ask_shop_team": (AskTeamArgs, _ask_team),
    "handoff_to_human": (HandoffArgs, _handoff),
}


def run_tool(db: Session, seller: Seller, conversation: Conversation, name: str, raw_arguments: str) -> dict:
    """Runs one tool call safely. Anything wrong comes back as a small error the model can read and recover from."""
    handler = HANDLERS.get(name)
    if handler is None:
        return {"error": f"unknown_tool: {name}"}
    model, fn = handler

    try:
        raw = json.loads(raw_arguments or "{}")
    except json.JSONDecodeError:
        return {"error": "arguments_were_not_valid_json"}

    try:
        args = model.model_validate(raw)
    except ValidationError as e:
        return {"error": "invalid_arguments", "details": str(e)[:300]}

    try:
        return fn(db, seller, conversation, args)
    except Exception:
        db.rollback()
        logger.exception("tool %s failed", name)
        return {"error": "tool_failed"}
