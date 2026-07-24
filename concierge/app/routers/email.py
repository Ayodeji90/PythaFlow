"""Inbound email webhook endpoint.

Accepts POST from email providers (SendGrid Inbound Parse, Mailgun, Resend)
and feeds the parsed email through the same concierge pipeline as web chat.

The reply is sent via the configured EmailSender (SMTP by default).
If no email sender is configured, the reply is logged instead.
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..channels.base import TenantNotFound, handle_inbound
from ..channels.email import EmailAdapter, EmailSender, NullSender, ParsedEmail, SmtpSender
from ..config import get_settings
from ..deps import get_db
from ..models import Channel, Tenant
from ..models.enums import ChannelType
from ..services.redis import get_redis_client

log = logging.getLogger("concierge.email")
router = APIRouter()


# ── Provider-specific parsers ────────────────────────────────────────────


def _parse_sendgrid(payload: dict[str, Any]) -> ParsedEmail:
    """Parse a SendGrid Inbound Parse webhook payload.

    SendGrid POSTs one email per request with form-encoded fields.
    See: https://docs.sendgrid.com/for-developers/parsing-email/setting-up-the-inbound-parse-webhook
    """
    envelope = payload.get("envelope", "{}")
    if isinstance(envelope, str):
        import json
        envelope = json.loads(envelope)
    elif not isinstance(envelope, dict):
        envelope = {}

    to_list = envelope.get("to", [])
    to_email = to_list[0] if isinstance(to_list, list) and to_list else payload.get("to", "")

    return ParsedEmail(
        message_id=payload.get("dkim", "") or payload.get("message_id", ""),
        in_reply_to=payload.get("In-Reply-To") or payload.get("in_reply_to"),
        references=payload.get("References") or payload.get("references"),
        subject=payload.get("subject", ""),
        body=payload.get("text", payload.get("plain", "")),
        html=payload.get("html"),
        from_email=payload.get("from", envelope.get("from", "")),
        from_name=payload.get("from_name"),
        to_email=to_email,
        attachments=payload.get("attachments", []),
        raw=payload,
    )


def _extract_from(from_str: str) -> tuple[str, str | None]:
    """Extract (email_addr, display_name) from Mailgun's 'Name <email>' format."""
    if "<" in from_str:
        name = from_str.split("<")[0].strip()
        email = from_str.split("<")[-1].rstrip(">")
        return email, name or None
    return from_str, None


def _parse_mailgun(payload: dict[str, Any]) -> ParsedEmail:
    """Parse a Mailgun incoming webhook payload."""
    from_email, from_name = _extract_from(payload.get("from", ""))
    return ParsedEmail(
        message_id=payload.get("Message-Id", ""),
        in_reply_to=payload.get("In-Reply-To"),
        references=payload.get("References"),
        subject=payload.get("subject", ""),
        body=payload.get("body-plain", ""),
        html=payload.get("body-html"),
        from_email=from_email,
        from_name=from_name,
        to_email=payload.get("recipient", payload.get("to", "")),
        raw=payload,
    )


def _parse_resend(payload: dict[str, Any]) -> ParsedEmail:
    """Parse a Resend inbound webhook payload."""
    return ParsedEmail(
        message_id=payload.get("MessageId", "") or payload.get("message_id", ""),
        in_reply_to=payload.get("In-Reply-To"),
        references=payload.get("References"),
        subject=payload.get("subject", ""),
        body=payload.get("text", payload.get("plain", "")),
        html=payload.get("html"),
        from_email=payload.get("from", ""),
        from_name=payload.get("from_name"),
        to_email=payload.get("to", ""),
        raw=payload,
    )


# ── Tenant routing ───────────────────────────────────────────────────────


async def _resolve_tenant_by_email(db: AsyncSession, to_email: str) -> Tenant:
    """Find the tenant that owns the given email address.

    Uses the `channels` table: a tenant configures an email channel with
    `external_id = their email address`. When mail arrives for that address,
    we look up the channel → tenant.
    """
    channel = (
        await db.execute(
            select(Channel).where(
                Channel.type == ChannelType.email,
                Channel.external_id == to_email,
                Channel.active.is_(True),
            )
        )
    ).scalar_one_or_none()

    if channel is None:
        raise TenantNotFound(f"no active email channel configured for '{to_email}'")

    tenant = await db.get(Tenant, channel.tenant_id)
    if tenant is None:
        raise TenantNotFound(f"tenant for email channel '{to_email}' not found")

    return tenant


# ── Sender factory ───────────────────────────────────────────────────────


