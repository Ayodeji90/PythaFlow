from datetime import date, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Guest, Inventory, MenuItem, Order, OrderItem, Reservation

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("/summary")
def summary(db: Session = Depends(get_db)):
    today: str = db.query(func.max(Order.service_date)).scalar()
    week_ago = (date.fromisoformat(today) - timedelta(days=6)).isoformat()
    month_ago = (date.fromisoformat(today) - timedelta(days=29)).isoformat()

    def day_stats(day: str):
        revenue, orders, covers = (
            db.query(func.coalesce(func.sum(Order.total), 0),
                     func.count(Order.id),
                     func.coalesce(func.sum(Order.covers), 0))
            .filter(Order.service_date == day).first())
        return {"revenue": round(revenue, 2), "orders": orders, "covers": int(covers)}

    revenue_series = [
        {"date": d, "revenue": round(rev, 2), "covers": int(cov)}
        for d, rev, cov in (
            db.query(Order.service_date, func.sum(Order.total), func.sum(Order.covers))
            .filter(Order.service_date >= month_ago)
            .group_by(Order.service_date).order_by(Order.service_date).all())
    ]

    top_sellers = [
        {"name": name, "category": cat, "qty": int(qty), "revenue": round(rev, 2)}
        for name, cat, qty, rev in (
            db.query(MenuItem.name, MenuItem.category,
                     func.sum(OrderItem.qty), func.sum(OrderItem.qty * OrderItem.unit_price))
            .join(OrderItem, OrderItem.item_id == MenuItem.id)
            .join(Order, Order.id == OrderItem.order_id)
            .filter(Order.service_date >= week_ago)
            .group_by(MenuItem.id).order_by(func.sum(OrderItem.qty).desc())
            .limit(8).all())
    ]

    low_stock = [
        {"item_id": inv.item_id, "name": item.name, "stock": inv.stock,
         "par_level": inv.par_level, "unit": inv.unit}
        for inv, item in (
            db.query(Inventory, MenuItem).join(MenuItem, MenuItem.id == Inventory.item_id)
            .filter(Inventory.stock < Inventory.par_level)
            .order_by((Inventory.stock * 1.0 / Inventory.par_level)).limit(8).all())
    ]

    upcoming_res = (db.query(func.count(Reservation.id))
                    .filter(Reservation.date >= today).scalar())
    vip_count = db.query(func.count(Guest.id)).filter(Guest.tier == "VIP").scalar()

    return {
        "as_of": today,
        "today": day_stats(today),
        "revenue_30d": revenue_series,
        "top_sellers_7d": top_sellers,
        "low_stock": low_stock,
        "upcoming_reservations": upcoming_res,
        "vip_guests": vip_count,
    }
