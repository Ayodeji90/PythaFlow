"""WhatsApp outbound client + inbound signature validation.

Twilio is the default backend: its WhatsApp Sandbox works with just a Twilio
account (no Meta business verification), which is what lets a pre-registration
founder demo on real WhatsApp today. The `WhatsAppClient` Protocol keeps the rest
of the code vendor-agnostic, so a Meta Cloud API client can slot in later.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import logging
from collections.abc import Awaitable, Callable
from typing import Protocol, TypeVar

log = logging.getLogger("concierge.whatsapp")


class WhatsAppClient(Protocol):
    """Abstract outbound WhatsApp sender."""

    async def send_text(self, *, to: str, body: str) -> str:
        """Send a text message. `to` is the guest's number (with or without the
        `whatsapp:` prefix). Returns the provider message id."""
        ...

    async def send_template(
        self, *, to: str, content_sid: str, variables: dict[str, str] | None = None
    ) -> str:
        """Send a pre-approved template — required OUTSIDE the 24h session window.
        `content_sid` is the provider template id; `variables` fill its slots."""
        ...


class TwilioWhatsAppClient:
    """Sends WhatsApp messages via the Twilio REST API (no SDK dependency)."""

    def __init__(
        self,
        *,
        account_sid: str,
        auth_token: str,
        from_number: str,
        timeout: float = 15.0,
    ) -> None:
        self._sid = account_sid
        self._token = auth_token
        # Twilio wants the "whatsapp:" prefix on both ends.
        prefix = "" if from_number.startswith("whatsapp:") else "whatsapp:"
        self._from = f"{prefix}{from_number}"
        self._timeout = timeout

    async def send_text(self, *, to: str, body: str) -> str:
        import httpx

        to_addr = to if to.startswith("whatsapp:") else f"whatsapp:{to}"
        url = f"https://api.twilio.com/2010-04-01/Accounts/{self._sid}/Messages.json"
        data = {"From": self._from, "To": to_addr, "Body": body}
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.post(url, data=data, auth=(self._sid, self._token))
            resp.raise_for_status()
            return resp.json().get("sid", "")

    async def send_template(
        self, *, to: str, content_sid: str, variables: dict[str, str] | None = None
    ) -> str:
        import httpx

        to_addr = to if to.startswith("whatsapp:") else f"whatsapp:{to}"
        url = f"https://api.twilio.com/2010-04-01/Accounts/{self._sid}/Messages.json"
        data = {"From": self._from, "To": to_addr, "ContentSid": content_sid}
        if variables:
            data["ContentVariables"] = json.dumps(variables)
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.post(url, data=data, auth=(self._sid, self._token))
            resp.raise_for_status()
            return resp.json().get("sid", "")


class NullWhatsAppClient:
    """No-op sender for dev/tests or when no Twilio creds are configured —
    logs the reply instead of sending it, so the pipeline stays runnable."""

    async def send_text(self, *, to: str, body: str) -> str:
        log.info("[null-whatsapp] To: %s | Body: %.140s", to, body)
        return "null-whatsapp"

    async def send_template(
        self, *, to: str, content_sid: str, variables: dict[str, str] | None = None
    ) -> str:
        log.info("[null-whatsapp] To: %s | Template: %s | Vars: %s", to, content_sid, variables)
        return "null-whatsapp-template"


def build_whatsapp_client(settings) -> WhatsAppClient:
    """Pick the outbound client from config. Falls back to NullWhatsAppClient
    when Twilio isn't configured, so the endpoint is always safe to run."""
    if (
        settings.WHATSAPP_PROVIDER.lower() == "twilio"
        and settings.TWILIO_ACCOUNT_SID
        and settings.TWILIO_AUTH_TOKEN
        and settings.TWILIO_WHATSAPP_FROM
    ):
        return TwilioWhatsAppClient(
            account_sid=settings.TWILIO_ACCOUNT_SID,
            auth_token=settings.TWILIO_AUTH_TOKEN,
            from_number=settings.TWILIO_WHATSAPP_FROM,
        )
    return NullWhatsAppClient()


def validate_twilio_signature(
    auth_token: str, url: str, params: dict[str, str], signature: str
) -> bool:
    """Verify a Twilio webhook's X-Twilio-Signature.

    Twilio signs `full_url + each POST param (key+value) sorted by key`, HMAC-SHA1
    with the auth token, base64-encoded. See Twilio's security docs.
    """
    payload = url
    for key in sorted(params):
        payload += key + str(params[key])
    digest = hmac.new(auth_token.encode(), payload.encode("utf-8"), hashlib.sha1).digest()
    expected = base64.b64encode(digest).decode()
    return hmac.compare_digest(expected, signature or "")


T = TypeVar("T")


async def send_with_retry(  # noqa: UP047 — keep 3.12-compatible generic
    send: Callable[[], Awaitable[T]],
    *,
    max_retries: int = 3,
    base_delay: float = 0.5,
) -> T:
    """Call an async send, retrying transient failures with exponential backoff.

    Only *failed* attempts are retried, so a successful send is never duplicated.
    Raises after the last attempt (a permanent failure is loud, never silent)."""
    last_exc: Exception | None = None
    for attempt in range(max_retries):
        try:
            return await send()
        except Exception as exc:  # noqa: BLE001 — retry any transient send failure
            last_exc = exc
            if attempt < max_retries - 1:
                delay = base_delay * (2 ** attempt)
                log.warning(
                    "WhatsApp send failed (attempt %d/%d): %s — retrying in %.1fs",
                    attempt + 1, max_retries, exc, delay,
                )
                await asyncio.sleep(delay)
    raise RuntimeError(
        f"WhatsApp send failed after {max_retries} attempts"
    ) from last_exc
