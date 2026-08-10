"""Email notification subscriber (Day 19).

Escalations email the venue's staff. Recipients come from
``Tenant.config["notify"]["email"]`` (a list); unconfigured tenants fall back
to the ``NOTIFY_EMAIL_FROM`` env address, else skip quietly. Sending reuses
the email channel's ``SmtpSender`` seam (or the ``NullSender`` log when no
SMTP host is configured — never silent, never crashing).
"""
from __future__ import annotations

import logging

from ..config import get_settings
from ..db import SessionLocal
from ..models import Tenant
from ..notifications import NOTIF_ESCALATED

log = logging.getLogger("concierge.notifications.email")


class EmailSubscriber:
    """Sends escalation alerts to the tenant's configured inbox(es)."""

    def __init__(self, sender=None) -> None:
        # Inject a fake sender in tests; otherwise built from settings lazily.
        self._sender = sender

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
        recipients, subject, body = await self._compose(tenant_id, payload)
        if not recipients:
            return
        sender = self._sender or self._build_sender()
        try:
            for to in recipients:
                await sender.send_reply(to=to, subject=subject, body=body)
            log.info("escalation email sent to %s", recipients)
        except Exception:  # noqa: BLE001 — SMTP trouble must not break the caller
            log.exception("escalation email failed for tenant %s", tenant_id)

    @staticmethod
    async def _compose(tenant_id, payload: dict) -> tuple[list[str], str, str]:
        async with SessionLocal() as db:
            tenant = await db.get(Tenant, tenant_id)
        if tenant is None:
            return [], "", ""
        cfg = (tenant.config or {}).get("notify", {}) or {}
        recipients = [str(r) for r in cfg.get("email", []) or []]
        if not recipients and get_settings().NOTIFY_EMAIL_FROM:
            recipients = [get_settings().NOTIFY_EMAIL_FROM]
        summary = payload.get("summary") or "needs a human"
        subject = f"[Concierge] Escalation — {summary}"
        body = (
            "An escalation needs attention:\n"
            f"- Reasons: {', '.join(payload.get('reason') or []) or 'unspecified'}\n"
            f"- Summary: {payload.get('summary')}\n"
            f"- Conversation: {payload.get('conversation_id')}"
        )
        return recipients, subject, body

    @staticmethod
    def _build_sender():
        from ..channels.email import NullSender, SmtpSender

        settings = get_settings()
        if settings.EMAIL_SMTP_HOST:
            return SmtpSender(
                host=settings.EMAIL_SMTP_HOST,
                port=settings.EMAIL_SMTP_PORT,
                username=settings.EMAIL_SMTP_USERNAME,
                password=settings.EMAIL_SMTP_PASSWORD,
                from_address=settings.EMAIL_FROM_ADDRESS,
                from_name=settings.EMAIL_FROM_NAME,
            )
        return NullSender()
