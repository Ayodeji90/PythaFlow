from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import MenuItem, PriceSuggestion
from ..schemas import SuggestionDecision
from ..services import forecast as forecast_svc
from ..services import pricing as pricing_svc

router = APIRouter(prefix="/api", tags=["forecast-pricing"])


@router.get("/forecast")
def get_forecast(item_id: int | None = None, db: Session = Depends(get_db)):
    if item_id is not None:
        if not db.get(MenuItem, item_id):
            raise HTTPException(404, "Menu item not found")
        return forecast_svc.item_demand(db, item_id)
    return forecast_svc.covers_forecast(db)


def _suggestion_dict(s: PriceSuggestion) -> dict:
    change = (s.suggested_price - s.current_price) / s.current_price * 100
    return {
        "id": s.id, "item_id": s.item_id, "item_name": s.item.name,
        "category": s.item.category, "current_price": s.current_price,
        "suggested_price": s.suggested_price, "change_pct": round(change, 1),
        "rationale": s.rationale, "status": s.status,
    }


@router.get("/pricing/suggestions")
def list_suggestions(db: Session = Depends(get_db)):
    # Generate one batch per demo session; decisions persist on the same batch.
    existing = db.query(PriceSuggestion).order_by(PriceSuggestion.id).all()
    if not existing:
        batch = pricing_svc.generate_suggestions(db)
        db.add_all(batch)
        db.commit()
        existing = db.query(PriceSuggestion).order_by(PriceSuggestion.id).all()
    return [_suggestion_dict(s) for s in existing]


@router.post("/pricing/suggestions/{suggestion_id}")
def decide_suggestion(suggestion_id: int, decision: SuggestionDecision,
                      db: Session = Depends(get_db)):
    s = db.get(PriceSuggestion, suggestion_id)
    if not s:
        raise HTTPException(404, "Suggestion not found")
    if s.status != "pending":
        raise HTTPException(409, f"Suggestion already {s.status}")
    s.status = decision.status
    if decision.status == "accepted":
        item = db.get(MenuItem, s.item_id)
        item.price = s.suggested_price
    db.commit()
    return _suggestion_dict(s)


@router.get("/pricing/waste-risk")
def get_waste_risk(db: Session = Depends(get_db)):
    return pricing_svc.waste_risk(db)
