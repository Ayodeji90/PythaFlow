"""WhatsApp outbound transport — a subscriber on the notify() seam.

Registered once at startup (see app.main). On `NOTIF_MESSAGE_SENT` it locates
the originating conversation (via payload's conversation_id, request_id or
reservation_id), and if that conversation's channel is WhatsApp it delivers the
message through the BSP client.

Confirmations, reminders and fulfilment replies all flow through here — the
same code path that web chat persists, now with a phone number. This is the
"transport swap, not rewrite" the Week-2 notification seam was built for.

Day 16 hardening:
- **24h service window**: in-window sends are free-form text; out-of-window
  sends must use an approved template. An un-templated out-of-window send is a
  loud error (blocked + persisted as failed), never a silent drop — Meta
  silently fails free-form text outside the window.
- **Idempotent delivery**: every send is keyed by (conversation, body); a
  retried notification is never delivered twice.
- **Persisted outbound rows**: each delivered/failed message is stored with the
  provider id + delivery meta so the console (Day 17) can show ticks.
"""
from __future__ import annotations

import hashlib
import logging
from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...db import SessionLocal
from ...models import Conversation, Guest, Message, Request, Reservation
from ...models.enums import ChannelType, MessageRole, ReservationStatus
from ...notifications import NOTIF_MESSAGE_SENT
from .client import WhatsAppClient, WhatsAppSendError
from .retry import send_with_retry
from .templates import TEMPLATES, resolve_template_name
from .window import choose_send_mode

log = logging.getLogger("concierge.whatsapp.transport")


