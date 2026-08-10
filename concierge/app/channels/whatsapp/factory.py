"""WhatsApp client factory — returns the active BSP client.

Defaults to the mock (no network) until a token is configured, mirroring the
email `NullSender` pattern: the app is safe to run in dev without credentials,
and the real client is picked up automatically when `.env` is filled in.
"""
from __future__ import annotations

from ...config import get_settings
from .client import MetaCloudClient, MockWhatsAppClient, WhatsAppClient


def build_whatsapp_client(settings=None) -> WhatsAppClient:
    """Return the configured BSP client (mock until a token is present)."""
    s = settings or get_settings()
    if s.WHATSAPP_BSP.lower() == "mock" or not s.WHATSAPP_TOKEN:
        return MockWhatsAppClient()
    return MetaCloudClient(
        token=s.WHATSAPP_TOKEN,
        phone_id=s.WHATSAPP_PHONE_ID,
        base_url=s.WHATSAPP_GRAPH_BASE,
        timeout=s.LLM_TIMEOUT,
    )
