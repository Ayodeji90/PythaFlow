from datetime import datetime

from sqlalchemy import Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


class MenuItem(Base):
    __tablename__ = "menu_items"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    category: Mapped[str] = mapped_column(String(30), index=True)
    price: Mapped[float] = mapped_column(Float)
    cost: Mapped[float] = mapped_column(Float)
    tags: Mapped[str] = mapped_column(String(200), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    pairing_item_id: Mapped[int | None] = mapped_column(ForeignKey("menu_items.id"), nullable=True)
    active: Mapped[int] = mapped_column(Integer, default=1)

    inventory: Mapped["Inventory"] = relationship(back_populates="item", uselist=False)


class Guest(Base):
    __tablename__ = "guests"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(80))
    email: Mapped[str] = mapped_column(String(120))
    tier: Mapped[str] = mapped_column(String(20), index=True)
    country: Mapped[str] = mapped_column(String(40))
    hotel_guest: Mapped[int] = mapped_column(Integer, default=0)
    dietary: Mapped[str] = mapped_column(String(30), default="none")


class Order(Base):
    __tablename__ = "orders"
    id: Mapped[int] = mapped_column(primary_key=True)
    placed_at: Mapped[datetime] = mapped_column()
    service_date: Mapped[str] = mapped_column(String(10), index=True)
    guest_id: Mapped[int | None] = mapped_column(ForeignKey("guests.id"), nullable=True)
    covers: Mapped[int] = mapped_column(Integer, default=2)
    table_no: Mapped[int] = mapped_column(Integer, default=1)
    channel: Mapped[str] = mapped_column(String(20), default="dine-in")
    total: Mapped[float] = mapped_column(Float, default=0)

    items: Mapped[list["OrderItem"]] = relationship(back_populates="order")


class OrderItem(Base):
    __tablename__ = "order_items"
    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), index=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("menu_items.id"), index=True)
    qty: Mapped[int] = mapped_column(Integer, default=1)
    unit_price: Mapped[float] = mapped_column(Float)

    order: Mapped["Order"] = relationship(back_populates="items")
    item: Mapped["MenuItem"] = relationship()


class Inventory(Base):
    __tablename__ = "inventory"
    item_id: Mapped[int] = mapped_column(ForeignKey("menu_items.id"), primary_key=True)
    stock: Mapped[int] = mapped_column(Integer)
    par_level: Mapped[int] = mapped_column(Integer)
    unit: Mapped[str] = mapped_column(String(20), default="portions")
    shelf_life_days: Mapped[int] = mapped_column(Integer, default=3)
    last_restock: Mapped[str] = mapped_column(String(10))

    item: Mapped["MenuItem"] = relationship(back_populates="inventory")


class Event(Base):
    __tablename__ = "events"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    date: Mapped[str] = mapped_column(String(10), index=True)
    name: Mapped[str] = mapped_column(String(120))
    type: Mapped[str] = mapped_column(String(30))
    impact: Mapped[str] = mapped_column(String(10))


class Reservation(Base):
    __tablename__ = "reservations"
    id: Mapped[int] = mapped_column(primary_key=True)
    guest_id: Mapped[int | None] = mapped_column(ForeignKey("guests.id"), nullable=True)
    guest_name: Mapped[str] = mapped_column(String(80))
    date: Mapped[str] = mapped_column(String(10), index=True)
    time: Mapped[str] = mapped_column(String(5))
    party_size: Mapped[int] = mapped_column(Integer, default=2)
    status: Mapped[str] = mapped_column(String(20), default="confirmed")
    source: Mapped[str] = mapped_column(String(30), default="web")


class PriceSuggestion(Base):
    __tablename__ = "price_suggestions"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("menu_items.id"))
    current_price: Mapped[float] = mapped_column(Float)
    suggested_price: Mapped[float] = mapped_column(Float)
    rationale: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)

    item: Mapped["MenuItem"] = relationship()


class MarketingDraft(Base):
    __tablename__ = "marketing_drafts"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    channel: Mapped[str] = mapped_column(String(30))
    title: Mapped[str] = mapped_column(String(200), default="")
    body: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="draft", index=True)
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)
