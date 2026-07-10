"""Hybrid recommender: co-occurrence collaborative filtering + content
similarity + guest history, with dietary filtering and VIP treatment.

Two modes:
  guest mode — "For you" picks when a returning guest opens the menu
  cart mode  — upsell suggestions for what's in the cart right now
"""

from collections import defaultdict
from itertools import combinations

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..models import Guest, MenuItem, Order, OrderItem

# Tag exclusions per dietary preference (kept deliberately conservative).
DIETARY_EXCLUDE = {
    "vegetarian": {"beef", "lamb", "duck", "wagyu", "steak", "lobster", "crab",
                   "conch", "tuna", "grouper", "mahi", "seafood", "shrimp",
                   "escargot", "foie-gras"},
    "pescatarian": {"beef", "lamb", "duck", "wagyu", "steak", "escargot", "foie-gras"},
    "shellfish-allergy": {"lobster", "crab", "conch", "shrimp"},
    "gluten-free": {"pasta", "pastry", "fried", "souffle"},
}

_cache: dict = {}


def _tag_set(item: MenuItem) -> set[str]:
    return {t.strip() for t in item.tags.split(",") if t.strip()}


def _co_occurrence(db: Session) -> dict[int, dict[int, int]]:
    """item_id -> {other_item_id: times ordered together} over recent history."""
    if "cooc" in _cache:
        return _cache["cooc"]
    cutoff = (db.query(func.max(Order.service_date)).scalar() or "")[:4]
    rows = (db.query(OrderItem.order_id, OrderItem.item_id)
            .join(Order, Order.id == OrderItem.order_id)
            .filter(Order.service_date >= f"{int(cutoff) - 1}-01-01")
            .all())
    by_order: dict[int, set[int]] = defaultdict(set)
    for order_id, item_id in rows:
        by_order[order_id].add(item_id)
    cooc: dict[int, dict[int, int]] = defaultdict(lambda: defaultdict(int))
    for items in by_order.values():
        for a, b in combinations(sorted(items), 2):
            cooc[a][b] += 1
            cooc[b][a] += 1
    _cache["cooc"] = {k: dict(v) for k, v in cooc.items()}
    return _cache["cooc"]


def _popularity(db: Session) -> dict[int, float]:
    if "pop" in _cache:
        return _cache["pop"]
    rows = (db.query(OrderItem.item_id, func.sum(OrderItem.qty))
            .group_by(OrderItem.item_id).all())
    total = sum(v for _, v in rows) or 1
    _cache["pop"] = {item_id: float(v) / total for item_id, v in rows}
    return _cache["pop"]


def _guest_history(db: Session, guest_id: int) -> dict[int, int]:
    rows = (db.query(OrderItem.item_id, func.sum(OrderItem.qty))
            .join(Order, Order.id == OrderItem.order_id)
            .filter(Order.guest_id == guest_id)
            .group_by(OrderItem.item_id).all())
    return {item_id: int(v) for item_id, v in rows}


def _allowed(item: MenuItem, dietary: str) -> bool:
    excluded = DIETARY_EXCLUDE.get(dietary, set())
    return not (_tag_set(item) & excluded)


def _item_payload(item: MenuItem) -> dict:
    return {
        "id": item.id, "name": item.name, "category": item.category,
        "price": item.price, "description": item.description,
        "pairing_item_id": item.pairing_item_id,
    }


