"""Liveness/readiness endpoint. Actually checks the datastores rather than
returning a bare 200, and returns 503 when degraded so HTTP-based load balancers
and orchestrators stop routing traffic to an instance that can't serve."""
from fastapi import APIRouter, Response, status

from ..config import get_settings
from ..db import ping_db
from ..services.redis import ping_redis

router = APIRouter()


@router.get("/", include_in_schema=False)
async def root() -> dict:
    """A small index so hitting the bare root isn't a confusing 404."""
    s = get_settings()
    endpoints = {
        "health": "/health",
        "chat_rest": "POST /api/chat",
        "chat_ws": "/ws/chat?tenant=<slug>",
        "docs": "/docs",
    }
    if s.ENV.lower() in {"dev", "development", "local", "test"}:
        endpoints["dev_chat"] = "/dev/chat?tenant=demo"
    return {"service": "PythaFlow Concierge", "version": s.APP_VERSION, "endpoints": endpoints}


@router.get("/favicon.ico", include_in_schema=False)
async def favicon() -> Response:
    return Response(status_code=204)  # no icon; avoid noisy 404s in the log


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
