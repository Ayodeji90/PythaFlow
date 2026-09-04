"""Stopgap auth for the staff console.

Why this exists: real staff auth (SSO / per-user roles, audits, revocation) is
**Day 24**. Until then, a token-secret gates console routes so nothing leaks
publicly. Tokens are stored on `Tenant.config["staff_tokens"]` (list[str]).
A dev fallback accepts the literal `dev-token` for dev environments only.

**Replace this with the real auth on Day 24** — the dep signature is the
public surface; router code shouldn't need to change.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .config import get_settings
from .deps import get_db

if TYPE_CHECKING:
    from .models import Tenant


async def require_console_token(
    x_staff_token: str | None = Header(default=None, alias="X-Staff-Token"),
) -> str:
    """Authenticate at the console boundary. Dev-only ``dev-token`` accepted
    when ENV is dev/local/test. In production the call must carry a non-empty
    token; per-tenant binding happens in `require_tenant_via_token_or_slug`."""
    s = get_settings()
    if not x_staff_token:
        raise HTTPException(status_code=401, detail="Missing X-Staff-Token header")
    if (
        s.ENV.lower() in {"dev", "development", "local", "test"}
        and x_staff_token == s.CONSOLE_SUPER_TOKEN
    ):
        return x_staff_token
    return x_staff_token


async def require_tenant_via_token_or_slug(
    tenant_slug: str | None = None,
    token: str = Depends(require_console_token),
    db: AsyncSession = Depends(get_db),
):
    """Resolve the Tenant the caller is operating *on*, separate from auth.

    Two routes to a tenant:
      • Fastest: query `GET /api/conversations?tenant=<slug>` and pass ``tenant_slug``.
        The token is then verified against `Tenant.config["staff_tokens"]`.
      • No slug: the token must equal ``CONSOLE_SUPER_TOKEN`` (dev), or be
        present in *exactly one* tenant's staff_tokens list — that tenant wins.

    Raises 403 when the token doesn't grant access to the requested slug, and
    404 when the slug is unknown. Cross-tenant access always fails closed.
    """
    from .models import Tenant  # local import to avoid circular

    s = get_settings()

    if tenant_slug:
        tenant = (
            await db.execute(select(Tenant).where(Tenant.slug == tenant_slug))
        ).scalar_one_or_none()
        if tenant is None:
            raise HTTPException(status_code=404, detail="unknown tenant")
        if not _token_authorises(token, tenant, s):
            raise HTTPException(status_code=403, detail="token not authorised for tenant")
        return tenant

    # No slug provided: dev super-token resolves the unique tenant (or first).
    if s.ENV.lower() in {"dev", "development", "local", "test"} and token == s.CONSOLE_SUPER_TOKEN:
        tenants = (await db.execute(select(Tenant))).scalars().all()
        if not tenants:
            raise HTTPException(status_code=404, detail="no tenants configured")
        if len(tenants) > 1:
            raise HTTPException(
                status_code=400,
                detail="tenant_slug is required when more than one tenant exists",
            )
        return tenants[0]

    # Real path: the token must match exactly one tenant's staff_tokens list.
    tenants = (await db.execute(select(Tenant))).scalars().all()
    matches = [t for t in tenants if token in (t.config or {}).get("staff_tokens", [])]
    if not matches:
        raise HTTPException(status_code=403, detail="token not authorised")
    if len(matches) > 1:
        raise HTTPException(
            status_code=409,
            detail="token is registered against multiple tenants — pass ?tenant=",
        )
    return matches[0]


def _token_authorises(token: str, tenant: Tenant, settings) -> bool:
    """True if `token` may operate on `tenant`."""
    if (
        settings.ENV.lower() in {"dev", "development", "local", "test"}
        and token == settings.CONSOLE_SUPER_TOKEN
    ):
        return True
    cfg = (tenant.config or {}) if isinstance(tenant.config, dict) else {}
    tokens = cfg.get("staff_tokens", [])
    return isinstance(tokens, list) and token in tokens
