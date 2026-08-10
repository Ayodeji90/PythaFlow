"""WhatsApp BSP client seam — mirrors the LLM-provider pattern.

The concierge core depends only on the `WhatsAppClient` Protocol. Implementations:

- `MockWhatsAppClient` — no network; records sends (dev + tests)
- `MetaCloudClient`    — real sends via the WhatsApp Business Cloud API
                         (graph.facebook.com). This is the endpoint that
                         360dialog, Twilio's WhatsApp API, and Meta's own Cloud
                         API all proxy, so one client covers the Day-1 BSP
                         decision; swapping BSPs = a different base URL/token.

Swapping BSPs = editing `.env`; adding a non-Meta BSP = one new file
implementing the Protocol.
"""
from __future__ import annotations

import logging
from typing import Protocol

log = logging.getLogger("concierge.whatsapp.client")


class WhatsAppSendError(RuntimeError):
    """Raised when the BSP rejects or fails an outbound send."""


class WhatsAppClient(Protocol):
    """What an outbound transport needs from a BSP."""

    async def send_text(self, *, to: str, body: str) -> str:
        """Send a free-form text message. Returns the provider message id."""
        ...

    async def send_template(self, *, to: str, name: str, variables: dict) -> str:
        """Send an approved template (e.g. booking_confirmed). Returns the id."""
        ...


class MockWhatsAppClient:
    """No-network client for dev + tests. Records every send so tests can assert
    what was delivered without touching a BSP."""

    def __init__(self) -> None:
        self.sent: list[dict] = []

    async def send_text(self, *, to: str, body: str) -> str:
        self.sent.append({"kind": "text", "to": to, "body": body})
        log.info("[mock-whatsapp] text to %s: %.120s", to, body)
        return f"mock-{len(self.sent)}"

    async def send_template(self, *, to: str, name: str, variables: dict) -> str:
        self.sent.append({"kind": "template", "to": to, "name": name, "variables": variables})
        log.info("[mock-whatsapp] template %s to %s", name, to)
        return f"mock-{len(self.sent)}"


class MetaCloudClient:
    """Sends via the WhatsApp Business Cloud API (graph.facebook.com)."""

    def __init__(
        self,
        token: str,
        phone_id: str,
        base_url: str = "https://graph.facebook.com/v21.0",
        timeout: float = 30.0,
    ) -> None:
        self._token = token
        self._phone_id = phone_id
        self._base = base_url.rstrip("/")
        self._timeout = timeout

    async def send_text(self, *, to: str, body: str) -> str:
        return await self._post(
            {
                "messaging_product": "whatsapp",
                "recipient_type": "individual",
                "to": to,
                "type": "text",
                "text": {"body": body},
            }
        )

    async def send_template(self, *, to: str, name: str, variables: dict) -> str:
        payload: dict = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to,
            "type": "template",
            "template": {
                "name": name,
                "language": {"code": "en"},
                "components": [],
            },
        }
        if variables:
            payload["template"]["components"].append(
                {
                    "type": "body",
                    "parameters": [{"type": "text", "text": str(v)} for v in variables.values()],
                }
            )
        return await self._post(payload)

    async def _post(self, payload: dict) -> str:
        import httpx

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.post(
                    f"{self._base}/{self._phone_id}/messages",
                    headers={"Authorization": f"Bearer {self._token}"},
                    json=payload,
                )
        except httpx.TransportError as exc:
            # Network/timeout failures become WhatsAppSendError so the retry
            # layer (send_with_retry) sees ONE error type for every transient
            # failure — otherwise httpx errors would never be retried.
            raise WhatsAppSendError(f"BSP unreachable: {exc}") from exc
        if response.status_code >= 400:
            log.error(
                "WhatsApp send failed: HTTP %s — %s", response.status_code, response.text[:500]
            )
            raise WhatsAppSendError(f"BSP returned HTTP {response.status_code}")
        data = response.json()
        messages = data.get("messages") or []
        return messages[0].get("id", "") if messages else ""
