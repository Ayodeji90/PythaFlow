from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Guest, MenuItem, Order, Reservation
from ..schemas import OrderIn, OrderItemIn, VoiceUtterance
from ..services import llm
from .orders import create_order

router = APIRouter(prefix="/api/voice", tags=["voice"])


@router.post("/interpret")
def interpret(payload: VoiceUtterance, db: Session = Depends(get_db)):
    menu = db.query(MenuItem).filter(MenuItem.active == 1).all()
    names = [m.name for m in menu]
    by_name = {m.name.lower(): m for m in menu}
    today = db.query(func.max(Order.service_date)).scalar()

    result = llm.interpret_voice(payload.transcript, names, today)
    action: dict = {"type": "none"}

    if result["intent"] == "order" and result.get("items"):
        lines = []
        for entry in result["items"]:
            item = by_name.get(entry["name"].lower())
            if item:
                lines.append(OrderItemIn(item_id=item.id, qty=max(1, int(entry.get("qty", 1)))))
        if lines:
            order = create_order(OrderIn(
                items=lines, guest_id=payload.guest_id,
                table_no=0, covers=max(1, len(lines)), channel="voice",
            ), db)
            action = {"type": "order", "order": order}

    elif result["intent"] == "reservation":
        guest = db.get(Guest, payload.guest_id) if payload.guest_id else None
        name = result.get("guest_name") or (guest.name if guest else "Voice Guest")
        res = Reservation(
            id=(db.query(func.max(Reservation.id)).scalar() or 0) + 1,
            guest_id=payload.guest_id, guest_name=name,
            date=result.get("date") or today,
            time=result.get("time") or "19:00",
            party_size=result.get("party_size") or 2,
            status="confirmed", source="voice",
        )
        db.add(res)
        db.commit()
        action = {"type": "reservation", "reservation": {
            "id": res.id, "guest_name": res.guest_name, "date": res.date,
            "time": res.time, "party_size": res.party_size,
        }}

    return {
        "transcript": payload.transcript,
        "intent": result["intent"],
        "reply": result["reply"],
        "engine": result.get("engine", "rules"),
        "action": action,
    }