def _build_email_sender(settings) -> EmailSender:
    """Build an EmailSender based on app config. Defaults to NullSender
    if SMTP is not configured, so the endpoint is safe to run in dev."""
    smtp_host = settings.EMAIL_SMTP_HOST
    if not smtp_host or smtp_host == "localhost" and not settings.EMAIL_SMTP_USERNAME:
        # No SMTP credentials configured — use null sender in dev.
        return NullSender()

    sender_type = settings.EMAIL_SENDER.lower()
    if sender_type == "sendgrid":
        # Placeholder for future SendGrid sender.
        log.warning("SendGrid sender not yet implemented, falling back to SMTP")
        return SmtpSender(
            host=smtp_host,
            port=settings.EMAIL_SMTP_PORT,
            username=settings.EMAIL_SMTP_USERNAME,
            password=settings.EMAIL_SMTP_PASSWORD,
            from_address=settings.EMAIL_FROM_ADDRESS,
            from_name=settings.EMAIL_FROM_NAME,
        )

    return SmtpSender(
        host=smtp_host,
        port=settings.EMAIL_SMTP_PORT,
        username=settings.EMAIL_SMTP_USERNAME,
        password=settings.EMAIL_SMTP_PASSWORD,
        from_address=settings.EMAIL_FROM_ADDRESS,
        from_name=settings.EMAIL_FROM_NAME,
    )


# ── Endpoint ─────────────────────────────────────────────────────────────


@router.post("/api/email/inbound")
async def inbound_email(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    """Receive an inbound email via webhook and process through the concierge.

    The body can be form-encoded (SendGrid, Mailgun) or JSON (Resend).
    We auto-detect the provider from the payload shape.
    """
    # Parse the raw payload.
    content_type = request.headers.get("content-type", "").lower()
    if "json" in content_type:
        payload = await request.json()
    else:
        form = await request.form()
        payload = dict(form)

    # Auto-detect provider and parse into ParsedEmail.
    if "envelope" in payload:
        parsed = _parse_sendgrid(payload)
        provider = "sendgrid"
    elif "Message-Id" in payload or "recipient" in payload:
        parsed = _parse_mailgun(payload)
        provider = "mailgun"
    elif "MessageId" in payload:
        parsed = _parse_resend(payload)
        provider = "resend"
    else:
        # Generic fallback — try best-effort parsing.
        parsed = ParsedEmail(
            message_id=payload.get("message_id", payload.get("id", "")),
            subject=payload.get("subject", ""),
            body=payload.get("text", payload.get("body", "")),
            from_email=payload.get("from", ""),
            to_email=payload.get("to", ""),
            raw=payload,
        )
        provider = "generic"

    log.info(
        "inbound email [%s] from=%s to=%s subject=%s",
        provider, parsed.from_email, parsed.to_email, parsed.subject,
    )

    # Resolve the tenant from the recipient address.
    if not parsed.to_email:
        log.warning("inbound email has no to_address — discarding")
        return {"status": "accepted", "detail": "no recipient address"}

    # Attempt tenant resolution; fail gracefully if no channel matches.
    try:
        tenant = await _resolve_tenant_by_email(db, parsed.to_email)
    except TenantNotFound:
        log.warning("no tenant for email %s — discarding", parsed.to_email)
        return {"status": "accepted", "detail": f"no tenant for {parsed.to_email}"}

    # Convert to canonical message and run the pipeline.
    msg = EmailAdapter.to_inbound(parsed, tenant_slug=tenant.slug)

    orchestrator: Any = request.app.state.orchestrator
    redis = get_redis_client()

    parts: list[str] = []
    try:
        async for chunk in handle_inbound(
            msg, db=db, redis=redis, orchestrator=orchestrator
        ):
            if chunk.content and chunk.type in ("token", "message"):
                parts.append(chunk.content)
    except TenantNotFound as e:
        log.warning("tenant not found during email processing: %s", e)
        return {"status": "accepted", "detail": str(e)}

    reply = "".join(parts)

    if reply:
        # Build the outbound subject line.
        subject = parsed.subject
        if not subject.lower().startswith("re:"):
            subject = f"Re: {subject}"

        # Get the tenant's email config (if any) from their Channel row.
        tenant_config = tenant.config or {}
        email_config = tenant_config.get("email", {})

        # Send the reply.
        sender = _build_email_sender(get_settings())
        try:
            outbound_id = await sender.send_reply(
                to=parsed.from_email,
                subject=subject,
                body=reply,
                in_reply_to=parsed.message_id,
                tenant_config=email_config,
            )
            log.info("reply sent to %s (message-id: %s)", parsed.from_email, outbound_id)
        except Exception:
            log.exception("failed to send email reply to %s", parsed.from_email)
            # Still return 200 — the email's been processed; outbound failure
            # is a separate concern and will be retried.
            return {"status": "accepted", "detail": "reply not sent (outbound failure)"}

    return {"status": "accepted", "detail": "ok"}