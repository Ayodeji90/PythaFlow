"""Slack notification subscriber (Day 19).

Escalations reach the channel staff actually watch. The webhook is chosen per
tenant via ``Tenant.config["notify"]["slack"]`` (falling back to the
``NOTIFY_SLACK_WEBHOOK`` env default); unconfigured tenants are silently
skipped — that's the seam's contract, not a failure.

The ``post`` callable is injectable so tests verify the payload without
touching the network (``post(url, text)``).
"""
from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable

from ..config import get_settings
from ..db import SessionLocal
from ..models import Tenant
from ..notifications import NOTIF_ESCALATED

log = logging.getLogger("concierge.notifications.slack")


async def _httpx_post(url: str, text: str) -> None:
    import httpx

    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.post(url, json={"text": text})
        response.raise_for_status()


class SlackSubscriber:
    """Sends escalation alerts to the tenant's Slack webhook (if configured)."""

    def __init__(self, post: Callable[..., Awaitable[None]] | None = None) -> None:
        self._post = post or _httpx_post

    async def handle_event(
        self,
        event: str,
        *,
        tenant_id,
        request_id=None,
        payload: dict,
    ) -> None:
        if event != NOTIF_ESCALATED:
            return
        url = await self._webhook_url(tenant_id)
        if not url:
            return  # not configured for this tenant — quiet by design

        summary = payload.get("summary") or "a request needs a human"
        reasons = ", ".join(payload.get("reason") or []) or "unspecified"
        text = (
            f"🚨 *Escalation* — {summary}\n"
            f"Reasons: {reasons}\n"
            f"Conversation: {payload.get('conversation_id')}"
        )
        try:
            await self._post(url, text)
            log.info("slack escalation alert sent for tenant %s", tenant_id)
        except Exception:  # noqa: BLE001 — a dead webhook must not break the caller
            log.exception("slack alert failed for tenant %s", tenant_id)

    @staticmethod
    async def _webhook_url(tenant_id) -> str:
        async with SessionLocal() as db:
            tenant = await db.get(Tenant, tenant_id)
        if tenant is None:
            return ""
        cfg = (tenant.config or {}).get("notify", {}) or {}
        return str(cfg.get("slack") or get_settings().NOTIFY_SLACK_WEBHOOK or "")
