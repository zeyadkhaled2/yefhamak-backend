"""Persist a request before calling tools; cache its result for safe transport retries."""
import hashlib
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import ChatRequest


class RequestConflict(ValueError):
    pass


def existing(request: ChatRequest, conversation_id: UUID, text_hash: str) -> dict:
    if request.conversation_id != conversation_id or request.text_hash != text_hash:
        raise RequestConflict("request_id_reused")
    if request.response is None:
        raise RequestConflict("request_in_progress")
    return request.response


def claim(db: Session, request_id: UUID, conversation_id: UUID, text: str) -> dict | None:
    digest = hashlib.sha256(text.encode()).hexdigest()
    request = db.get(ChatRequest, request_id)
    if request is not None:
        return existing(request, conversation_id, digest)
    try:
        db.add(ChatRequest(id=request_id, conversation_id=conversation_id, text_hash=digest))
        db.commit()  # Survives the agent/tool commits and a dropped HTTP connection.
    except IntegrityError:
        db.rollback()
        request = db.get(ChatRequest, request_id)
        if request is not None:
            return existing(request, conversation_id, digest)
        raise RequestConflict("conversation_busy")
    return None


def finish(db: Session, request_id: UUID, response: dict) -> None:
    request = db.get(ChatRequest, request_id)
    request.response = response
    db.commit()
