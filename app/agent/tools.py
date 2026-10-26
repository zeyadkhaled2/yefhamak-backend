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

from app.models import Conversation, ConversationStatus, Reservation, ReservationStatus, Seller
from app.services.catalog import search_products
from app.services.inventory import RESERVATION_MINUTES, available_quantity, reserve_item

logger = logging.getLogger(__name__)


# ---------- What the model must send (Pydantic checks it before our code runs) ----------

class SearchArgs(BaseModel):
    query: str = Field(min_length=1, max_length=200)


class ReserveArgs(BaseModel):
    variant_ref: str = Field(pattern=r"^v\d{1,3}$")
    quantity: int = Field(default=1, ge=1, le=5)


class HandoffArgs(BaseModel):
    reason: str = Field(max_length=300)


def _tool(name: str, description: str, model: type[BaseModel]) -> dict:
    schema = model.model_json_schema()
    schema.pop("title", None)
    return {"type": "function", "function": {"name": name, "description": description, "parameters": schema}}


# The list we send to the LLM so it knows what it can do
TOOLS = [
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
        "handoff_to_human",
        "Pass the chat to a human at the shop. Use when unsure, the customer is upset, or the request is about "
        "refunds, complaints, custom requests, or anything beyond product questions and reservations.",
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
        instruction = "Nothing matches. Tell the customer you will check with the team, or offer to hand off."
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


def _handoff(db: Session, seller: Seller, conversation: Conversation, args: HandoffArgs) -> dict:
    conversation.status = ConversationStatus.HANDOFF
    db.commit()
    return {"ok": True, "note": "A human from the shop will take over. Tell the customer the team will reply soon."}


HANDLERS = {
    "search_products": (SearchArgs, _search),
    "reserve_item": (ReserveArgs, _reserve),
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
