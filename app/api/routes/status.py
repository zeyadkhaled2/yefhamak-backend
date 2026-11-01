from fastapi import APIRouter, Depends

from app.api.dependencies import get_demo_seller
from app.core.config import settings
from app.models import Seller

router = APIRouter(prefix="/api/demo", tags=["demo connection"])


@router.get("/status")
def status(seller: Seller = Depends(get_demo_seller)):
    return {"store": seller.name, "live_chat_enabled": settings.live_chat_enabled}
