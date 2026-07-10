from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Inventory, MenuItem

router = APIRouter(prefix="/api/menu", tags=["menu"])


def item_dict(m: MenuItem, inv: Inventory | None = None) -> dict:
    return {
        "id": m.id, "name": m.name, "category": m.category,
        "price": m.price, "cost": m.cost, "tags": m.tags.split(","),
        "description": m.description, "pairing_item_id": m.pairing_item_id,
        "active": bool(m.active),
        "stock": inv.stock if inv else None,
        "unit": inv.unit if inv else None,
    }


@router.get("")
def list_menu(category: str | None = None, db: Session = Depends(get_db)):
    q = db.query(MenuItem).filter(MenuItem.active == 1)
    if category:
        q = q.filter(MenuItem.category == category)
    items = q.order_by(MenuItem.category, MenuItem.id).all()
    return [item_dict(m, m.inventory) for m in items]


@router.get("/{item_id}")
def get_item(item_id: int, db: Session = Depends(get_db)):
    m = db.get(MenuItem, item_id)
    if not m:
        raise HTTPException(404, "Menu item not found")
    d = item_dict(m, m.inventory)
    if m.pairing_item_id:
        p = db.get(MenuItem, m.pairing_item_id)
        d["pairing"] = item_dict(p) if p else None
    return d
