"""Access to the local, single-store demo workspace."""
import secrets

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import get_db
from app.demo.seed import DEMO_NAME
from app.models import Seller

bearer = HTTPBearer(auto_error=False)


def require_demo_access(credentials: HTTPAuthorizationCredentials | None = Depends(bearer)) -> None:
    if not settings.demo_api_key:
        raise HTTPException(503, detail="demo_api_key_not_configured")
    if not credentials or not secrets.compare_digest(credentials.credentials.encode(), settings.demo_api_key.encode()):
        raise HTTPException(401, detail="invalid_demo_api_key", headers={"WWW-Authenticate": "Bearer"})


def get_demo_seller(db: Session = Depends(get_db), access: None = Depends(require_demo_access)) -> Seller:
    seller = db.scalar(select(Seller).where(Seller.name == DEMO_NAME))
    if seller is None:
        raise HTTPException(503, detail="demo_store_not_seeded")
    return seller


def require_live_chat(access: None = Depends(require_demo_access)) -> None:
    if not settings.live_chat_enabled:
        raise HTTPException(503, detail="live_chat_disabled")
