from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Event, MarketingDraft, MenuItem, Order, OrderItem
from ..schemas import DraftUpdate, MarketingRequest
from ..services import llm

router = APIRouter(prefix="/api/marketing", tags=["marketing"])

SEASONS = {12: "high", 1: "high", 2: "high", 3: "high", 4: "shoulder", 5: "shoulder",
           6: "summer", 7: "summer", 8: "quiet", 9: "quiet", 10: "shoulder", 11: "festive"}
SEASON_NAMES = {"high": "high season", "shoulder": "spring", "summer": "island summer",
                "quiet": "late summer", "festive": "pre-holiday"}


def _context(db: Session) -> dict:
    today = db.query(func.max(Order.service_date)).scalar()
    week_ago = (date.fromisoformat(today) - timedelta(days=6)).isoformat()
    best = (db.query(MenuItem.name)
            .join(OrderItem, OrderItem.item_id == MenuItem.id)
            .join(Order, Order.id == OrderItem.order_id)
            .filter(Order.service_date >= week_ago,
                    MenuItem.category.in_(["Starter", "Main", "Tasting", "Dessert"]))
            .group_by(MenuItem.id).order_by(func.sum(OrderItem.qty).desc())
            .limit(3).all())
    events = (db.query(Event)
              .filter(Event.date > today, Event.impact.in_(["high", "medium"]))
              .order_by(Event.date).limit(3).all())
    season = SEASON_NAMES[SEASONS[date.fromisoformat(today).month]]
    return {
        "best_sellers": [b[0] for b in best],
        "events": [f"{e.name} ({e.date})" for e in events],
        "season": season,
    }


def _draft_dict(d: MarketingDraft) -> dict:
    return {"id": d.id, "channel": d.channel, "title": d.title, "body": d.body,
            "status": d.status, "created_at": d.created_at.isoformat(sep=" ", timespec="minutes")}


@router.post("/generate", status_code=201)
def generate(req: MarketingRequest, db: Session = Depends(get_db)):
    content = llm.generate_marketing(req.channel, req.topic, req.tone, _context(db))
    draft = MarketingDraft(channel=req.channel, title=content["title"],
                           body=content["body"], status="draft")
    db.add(draft)
    db.commit()
    out = _draft_dict(draft)
    out["engine"] = content.get("engine", "template")
    return out


@router.get("/drafts")
def drafts(db: Session = Depends(get_db)):
    rows = db.query(MarketingDraft).order_by(MarketingDraft.id.desc()).limit(50).all()
    return [_draft_dict(d) for d in rows]


@router.patch("/drafts/{draft_id}")
def update_draft(draft_id: int, patch: DraftUpdate, db: Session = Depends(get_db)):
    d = db.get(MarketingDraft, draft_id)
    if not d:
        raise HTTPException(404, "Draft not found")
    if patch.title is not None:
        d.title = patch.title
    if patch.body is not None:
        d.body = patch.body
    if patch.status is not None:
        d.status = patch.status
    db.commit()
    return _draft_dict(d)
