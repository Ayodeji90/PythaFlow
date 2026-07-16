"""Liveness/readiness endpoint. Actually checks the datastores rather than
returning a bare 200, so `/health` reflects real reachability."""
from fastapi import APIRouter

from ..config import get_settings
from ..db import ping_db
from ..services.redis import ping_redis

router = APIRouter()


@router.get("/health")
async def health() -> dict:
    db_ok = await ping_db()
    redis_ok = await ping_redis()
    return {
        "status": "ok" if (db_ok and redis_ok) else "degraded",
        "db": db_ok,
        "redis": redis_ok,
        "version": get_settings().APP_VERSION,
    }
