from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..database import get_db
from ..services import recommender

router = APIRouter(prefix="/api/recommendations", tags=["recommendations"])


@router.get("")
def recommendations(guest_id: int | None = None,
                    cart: str = Query(default=""),
                    db: Session = Depends(get_db)):
    cart_ids = [int(x) for x in cart.split(",") if x.strip().isdigit()]
    if cart_ids:
        return recommender.upsell_for_cart(db, cart_ids, guest_id)
    if guest_id is not None:
        return recommender.recommend_for_guest(db, guest_id)
    return {"mode": "guest", "guest": None, "recommendations": []}
