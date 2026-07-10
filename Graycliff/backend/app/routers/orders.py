from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from ..database import get_db
from ..models import Inventory, MenuItem, Order, OrderItem
from ..schemas import OrderIn

router = APIRouter(prefix="/api/orders", tags=["orders"])


def order_dict(o: Order, with_items: bool = False) -> dict:
    d = {
        "id": o.id, "placed_at": o.placed_at.isoformat(sep=" "),
        "service_date": o.service_date, "guest_id": o.guest_id,
        "covers": o.covers, "table_no": o.table_no, "channel": o.channel,
        "total": o.total,
    }
    if with_items:
        d["items"] = [{
            "item_id": li.item_id, "name": li.item.name, "qty": li.qty,
            "unit_price": li.unit_price,
        } for li in o.items]
    return d


@router.get("")
def list_orders(date: str | None = None, limit: int = 25, db: Session = Depends(get_db)):
    q = db.query(Order)
    if date:
        q = q.filter(Order.service_date == date)
    orders = q.order_by(Order.placed_at.desc()).limit(min(limit, 200)).all()
    return [order_dict(o) for o in orders]


@router.get("/{order_id}")
def get_order(order_id: int, db: Session = Depends(get_db)):
    o = (db.query(Order).options(joinedload(Order.items).joinedload(OrderItem.item))
         .filter(Order.id == order_id).first())
    if not o:
        raise HTTPException(404, "Order not found")
    return order_dict(o, with_items=True)


@router.post("", status_code=201)
def create_order(payload: OrderIn, db: Session = Depends(get_db)):
    if not payload.items:
        raise HTTPException(422, "Order must contain at least one item")
    now = datetime.now()
    order = Order(
        id=(db.query(func.max(Order.id)).scalar() or 0) + 1,
        placed_at=now, service_date=now.date().isoformat(),
        guest_id=payload.guest_id, covers=payload.covers,
        table_no=payload.table_no, channel=payload.channel, total=0.0,
    )
    db.add(order)
    total = 0.0
    next_item_id = (db.query(func.max(OrderItem.id)).scalar() or 0) + 1
    for line in payload.items:
        item = db.get(MenuItem, line.item_id)
        if not item or not item.active:
            raise HTTPException(422, f"Unknown menu item {line.item_id}")
        db.add(OrderItem(id=next_item_id, order_id=order.id, item_id=item.id,
                         qty=line.qty, unit_price=item.price))
        next_item_id += 1
        total += item.price * line.qty
        inv = db.get(Inventory, item.id)
        if inv:
            inv.stock = max(0, inv.stock - line.qty)
    order.total = round(total, 2)
    db.commit()
    return get_order(order.id, db)