def recommend_for_guest(db: Session, guest_id: int, limit: int = 6) -> dict:
    guest = db.get(Guest, guest_id)
    if not guest:
        return {"mode": "guest", "guest": None, "recommendations": []}

    history = _guest_history(db, guest_id)
    cooc = _co_occurrence(db)
    pop = _popularity(db)
    items = {m.id: m for m in db.query(MenuItem).filter(MenuItem.active == 1).all()}
    fav_tags: set[str] = set()
    for item_id in sorted(history, key=history.get, reverse=True)[:5]:
        if item_id in items:
            fav_tags |= _tag_set(items[item_id])

    scored = []
    for item_id, item in items.items():
        if item.category == "Beverage":
            continue
        if not _allowed(item, guest.dietary):
            continue

        cf = sum(cnt for other, cnt in cooc.get(item_id, {}).items() if other in history)
        cf_norm = min(cf / 50.0, 1.0)
        content = len(_tag_set(item) & fav_tags) / max(len(_tag_set(item)), 1)
        popularity = min(pop.get(item_id, 0) * 25, 1.0)
        novelty = 0.15 if item_id not in history else 0.0
        score = 0.45 * cf_norm + 0.30 * content + 0.10 * popularity + novelty

        if guest.tier == "VIP" and (item.price >= 60 or "signature" in _tag_set(item)):
            score *= 1.25
        if score <= 0.05:
            continue

        if item_id in history:
            reason = f"You've enjoyed this {history[item_id]}× before"
        elif cf_norm >= content and cf > 0:
            reason = "Guests with your taste order this together"
        elif content > 0:
            reason = "Close to your favourites"
        else:
            reason = "House favourite"
        if guest.tier == "VIP" and item.price >= 100:
            reason = "Reserved suggestion for our VIP guests"
        scored.append((score, item, reason))

    scored.sort(key=lambda x: -x[0])
    return {
        "mode": "guest",
        "guest": {"id": guest.id, "name": guest.name, "tier": guest.tier,
                  "dietary": guest.dietary},
        "recommendations": [
            {"item": _item_payload(item), "reason": reason, "score": round(s, 3)}
            for s, item, reason in scored[:limit]
        ],
    }


def upsell_for_cart(db: Session, cart_ids: list[int], guest_id: int | None,
                    limit: int = 3) -> dict:
    items = {m.id: m for m in db.query(MenuItem).filter(MenuItem.active == 1).all()}
    cart = [items[i] for i in cart_ids if i in items]
    if not cart:
        return {"mode": "cart", "recommendations": []}

    guest = db.get(Guest, guest_id) if guest_id else None
    dietary = guest.dietary if guest else "none"
    cooc = _co_occurrence(db)
    cart_set = set(cart_ids)
    cart_categories = {c.category for c in cart}

    scored: dict[int, tuple[float, str]] = {}

    def consider(item_id: int, score: float, reason: str):
        if item_id in cart_set or item_id not in items:
            return
        if not _allowed(items[item_id], dietary):
            return
        if item_id not in scored or scored[item_id][0] < score:
            scored[item_id] = (score, reason)

    for c in cart:
        # Sommelier pairing beats everything for mains without a drink.
        if c.pairing_item_id and "Wine" not in cart_categories:
            consider(c.pairing_item_id, 100.0, f"Sommelier's pairing for the {c.name}")
        for other_id, cnt in sorted(cooc.get(c.id, {}).items(), key=lambda kv: -kv[1])[:8]:
            other = items.get(other_id)
            if not other:
                continue
            # Steer upsell toward attach categories, not another main.
            weight = {"Dessert": 1.3, "Wine": 1.2, "Starter": 1.0,
                      "Beverage": 0.9, "Cigar": 0.8}.get(other.category, 0.3)
            consider(other_id, cnt * weight / 100.0,
                     f"Guests who order the {c.name} often add this")

    if "Dessert" not in cart_categories:
        souffle = next((m for m in items.values() if "signature" in _tag_set(m)
                        and m.category == "Dessert"), None)
        if souffle:
            consider(souffle.id, 0.5, "The table favourite to finish")

    ranked = sorted(scored.items(), key=lambda kv: -kv[1][0])[:limit]
    return {
        "mode": "cart",
        "recommendations": [
            {"item": _item_payload(items[item_id]), "reason": reason, "score": round(score, 3)}
            for item_id, (score, reason) in ranked
        ],
    }
