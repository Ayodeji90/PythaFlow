from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Event, Order, Reservation
from ..schemas import ReservationIn

router = APIRouter(prefix="/api", tags=["misc"])


def demo_today(db: Session) -> str:
    """The demo's 'today' is the last day with order data, so charts are never empty."""
    return db.query(func.max(Order.service_date)).scalar()


@router.get("/events")
def list_events(db: Session = Depends(get_db)):
    today = demo_today(db)
    events = (db.query(Event).filter(Event.date >= today)
              .order_by(Event.date).limit(40).all())
    return [{"id": e.id, "date": e.date, "name": e.name, "type": e.type,
             "impact": e.impact} for e in events]


@router.get("/reservations")
def list_reservations(date: str | None = None, db: Session = Depends(get_db)):
    q = db.query(Reservation)
    q = q.filter(Reservation.date == date) if date else q.filter(Reservation.date >= demo_today(db))
    return [{
        "id": r.id, "guest_id": r.guest_id, "guest_name": r.guest_name,
        "date": r.date, "time": r.time, "party_size": r.party_size,
        "status": r.status, "source": r.source,
    } for r in q.order_by(Reservation.date, Reservation.time).limit(100).all()]


@router.post("/reservations", status_code=201)
def create_reservation(payload: ReservationIn, db: Session = Depends(get_db)):
    res = Reservation(
        id=(db.query(func.max(Reservation.id)).scalar() or 0) + 1,
        guest_id=payload.guest_id, guest_name=payload.guest_name,
        date=payload.date, time=payload.time, party_size=payload.party_size,
        status="confirmed", source=payload.source,
    )
    db.add(res)
    db.commit()
    return {"id": res.id, "guest_name": res.guest_name, "date": res.date,
            "time": res.time, "party_size": res.party_size, "status": res.status}
