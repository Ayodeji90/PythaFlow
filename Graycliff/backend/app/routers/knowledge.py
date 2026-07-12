from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import KnowledgeEntry
from ..schemas import KnowledgeIn, KnowledgePatch
from ..services import knowledge as knowledge_svc

router = APIRouter(prefix="/api/knowledge", tags=["knowledge"])

CATEGORY_ORDER = ["property", "hours", "dining", "services", "policies", "faq"]


def _entry_dict(e: KnowledgeEntry) -> dict:
    return {
        "id": e.id, "restaurant_id": e.restaurant_id, "category": e.category,
        "topic": e.topic, "question": e.question, "content": e.content,
        "keywords": e.keywords, "priority": e.priority,
        "verified": bool(e.verified), "active": bool(e.active),
        "updated_at": e.updated_at.isoformat(sep=" ", timespec="minutes"),
    }


@router.get("")
def list_entries(category: str | None = None, db: Session = Depends(get_db)):
    q = db.query(KnowledgeEntry).filter(KnowledgeEntry.active == 1)
    if category:
        q = q.filter(KnowledgeEntry.category == category)
    rows = q.all()
    rows.sort(key=lambda e: (CATEGORY_ORDER.index(e.category)
                             if e.category in CATEGORY_ORDER else 99, -e.priority))
    unverified = sum(1 for e in rows if not e.verified)
    return {"entries": [_entry_dict(e) for e in rows],
            "total": len(rows), "needs_confirmation": unverified}


@router.get("/search")
def search_entries(q: str, db: Session = Depends(get_db)):
    hits = knowledge_svc.search(db, q)
    return [{"score": round(score, 2), **_entry_dict(e)} for score, e in hits]


@router.post("", status_code=201)
def create_entry(payload: KnowledgeIn, db: Session = Depends(get_db)):
    e = KnowledgeEntry(
        category=payload.category, topic=payload.topic, question=payload.question,
        content=payload.content, keywords=payload.keywords,
        priority=payload.priority, verified=1 if payload.verified else 0,
    )
    db.add(e)
    db.commit()
    return _entry_dict(e)


@router.patch("/{entry_id}")
def update_entry(entry_id: int, patch: KnowledgePatch, db: Session = Depends(get_db)):
    e = db.get(KnowledgeEntry, entry_id)
    if not e or not e.active:
        raise HTTPException(404, "Knowledge entry not found")
    if patch.question is not None:
        e.question = patch.question
    if patch.content is not None:
        e.content = patch.content
    if patch.keywords is not None:
        e.keywords = patch.keywords
    if patch.priority is not None:
        e.priority = patch.priority
    if patch.verified is not None:
        e.verified = 1 if patch.verified else 0
    if patch.active is not None:
        e.active = 1 if patch.active else 0
    db.commit()
    return _entry_dict(e)


@router.delete("/{entry_id}", status_code=204)
def delete_entry(entry_id: int, db: Session = Depends(get_db)):
    e = db.get(KnowledgeEntry, entry_id)
    if not e:
        raise HTTPException(404, "Knowledge entry not found")
    e.active = 0  # soft delete — recoverable, and history stays audit-able
    db.commit()
