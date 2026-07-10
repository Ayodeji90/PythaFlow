"""Demand forecasting — honest seasonal baseline, no black box.

forecast(day) = trailing-28-day level × day-of-week factor × event uplift

The day-of-week profile is computed over the last 56 days. Event uplift
comes from the events calendar (high 1.35×, medium 1.12×). This is the
pilot baseline the design doc calls for; a gradient-boosted model can
replace it once Graycliff's real POS history is connected.
"""

from datetime import date, timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..models import Event, MenuItem, Order, OrderItem

HISTORY_WINDOW = 56
LEVEL_WINDOW = 28
HORIZON = 14

_EVENT_UPLIFT = {"high": 1.35, "medium": 1.12, "low": 1.0}


def as_of_date(db: Session) -> date:
    return date.fromisoformat(db.query(func.max(Order.service_date)).scalar())


def _event_factor(db: Session, start: date, days: int) -> dict[str, tuple[float, str | None]]:
    """date-iso -> (uplift, event name) for the horizon."""
    end = start + timedelta(days=days)
    rows = (db.query(Event)
            .filter(Event.date > start.isoformat(), Event.date <= end.isoformat()).all())
    out: dict[str, tuple[float, str | None]] = {}
    for e in rows:
        uplift = _EVENT_UPLIFT.get(e.impact, 1.0)
        prev = out.get(e.date, (1.0, None))
        if uplift > prev[0]:
            out[e.date] = (uplift, e.name)
    return out


def _dow_profile(daily: dict[str, float], anchor: date) -> list[float]:
    """Normalized day-of-week factors from the trailing window."""
    sums = [0.0] * 7
    counts = [0] * 7
    for offset in range(HISTORY_WINDOW):
        d = anchor - timedelta(days=offset)
        v = daily.get(d.isoformat(), 0.0)
        sums[d.weekday()] += v
        counts[d.weekday()] += 1
    means = [s / c if c else 0.0 for s, c in zip(sums, counts)]
    overall = sum(means) / 7 if any(means) else 1.0
    return [m / overall if overall else 1.0 for m in means]


def _level(daily: dict[str, float], anchor: date) -> float:
    vals = [daily.get((anchor - timedelta(days=o)).isoformat(), 0.0)
            for o in range(LEVEL_WINDOW)]
    return sum(vals) / len(vals)


def covers_forecast(db: Session) -> dict:
    """Restaurant-level covers: 28d history + 14d forecast."""
    anchor = as_of_date(db)
    start = (anchor - timedelta(days=HISTORY_WINDOW)).isoformat()
    rows = (db.query(Order.service_date, func.sum(Order.covers))
            .filter(Order.service_date >= start)
            .group_by(Order.service_date).all())
    daily = {d: float(v) for d, v in rows}

    dow = _dow_profile(daily, anchor)
    level = _level(daily, anchor)
    events = _event_factor(db, anchor, HORIZON)

    history = [
        {"date": d, "covers": int(daily.get(d, 0))}
        for d in ((anchor - timedelta(days=o)).isoformat() for o in range(LEVEL_WINDOW - 1, -1, -1))
    ]
    forecast = []
    for offset in range(1, HORIZON + 1):
        d = anchor + timedelta(days=offset)
        uplift, event_name = events.get(d.isoformat(), (1.0, None))
        forecast.append({
            "date": d.isoformat(),
            "covers": round(level * dow[d.weekday()] * uplift),
            "event": event_name,
        })
    return {"as_of": anchor.isoformat(), "history": history, "forecast": forecast}


def item_demand(db: Session, item_id: int) -> dict:
    """Per-item demand profile used by pricing and the item forecast endpoint."""
    anchor = as_of_date(db)
    start = (anchor - timedelta(days=HISTORY_WINDOW)).isoformat()
    rows = (db.query(Order.service_date, func.sum(OrderItem.qty))
            .join(Order, Order.id == OrderItem.order_id)
            .filter(OrderItem.item_id == item_id, Order.service_date >= start)
            .group_by(Order.service_date).all())
    daily = {d: float(v) for d, v in rows}

    dow = _dow_profile(daily, anchor)
    level = _level(daily, anchor)
    item = db.get(MenuItem, item_id)
    event_sensitive = item.category in ("Main", "Tasting", "Wine")
    events = _event_factor(db, anchor, 7) if event_sensitive else {}

    next7 = 0.0
    for offset in range(1, 8):
        d = anchor + timedelta(days=offset)
        uplift = events.get(d.isoformat(), (1.0, None))[0]
        next7 += level * dow[d.weekday()] * uplift
    return {
        "item_id": item_id,
        "daily_level": round(level, 2),
        "forecast_7d": round(next7, 1),
        "baseline_7d": round(level * 7, 1),
        "demand_ratio": round(next7 / (level * 7), 3) if level > 0 else 1.0,
    }
