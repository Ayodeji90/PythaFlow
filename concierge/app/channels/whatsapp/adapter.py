"""WhatsApp channel adapter — the ONE new mapping needed to add WhatsApp.

`WhatsAppInbound` normalises a Twilio inbound webhook; `WhatsAppAdapter.to_inbound`
turns it into the canonical `InboundMessage` the shared pipeline already speaks.
Nothing in the orchestrator or tools changes — that's the whole point.
"""

from __future__ import annotations

from dataclasses import dataclass

from ...models.enums import ChannelType
from ...schemas.message import InboundMessage, SenderRef


@dataclass
class WhatsAppInbound:
    """Normalised inbound WhatsApp message, independent of the BSP."""

    from_number: str  # guest, e.g. "whatsapp:+2348012345678"
    to_number: str  # venue/sandbox line, e.g. "whatsapp:+14155238886"
    body: str
    wa_id: str  # guest number, digits only (Twilio "WaId")
    profile_name: str | None = None
    message_sid: str = ""
    raw: dict | None = None

    @staticmethod
    def from_twilio_form(form: dict) -> WhatsAppInbound:
        """Build from a Twilio inbound webhook's form fields."""
        frm = form.get("From", "")
        wa_id = form.get("WaId") or frm.replace("whatsapp:", "").lstrip("+")
        return WhatsAppInbound(
            from_number=frm,
            to_number=form.get("To", ""),
            body=form.get("Body", ""),
            wa_id=wa_id,
            profile_name=form.get("ProfileName") or None,
            message_sid=form.get("MessageSid") or form.get("SmsMessageSid", ""),
            raw=dict(form),
        )


class WhatsAppAdapter:
    """Channel adapter: WhatsApp → InboundMessage."""

    channel = ChannelType.whatsapp

    @staticmethod
    def to_inbound(inbound: WhatsAppInbound, *, tenant_slug: str) -> InboundMessage:
        # The guest's WhatsApp id is the stable thread key (per tenant), and the
        # phone is what finally lets guest_memory recognise a returning guest —
        # web chat never had one.
        wa = inbound.wa_id
        phone = f"+{wa}" if wa and not wa.startswith("+") else wa
        return InboundMessage(
            tenant_slug=tenant_slug,
            channel=ChannelType.whatsapp,
            conversation_ref=inbound.wa_id,
            sender=SenderRef(
                id=inbound.wa_id,
                name=inbound.profile_name,
                phone=phone or None,
            ),
            content=inbound.body,
            metadata={
                "whatsapp": {
                    "from": inbound.from_number,
                    "to": inbound.to_number,
                    "message_sid": inbound.message_sid,
                    "profile_name": inbound.profile_name,
                },
                "source": "whatsapp",
            },
        )
