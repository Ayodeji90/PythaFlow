from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Guest, MenuItem, Order, OrderItem

router = APIRouter(prefix="/api/guests", tags=["guests"])


@router.get("")
def list_guests(search: str | None = None, tier: str | None = None,
                limit: int = 50, db: Session = Depends(get_db)):
    q = db.query(Guest)
    if search:
        q = q.filter(Guest.name.ilike(f"%{search}%"))
    if tier:
        q = q.filter(Guest.tier == tier)
    guests = q.order_by(Guest.id).limit(min(limit, 500)).all()
    return [{
        "id": g.id, "name": g.name, "email": g.email, "tier": g.tier,
        "country": g.country, "hotel_guest": bool(g.hotel_guest), "dietary": g.dietary,
    } for g in guests]


@router.get("/{guest_id}")
def get_guest(guest_id: int, db: Session = Depends(get_db)):
    g = db.get(Guest, guest_id)
    if not g:
        raise HTTPException(404, "Guest not found")
    visits, spend = (db.query(func.count(Order.id), func.coalesce(func.sum(Order.total), 0))
                     .filter(Order.guest_id == guest_id).first())
    favorites = (db.query(MenuItem.name, func.sum(OrderItem.qty).label("n"))
                 .join(OrderItem, OrderItem.item_id == MenuItem.id)
                 .join(Order, Order.id == OrderItem.order_id)
                 .filter(Order.guest_id == guest_id)
                 .group_by(MenuItem.name).order_by(func.sum(OrderItem.qty).desc())
                 .limit(5).all())
    return {
        "id": g.id, "name": g.name, "email": g.email, "tier": g.tier,
        "country": g.country, "hotel_guest": bool(g.hotel_guest), "dietary": g.dietary,
        "visits": visits, "lifetime_spend": round(spend, 2),
        "favorites": [{"name": name, "times_ordered": int(n)} for name, n in favorites],
    }
