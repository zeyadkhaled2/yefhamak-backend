"""Conversation and chat endpoints for a single local demo store."""
from threading import Lock
from uuid import UUID
from weakref import WeakValueDictionary

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.agent.loop import handle_message
from app.api.dependencies import get_demo_seller, require_demo_access, require_live_chat
from app.api.schemas import ChatOut, ConversationOut, MessageIn, MessagePage
from app.db.session import get_db
from app.models import ConversationStatus, Seller
from app.services import workspace

router = APIRouter(prefix="/api/demo/conversations", tags=["demo conversations"], dependencies=[Depends(require_demo_access)])
_locks: WeakValueDictionary = WeakValueDictionary()
_registry_lock = Lock()


def conversation_lock(conversation_id: UUID):
    with _registry_lock:
        lock = _locks.get(conversation_id)
        if lock is None:
            lock = Lock()
            _locks[conversation_id] = lock
        return lock


@router.post("", response_model=ConversationOut, status_code=201)
def create(db: Session = Depends(get_db), seller: Seller = Depends(get_demo_seller)):
    return workspace.create_conversation(db, seller)


@router.get("/{conversation_id}", response_model=ConversationOut)
def read(conversation_id: UUID, db: Session = Depends(get_db), seller: Seller = Depends(get_demo_seller)):
    return workspace.get_conversation(db, seller.id, conversation_id)


@router.get("/{conversation_id}/messages", response_model=MessagePage)
def history(conversation_id: UUID, limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0),
            db: Session = Depends(get_db), seller: Seller = Depends(get_demo_seller)):
    conversation = workspace.get_conversation(db, seller.id, conversation_id)
    return {"items": workspace.messages(db, conversation, limit, offset), "limit": limit, "offset": offset}


@router.post("/{conversation_id}/messages", response_model=ChatOut, dependencies=[Depends(require_live_chat)])
def send(conversation_id: UUID, body: MessageIn, db: Session = Depends(get_db), seller: Seller = Depends(get_demo_seller)):
    # Existing tools commit during each turn. For the local MVP, use one server worker
    # and reject overlapping sends rather than holding a transaction over network calls.
    lock = conversation_lock(conversation_id)
    if not lock.acquire(blocking=False):
        raise HTTPException(409, detail="conversation_busy")
    try:
        conversation = workspace.get_conversation(db, seller.id, conversation_id)
        if conversation.status == ConversationStatus.CLOSED:
            raise HTTPException(409, detail="conversation_closed")
        trace: list[dict] = []
        reply = handle_message(db, seller, conversation, body.text, trace=trace)
        errors = [event["error"] for event in trace if event.get("type") == "error"]
        provider_types = ("RateLimitError", "APIConnectionError", "APITimeoutError", "InternalServerError", "EmptyProviderResponse")
        outcome = "handoff" if conversation.status == ConversationStatus.HANDOFF else "reply"
        if errors:
            outcome = "provider_error" if all(error.startswith(provider_types) for error in errors) else "application_error"
        return {"conversation_id": conversation.id, "status": conversation.status, "reply": reply or None,
                "outcome": outcome, "rate_limited": any(error.startswith("RateLimitError") for error in errors)}
    finally:
        lock.release()
