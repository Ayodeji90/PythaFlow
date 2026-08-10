"""WhatsApp adapter — same brain, new channel envelope.

Maps the standard WhatsApp Business API webhook payload (the envelope that
360dialog, Twilio's sandbox, and Meta's Cloud API all POST) to the canonical
`InboundMessage`. `parse_whatsapp_payload()` is a pure parser, kept separate so
tests can exercise it without HTTP. `WhatsAppAdapter.to_inbound()` is the only
channel-specific code — exactly the promise of the Day-3 pipeline.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ...models.enums import ChannelType
from ...schemas.message import InboundMessage, SenderRef


@dataclass
class ParsedWhatsAppMessage:
    """Normalised inbound WhatsApp message, independent of the BSP envelope."""

    wa_id: str                          # the guest's WhatsApp number (sender)
    message_id: str                     # provider message id (dedup/audit)
    text: str                           # message body
    profile_name: str | None = None
    timestamp: str | None = None
    phone_number_id: str | None = None  # the business number that received it → tenant routing
    display_phone_number: str | None = None
    message_type: str = "text"
    raw: dict[str, Any] | None = None


def parse_whatsapp_payload(
    payload: dict[str, Any],
) -> tuple[list[ParsedWhatsAppMessage], list[dict[str, Any]]]:
    """Extract inbound messages + status callbacks from the webhook envelope.

    Returns (messages, statuses). Status callbacks (sent/delivered/read/failed)
    are returned separately — Day 16 records them on Message.meta; today we just
    acknowledge them.
    """
    messages: list[ParsedWhatsAppMessage] = []
    statuses: list[dict[str, Any]] = []
    for entry in payload.get("entry") or []:
        for change in entry.get("changes") or []:
            value = change.get("value") or {}
            metadata = value.get("metadata") or {}
            contacts = {
                c.get("wa_id"): c for c in (value.get("contacts") or []) if c.get("wa_id")
            }
            for raw_msg in value.get("messages") or []:
                sender_wa = raw_msg.get("from") or ""
                if not sender_wa:
                    # No sender → nothing to thread, nothing to reply to.
                    continue
                contact = contacts.get(sender_wa) or {}
                text = (raw_msg.get("text") or {}).get("body", "")
                messages.append(
                    ParsedWhatsAppMessage(
                        wa_id=sender_wa,
                        profile_name=(contact.get("profile") or {}).get("name"),
                        message_id=raw_msg.get("id", ""),
                        timestamp=raw_msg.get("timestamp"),
                        text=text or "",
                        phone_number_id=metadata.get("phone_number_id"),
                        display_phone_number=metadata.get("display_phone_number"),
                        message_type=raw_msg.get("type", "text"),
                        raw=raw_msg,
                    )
                )
            for status in value.get("statuses") or []:
                statuses.append(status)
    return messages, statuses


class WhatsAppAdapter:
    """Channel adapter: WhatsApp payload → InboundMessage."""

    channel = ChannelType.whatsapp

    @staticmethod
    def to_inbound(msg: ParsedWhatsAppMessage, *, tenant_slug: str) -> InboundMessage:
        """Convert a parsed WhatsApp message to the canonical contract.

        The thread identifier is the guest's number (`wa_id`), and the phone is
        carried on the sender — which is what finally makes
        `guest_memory.resolve_guest()` fire for returning guests (web chat had
        no phone).
        """
        return InboundMessage(
            tenant_slug=tenant_slug,
            channel=ChannelType.whatsapp,
            conversation_ref=msg.wa_id,
            sender=SenderRef(id=msg.wa_id, name=msg.profile_name, phone=msg.wa_id),
            content=msg.text,
            metadata={
                "source": "whatsapp",
                "wa_message_id": msg.message_id,
                "wa_timestamp": msg.timestamp,
                "phone_number_id": msg.phone_number_id,
                "display_phone_number": msg.display_phone_number,
            },
        )


def example_payload() -> dict[str, Any]:
    """A realistic inbound payload (used by tests and the demo docs)."""
    return {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "WHATSAPP_BUSINESS_ACCOUNT_ID",
                "changes": [
                    {
                        "value": {
                            "messaging_product": "whatsapp",
                            "metadata": {
                                "display_phone_number": "15550123456",
                                "phone_number_id": "1000",
                            },
                            "contacts": [
                                {"profile": {"name": "Chidera"}, "wa_id": "15551234567"}
                            ],
                            "messages": [
                                {
                                    "from": "15551234567",
                                    "id": "wamid.ABC123",
                                    "timestamp": "1750000000",
                                    "type": "text",
                                    "text": {"body": "table for 4 on friday at 8"},
                                }
                            ],
                        },
                        "field": "messages",
                    }
                ],
            }
        ],
    }
