"""Seller-scoped order reads and atomic review actions."""
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.dependencies import get_demo_seller, require_demo_access
from app.api.schemas import OrderDetail, OrderItemOut, OrderOut, OrderPage
from app.db.session import get_db
from app.models import OrderStatus, Seller
from app.services import workspace
from app.services.seller_orders import OrderConflict, review_order

router = APIRouter(prefix="/api/demo/orders", tags=["demo seller orders"], dependencies=[Depends(require_demo_access)])


def review(db, seller, order_id, target):
    try:
        return review_order(db, seller.id, order_id, target)
    except OrderConflict as error:
        raise HTTPException(409, detail=str(error)) from error


@router.post("/{order_id}/confirm", response_model=OrderOut)
def confirm_order(order_id: UUID, db: Session = Depends(get_db), seller: Seller = Depends(get_demo_seller)):
    return review(db, seller, order_id, OrderStatus.CONFIRMED)


@router.post("/{order_id}/cancel", response_model=OrderOut)
def cancel_order(order_id: UUID, db: Session = Depends(get_db), seller: Seller = Depends(get_demo_seller)):
    return review(db, seller, order_id, OrderStatus.CANCELLED)


@router.get("", response_model=OrderPage)
def list_orders(status: OrderStatus | None = None, q: str | None = Query(None, min_length=1, max_length=100),
                limit: int = Query(25, ge=1, le=100), offset: int = Query(0, ge=0),
                db: Session = Depends(get_db), seller: Seller = Depends(get_demo_seller)):
    orders, total = workspace.list_orders(db, seller.id, status, q, limit, offset)
    return {"items": orders, "total": total, "limit": limit, "offset": offset}


@router.get("/{order_id}", response_model=OrderDetail)
def read_order(order_id: UUID, db: Session = Depends(get_db), seller: Seller = Depends(get_demo_seller)):
    order, rows = workspace.get_order(db, seller.id, order_id)
    return OrderDetail(**OrderOut.model_validate(order).model_dump(),
                       items=[OrderItemOut(product_name=product.name, product_code=product.code, color=variant.color,
                                           size=variant.size, quantity=item.quantity, unit_price=item.unit_price)
                              for item, variant, product in rows])
