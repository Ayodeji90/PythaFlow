"""Rule-based dynamic pricing with margin guardrails.

Every suggestion carries a plain-English rationale — the manager stays
in the loop and accepts or rejects each change. Guardrails: price never
drops below 2× cost, and no single change exceeds ±15%.
"""

from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from ..models import Event, Inventory, MenuItem, PriceSuggestion
from . import forecast

MAX_CHANGE = 0.15
MIN_MARGIN_MULTIPLE = 2.0
PERISHABLE_DAYS = 4


def _round_price(value: float) -> float:
    if value >= 100:
        return float(round(value))
    return round(value * 2) / 2  # .00 / .50 steps


def _high_impact_event_soon(db: Session, anchor) -> str | None:
    end = (anchor + timedelta(days=3)).isoformat()
    e = (db.query(Event)
         .filter(Event.date > anchor.isoformat(), Event.date <= end, Event.impact == "high")
         .order_by(Event.date).first())
    return e.name if e else None


def generate_suggestions(db: Session) -> list[PriceSuggestion]:
    anchor = forecast.as_of_date(db)
    event_name = _high_impact_event_soon(db, anchor)
    suggestions: list[PriceSuggestion] = []

    pairs = (db.query(MenuItem, Inventory)
             .join(Inventory, Inventory.item_id == MenuItem.id)
             .filter(MenuItem.active == 1).all())
    for item, inv in pairs:
        demand = forecast.item_demand(db, item.id)
        f7, ratio = demand["forecast_7d"], demand["demand_ratio"]
        daily = max(f7 / 7, 0.01)
        cover_days = inv.stock / daily
        perishable = inv.shelf_life_days <= PERISHABLE_DAYS

        new_price, rationale = None, None

        # 1) Scarcity: strong demand against thin stock — protect the margin.
        if (perishable and cover_days < 5 and ratio >= 1.0
                and item.category in ("Starter", "Main", "Tasting")):
            pct = min(0.04 + 0.04 * max(ratio - 1.0, 0) * 5, 0.12)
            new_price = item.price * (1 + pct)
            rationale = (
                f"Only ~{cover_days:.1f} days of stock ({inv.stock} {inv.unit}) against "
                f"forecast demand of {f7:.0f} portions this week. A modest premium slows "
                f"sell-out and protects margin on a signature dish."
            )

        # 2) Waste risk: perishable overstock with soft demand — move it.
        elif perishable and cover_days > 10 and ratio <= 1.05:
            excess = max(inv.stock - f7, 0)
            new_price = item.price * 0.90
            rationale = (
                f"Overstocked: {inv.stock} {inv.unit} on hand but only {f7:.0f} forecast to "
                f"sell this week (~{excess:.0f} portions at spoilage risk, "
                f"≈${excess * item.cost:.0f} of product). A 10% feature price moves stock "
                f"before it becomes waste."
            )

        # 3) Event uplift on premium categories.
        elif event_name and item.category in ("Wine", "Tasting"):
            new_price = item.price * 1.04
            rationale = (
                f"{event_name} falls within 3 days — premium demand peaks on event nights. "
                f"A 4% adjustment captures willingness to pay without denting volume."
            )

        if new_price is None:
            continue

        # Guardrails
        new_price = max(min(new_price, item.price * (1 + MAX_CHANGE)),
                        item.price * (1 - MAX_CHANGE),
                        item.cost * MIN_MARGIN_MULTIPLE)
        new_price = _round_price(new_price)
        if abs(new_price - item.price) / item.price < 0.02:
            continue

        suggestions.append((
            abs(new_price - item.price) * f7,  # est. weekly $ impact, for ranking
            PriceSuggestion(
                item_id=item.id, current_price=item.price, suggested_price=new_price,
                rationale=rationale, status="pending", created_at=datetime.now(),
            ),
        ))
    # Surface only the most material changes — a short, decisive list sells
    # better than a wall of ±4% tweaks.
    suggestions.sort(key=lambda pair: -pair[0])
    return [s for _, s in suggestions[:12]]


def waste_risk(db: Session) -> dict:
    """Perishable items whose stock exceeds forecast demand — money on the line."""
    items = []
    pairs = (db.query(MenuItem, Inventory)
             .join(Inventory, Inventory.item_id == MenuItem.id)
             .filter(MenuItem.active == 1, Inventory.shelf_life_days <= PERISHABLE_DAYS)
             .all())
    for item, inv in pairs:
        f7 = forecast.item_demand(db, item.id)["forecast_7d"]
        if inv.stock <= f7 * 1.25:
            continue
        excess = inv.stock - f7
        items.append({
            "item_id": item.id, "name": item.name, "category": item.category,
            "stock": inv.stock, "forecast_7d": round(f7, 1),
            "excess_portions": round(excess, 1),
            "at_risk_value": round(excess * item.cost, 2),
            "shelf_life_days": inv.shelf_life_days,
        })
    items.sort(key=lambda x: -x["at_risk_value"])
    return {
        "total_at_risk": round(sum(i["at_risk_value"] for i in items), 2),
        "items": items,
    }
