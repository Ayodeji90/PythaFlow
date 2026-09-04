"""WhatsApp channel (Twilio-backed, Meta Cloud API swappable later)."""

from .adapter import WhatsAppAdapter, WhatsAppInbound
from .client import (
    NullWhatsAppClient,
    TwilioWhatsAppClient,
    WhatsAppClient,
    build_whatsapp_client,
    send_with_retry,
    validate_twilio_signature,
)
from .window import last_inbound_at, session_window_open

__all__ = [
    "WhatsAppAdapter",
    "WhatsAppInbound",
    "WhatsAppClient",
    "TwilioWhatsAppClient",
    "NullWhatsAppClient",
    "build_whatsapp_client",
    "send_with_retry",
    "validate_twilio_signature",
    "session_window_open",
    "last_inbound_at",
]
