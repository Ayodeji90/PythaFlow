"""Load the synthetic Graycliff CSVs into SQLite on first startup."""

import csv
from datetime import datetime
from pathlib import Path

from sqlalchemy.orm import Session

from . import models

SEED_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "seed"


def _rows(name: str):
    with open(SEED_DIR / name, newline="") as fh:
        yield from csv.DictReader(fh)


def seed_if_empty(db: Session) -> None:
    if db.query(models.MenuItem).first():
        return
    if not (SEED_DIR / "menu.csv").exists():
        raise RuntimeError(
            f"Seed data missing at {SEED_DIR} — run: python data/generate_graycliff_data.py"
        )

    for r in _rows("menu.csv"):
        db.add(models.MenuItem(
            id=int(r["id"]), name=r["name"], category=r["category"],
            price=float(r["price"]), cost=float(r["cost"]), tags=r["tags"],
            description=r["description"],
            pairing_item_id=int(r["pairing_item_id"]) if r["pairing_item_id"] else None,
            active=int(r["active"]),
        ))
    for r in _rows("guests.csv"):
        db.add(models.Guest(
            id=int(r["id"]), name=r["name"], email=r["email"], tier=r["tier"],
            country=r["country"], hotel_guest=int(r["hotel_guest"]), dietary=r["dietary"],
        ))
    db.flush()

    orders = [models.Order(
        id=int(r["id"]),
        placed_at=datetime.fromisoformat(r["placed_at"]),
        service_date=r["service_date"],
        guest_id=int(r["guest_id"]) if r["guest_id"] else None,
        covers=int(r["covers"]), table_no=int(r["table_no"]),
        channel=r["channel"], total=float(r["total"]),
    ) for r in _rows("orders.csv")]
    db.bulk_save_objects(orders)

    items = [models.OrderItem(
        id=int(r["id"]), order_id=int(r["order_id"]), item_id=int(r["item_id"]),
        qty=int(r["qty"]), unit_price=float(r["unit_price"]),
    ) for r in _rows("order_items.csv")]
    db.bulk_save_objects(items)

    for r in _rows("inventory.csv"):
        db.add(models.Inventory(
            item_id=int(r["item_id"]), stock=int(r["stock"]), par_level=int(r["par_level"]),
            unit=r["unit"], shelf_life_days=int(r["shelf_life_days"]),
            last_restock=r["last_restock"],
        ))
    for r in _rows("events.csv"):
        db.add(models.Event(date=r["date"], name=r["name"], type=r["type"], impact=r["impact"]))
    for r in _rows("reservations.csv"):
        db.add(models.Reservation(
            id=int(r["id"]), guest_id=int(r["guest_id"]) if r["guest_id"] else None,
            guest_name=r["guest_name"], date=r["date"], time=r["time"],
            party_size=int(r["party_size"]), status=r["status"], source=r["source"],
        ))
    db.commit()