class WhatsAppTransport:
    """Delivers NOTIF_MESSAGE_SENT events over WhatsApp when appropriate."""

    def __init__(
        self,
        client: WhatsAppClient,
        *,
        template_confirm: str = "booking_confirmed",
        template_reminder: str = "booking_reminder",
    ) -> None:
        self._client = client
        # Per-intent template names come from settings at wiring time; they must
        # be members of APPROVED_TEMPLATES or resolve_template_name returns None.
        self._template_defaults = {
            "confirmation": template_confirm,
            "reminder": template_reminder,
        }

    async def handle_event(
        self,
        event: str,
        *,
        tenant_id,
        request_id=None,
        payload: dict,
    ) -> None:
        if event != NOTIF_MESSAGE_SENT:
            return

        # Explicit channel routing from the sender (e.g. send_message tool).
        channel_hint = payload.get("channel_type")
        if channel_hint not in (None, "", "whatsapp"):
            return

        async with SessionLocal() as db:
            conv = await self._resolve_conversation(db, payload, request_id)
            if conv is None or conv.channel_type != ChannelType.whatsapp:
                return  # not our channel — another transport's job (or none yet)

            phone = await self._guest_phone(db, conv)
            if not phone:
                log.warning(
                    "whatsapp outbound: conversation %s has no guest phone — dropping",
                    conv.id,
                )
                return

            body = await self._message_body(db, conv, payload)
            if not body:
                return

            await self._deliver(db, conv, phone, body, payload)

    # ── delivery ─────────────────────────────────────────────────────────

    async def _deliver(
        self, db: AsyncSession, conv: Conversation, phone: str, body: str, payload: dict
    ) -> None:
        template_name = resolve_template_name(payload, defaults=self._template_defaults)
        last_inbound_at = await self._last_inbound_at(db, conv)

        try:
            mode = choose_send_mode(last_inbound_at, template_name)
        except ValueError as exc:
            # Loud, never silent (Week-3 risk 4): blocked out-of-window send is
            # logged AND persisted as failed so it shows in the console.
            log.error("whatsapp outbound blocked: %s (conversation %s)", exc, conv.id)
            await self._persist_outcome(db, conv, body, failed="blocked")
            return

        # Staff replies (Day 18) ride the same transport but are keyed by a
        # fresh nonce so they can never collide with a notification's key, and
        # they were already persisted by the takeover endpoint (role=staff).
        is_staff = payload.get("role") == "staff"
        nonce = payload.get("nonce") if is_staff else None
        idem_key = self._idempotency_key(conv.id, body, nonce=nonce)
        if await self._already_delivered(db, conv.id, idem_key):
            return

        try:
            if mode == "template":
                variables = await self._template_variables(db, conv, template_name)
                msg_id = await send_with_retry(
                    lambda: self._client.send_template(
                        to=phone, name=template_name, variables=variables
                    )
                )
            else:
                msg_id = await send_with_retry(
                    lambda: self._client.send_text(to=phone, body=body)
                )
        except WhatsAppSendError:
            # Loud failure, never silent — the Week-2 rule. The failed row keeps
            # the idempotency key, so a re-notify (not a retry) can try again.
            log.exception("whatsapp outbound send failed for conversation %s", conv.id)
            if not is_staff:
                await self._persist_outcome(
                    db, conv, body, idem_key=idem_key, failed="send_error"
                )
            return

        if is_staff:
            log.info("whatsapp staff reply delivered to %s (provider id %s)", phone, msg_id)
            return
        await self._persist_outcome(
            db, conv, body, idem_key=idem_key, wa_message_id=msg_id
        )
        log.info(
            "whatsapp outbound delivered to %s (mode=%s, provider id %s)",
            phone,
            mode,
            msg_id,
        )

    # ── helpers ─────────────────────────────────────────────────────────

    @staticmethod
    async def _last_inbound_at(db: AsyncSession, conv: Conversation) -> datetime | None:
        """The guest's most recent message — the anchor of the 24h window."""
        return (
            await db.execute(
                select(Message.created_at)
                .where(
                    Message.conversation_id == conv.id,
                    Message.role == MessageRole.guest,
                )
                .order_by(Message.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()

    @staticmethod
    def _idempotency_key(conv_id, body: str, nonce: str | None = None) -> str:
        """Deterministic per-(conversation, body) key so a retried notification
        can be recognised and never double-sent. A staff send passes a fresh
        nonce so its key is unique and never collides with a notification's."""
        raw = f"{conv_id}:{nonce or body}".encode()
        return hashlib.sha256(raw).hexdigest()[:24]

    @staticmethod
    async def _already_delivered(
        db: AsyncSession, conv_id, idem_key: str
    ) -> bool:
        """True when this exact message was already delivered (has a provider id).

        Check-then-act (no unique constraint backing the key): two *concurrent*
        identical notifications could both pass this and double-send. In practice
        re-notifies are sequential and inbound turns are serialised by the turn
        lock, so this is a documented, conscious trade-off for the sandbox — a
        unique index on (tenant_id, idempotency_key) closes it for production.
        """
        row = (
            await db.execute(
                select(Message)
                .where(
                    Message.conversation_id == conv_id,
                    Message.meta["idempotency_key"].astext == idem_key,
                )
                .limit(1)
            )
        ).scalars().first()
        if row is None:
            return False
        if row.meta.get("wa_message_id"):
            log.info(
                "whatsapp outbound already delivered (key %s) — skipping", idem_key
            )
            return True
        return False  # previously failed — a re-notify may retry

    @staticmethod
    async def _template_variables(
        db: AsyncSession, conv: Conversation, template_name: str
    ) -> dict[str, str]:
        """Fill the template's ordered variables from the latest confirmed
        Reservation, or from nothing (empty strings) when facts are missing."""
        spec = TEMPLATES.get(template_name)
        if spec is None:
            return {}
        values: dict[str, str] = {}
        res = await WhatsAppTransport._latest_confirmed_reservation(db, conv)
        if res is not None and res.date is not None and res.time is not None:
            values = {
                "party_size": str(res.party_size),
                "date": res.date.isoformat(),
                "time": res.time.strftime("%H:%M"),
                "area": res.area or "",
            }
        return {name: values.get(name, "") for name in spec.variables}

    @staticmethod
    async def _persist_outcome(
        db: AsyncSession,
        conv: Conversation,
        body: str,
        *,
        idem_key: str | None = None,
        wa_message_id: str | None = None,
        failed: str | None = None,
    ) -> None:
        """Persist one outbound turn so the console sees delivery state."""
        meta: dict = {"channel": "whatsapp"}
        if idem_key:
            meta["idempotency_key"] = idem_key
        if wa_message_id:
            meta["wa_message_id"] = wa_message_id
        if failed:
            meta["delivery"] = {"failed": True, "reason": failed}
        else:
            meta["delivery"] = {}
        db.add(
            Message(
                tenant_id=conv.tenant_id,
                conversation_id=conv.id,
                role=MessageRole.assistant,
                content=body,
                meta=meta,
            )
        )
        await db.commit()

    # ── unchanged Day-15 helpers ────────────────────────────────────────

    async def _resolve_conversation(
        self, db: AsyncSession, payload: dict, request_id
    ) -> Conversation | None:
        conv_id = payload.get("conversation_id")
        if conv_id:
            conv = await self._get_or_none(db, Conversation, conv_id)
            if conv is not None:
                return conv

        # A Request knows its conversation (fulfilment notify passes request_id).
        if request_id is not None:
            req = await self._get_or_none(db, Request, request_id)
            if req is not None and req.conversation_id:
                return await self._get_or_none(db, Conversation, req.conversation_id)

        # Reminders notify with reservation_id only.
        res_id = payload.get("reservation_id")
        if res_id:
            res = await self._get_or_none(db, Reservation, res_id)
            if res is not None and res.conversation_id:
                return await self._get_or_none(db, Conversation, res.conversation_id)
        return None

    @staticmethod
    async def _get_or_none(db: AsyncSession, model, raw_id) -> Conversation | None:
        try:
            return await db.get(model, UUID(str(raw_id)))
        except (ValueError, TypeError):
            return None

    @staticmethod
    async def _guest_phone(db: AsyncSession, conv: Conversation) -> str | None:
        if not conv.guest_id:
            return None
        guest = await db.get(Guest, conv.guest_id)
        return guest.phone if guest else None

    @staticmethod
    async def _message_body(
        db: AsyncSession, conv: Conversation, payload: dict
    ) -> str | None:
        # An explicit message wins (send_message tool / reminders).
        if payload.get("message"):
            return str(payload["message"])
        # Confirmations are built from the confirmed Reservation artifact — never
        # from whatever the assistant happened to say last (which could be the
        # "sent for review" line). This is the text a guest should actually get.
        if payload.get("subject") == "confirmation":
            return await WhatsAppTransport._confirmation_text(db, conv)
        return None

    @staticmethod
    async def _confirmation_text(db: AsyncSession, conv: Conversation) -> str | None:
        """Build the confirmation copy from the latest confirmed Reservation
        linked to this conversation."""
        res = await WhatsAppTransport._latest_confirmed_reservation(db, conv)
        if res is None or res.date is None or res.time is None:
            return None
        text = (
            f"Your table for {res.party_size} on {res.date.isoformat()} "
            f"at {res.time.strftime('%H:%M')} is confirmed. "
            "We look forward to seeing you!"
        )
        if res.area:
            text += f" Area: {res.area}."
        return text

    @staticmethod
    async def _latest_confirmed_reservation(
        db: AsyncSession, conv: Conversation
    ) -> Reservation | None:
        return (
            await db.execute(
                select(Reservation)
                .where(
                    Reservation.conversation_id == conv.id,
                    Reservation.status == ReservationStatus.confirmed,
                )
                .order_by(Reservation.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
