"""Email adapter — same brain, new channel envelope.

The email channel mirrors the webchat adapter pattern exactly:
- `ParsedEmail` normalises an incoming email regardless of how it arrived
  (SendGrid webhook, IMAP poll, or test harness).
- `EmailAdapter.to_inbound()` converts a `ParsedEmail` into the canonical
  `InboundMessage` the shared pipeline expects.
- `EmailSender` (Protocol) + `SmtpSender` handle the outbound hop after the
  orchestrator produces a reply.

Threading: email's `Message-ID` → `external_thread_id` on the Conversation row.
The `(tenant_id, external_thread_id)` index gives fast thread lookup.
A reply (with `In-Reply-To`) reuses the same Conversation as the original email.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from email.mime.text import MIMEText
from email.utils import formataddr, formatdate, make_msgid
from typing import Protocol

from ..models.enums import ChannelType
from ..schemas.message import InboundMessage, SenderRef

log = logging.getLogger("concierge.email")


# ── Inbound: ParsedEmail ─────────────────────────────────────────────────


@dataclass
class ParsedEmail:
    """Normalised representation of an incoming email, independent of the
    provider that delivered it (SendGrid, Mailgun, IMAP, etc.)."""

    message_id: str                  # RFC 5322 Message-ID
    in_reply_to: str | None = None   # Message-ID this replies to (for threading)
    references: str | None = None    # full References header chain
    subject: str = ""
    body: str = ""                   # plain-text body
    html: str | None = None          # HTML body, if available
    from_email: str = ""
    from_name: str | None = None
    to_email: str = ""               # who the guest sent TO — used for tenant routing
    date: datetime | None = None
    attachments: list[str] = field(default_factory=list)
    raw: dict | None = None          # provider-specific extras (envelope, headers, etc.)

    @property
    def thread_ref(self) -> str:
        """Stable thread identifier used as the Conversation's external_thread_id.

        - A reply carries `In-Reply-To` → use that to find the existing thread.
        - A brand-new email has no `In-Reply-To` → use its own `Message-ID`.
        """
        return self.in_reply_to or self.message_id


# ── Channel Adapter ──────────────────────────────────────────────────────


class EmailAdapter:
    """Channel adapter: email → InboundMessage."""

    channel = ChannelType.email

    @staticmethod
    def to_inbound(email: ParsedEmail, *, tenant_slug: str) -> InboundMessage:
        """Convert a parsed email to the canonical message contract.

        The email body becomes `content` (what the orchestrator sees).
        Full email headers are stored in `metadata["email"]` so the router
        has everything it needs to construct a reply later.
        """
        return InboundMessage(
            tenant_slug=tenant_slug,
            channel=ChannelType.email,
            conversation_ref=email.thread_ref,
            sender=SenderRef(
                id=email.from_email,
                name=email.from_name,
            ),
            content=email.body or email.subject,
            locale=None,
            metadata={
                "email": {
                    "message_id": email.message_id,
                    "in_reply_to": email.in_reply_to,
                    "references": email.references,
                    "subject": email.subject,
                    "from_email": email.from_email,
                    "from_name": email.from_name,
                    "to_email": email.to_email,
                    "date": email.date.isoformat() if email.date else None,
                    "attachments": email.attachments or [],
                },
                "source": "email",
            },
        )


# ── Outbound: EmailSender Protocol + SMTP implementation ─────────────────


class EmailSender(Protocol):
    """Abstract outbound email sender.

    Implementations: `SmtpSender` (default), `SendGridSender` (future).
    """

    async def send_reply(
        self,
        *,
        to: str,
        subject: str,
        body: str,
        in_reply_to: str | None = None,
        tenant_config: dict | None = None,
    ) -> str:
        """Send an email reply. Returns the outbound Message-ID."""
        ...


class SmtpSender:
    """Sends email via SMTP using aiosmtplib.

    Designed for transactional outbound (concierge replies), not bulk mail.
    Defaults to localhost:587 which works with most SMTP relays.
    """

    def __init__(
        self,
        host: str = "localhost",
        port: int = 587,
        username: str = "",
        password: str = "",
        *,
        use_tls: bool = True,
        from_address: str = "concierge@localhost",
        from_name: str = "Concierge",
    ) -> None:
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.use_tls = use_tls
        self.from_address = from_address
        self.from_name = from_name
        self._message_id_counter = 0

    async def send_reply(
        self,
        *,
        to: str,
        subject: str,
        body: str,
        in_reply_to: str | None = None,
        tenant_config: dict | None = None,
    ) -> str:
        """Connect to SMTP, send one reply, return the outbound Message-ID."""
        import aiosmtplib

        # Allow per-tenant override of sender identity.
        from_addr = (tenant_config or {}).get("from_address") or self.from_address
        from_name = (tenant_config or {}).get("from_name") or self.from_name

        msg = MIMEText(body, _charset="utf-8")
        msg["From"] = formataddr((from_name, from_addr))
        msg["To"] = to
        msg["Subject"] = subject
        msg["Date"] = formatdate(localtime=True)

        outbound_id = make_msgid(domain=from_addr.split("@")[-1] or "localhost")
        msg["Message-ID"] = outbound_id

        if in_reply_to:
            msg["In-Reply-To"] = in_reply_to
            msg["References"] = in_reply_to

        try:
            if self.use_tls:
                await aiosmtplib.send(
                    msg,
                    hostname=self.host,
                    port=self.port,
                    username=self.username or None,
                    password=self.password or None,
                    use_tls=True,
                )
            else:
                await aiosmtplib.send(
                    msg,
                    hostname=self.host,
                    port=self.port,
                    username=self.username or None,
                    password=self.password or None,
                    start_tls=False,
                )
        except Exception:
            log.exception("SMTP send failed to %s", to)
            raise

        return outbound_id


class NullSender:
    """No-op sender for development/testing when no email backend is configured.
    Logs the reply instead of sending it."""

    async def send_reply(
        self,
        *,
        to: str,
        subject: str,
        body: str,
        in_reply_to: str | None = None,
        tenant_config: dict | None = None,
    ) -> str:
        log.info(
            "[null-sender] To: %s | Subject: %s | Body: %.120s",
            to, subject, body,
        )
        return "<null-sender@local>"