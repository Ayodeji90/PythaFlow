"""Staff auth stopgap (Day 17) + the console page itself.

**Security posture — read this loudly:** real staff auth (SSO/RBAC) is **Day
24**. Until then every console endpoint is gated by a **shared secret**
(`X-Staff-Token` header, or `?token=` for browser contexts that cannot set
headers — EventSource, the page load). There is no per-user identity: \"who
approved this\" is only as trustworthy as token hygiene. Keep the token
server-side, rotate on demand, and **never expose the console to the open
internet before Day 24**.

- Header dependency: `require_staff_token` — for fetch()/curl clients.
- Query-param dependency: `require_staff_token_param` — for EventSource and
  the `GET /console` page (browsers can't set headers on those).
- `GET /console` serves the single-file front end (``console/index.html``).

The dev/test convention (matching the Week-2 approvals endpoints): any
non-empty token passes; production compares against ``settings.STAFF_TOKEN``.
"""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from fastapi.responses import FileResponse

from ..config import get_settings

router = APIRouter()

_CONSOLE_PAGE = Path(__file__).resolve().parents[2] / "console" / "index.html"


def _token_ok(token: str | None) -> bool:
    """Dev/test: any non-empty token. Production: must match STAFF_TOKEN."""
    settings = get_settings()
    if settings.ENV.lower() in {"dev", "development", "local", "test"}:
        return bool(token and token.strip())
    return bool(token and token.strip() == settings.STAFF_TOKEN)


def require_staff_token(
    x_staff_token: str | None = Header(None),
) -> str:
    """Header-based dependency (fetch / curl). Raises 401 when missing/invalid."""
    if not _token_ok(x_staff_token):
        raise HTTPException(status_code=401, detail="Missing or invalid staff token")
    return x_staff_token


def require_staff_token_param(
    token: str | None = Query(None),
) -> str:
    """Query-param dependency (EventSource, page load). Raises 401 when bad."""
    if not _token_ok(token):
        raise HTTPException(status_code=401, detail="Missing or invalid staff token")
    return token


@router.get("/console", include_in_schema=False)
async def console_page(_: str = Depends(require_staff_token_param)) -> FileResponse:
    """The staff console — behind the token (stopgap until Day 24 real auth)."""
    return FileResponse(_CONSOLE_PAGE, media_type="text/html")
