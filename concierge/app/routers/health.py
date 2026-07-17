"""Liveness/readiness endpoint. Actually checks the datastores rather than
returning a bare 200, and returns 503 when degraded so HTTP-based load balancers
and orchestrators stop routing traffic to an instance that can't serve."""
from fastapi import APIRouter, Response, status

from ..config import get_settings
from ..db import ping_db
from ..services.redis import ping_redis

router = APIRouter()


@router.get("/health")
async def health(response: Response) -> dict:
    db_ok = await ping_db()
    redis_ok = await ping_redis()
    healthy = db_ok and redis_ok
    if not healthy:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return {
        "status": "ok" if healthy else "degraded",
        "db": db_ok,
        "redis": redis_ok,
        "version": get_settings().APP_VERSION,
    }
