"""Telegram outbound client using the Bot API over HTTP (no MTProto/Telethon).

A bot token (created via @BotFather) is the only credential needed — sending is
a plain HTTPS POST to api.telegram.org, mirroring how the WhatsApp channel uses
the Twilio REST API. There is no user account, phone number, or session, so
there is nothing to authenticate interactively and nothing to hang on stdin.

One identity end to end: the guest messages @VenueBot and the reply is sent by
the SAME bot (its token lives in Channel.config["bot_token"]).
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import TypeVar

import httpx

log = logging.getLogger("concierge.telegram")

TELEGRAM_API_BASE = "https://api.telegram.org"
MAX_MESSAGE_CHARS = 4096  # Telegram's hard limit per message


class TelegramClient:
    """Abstract outbound Telegram sender (Bot API)."""

    async def send_text(self, *, chat_id: int, text: str) -> str:
        """Send a text message. Returns the provider message id(s)."""
        ...


class BotApiTelegramClient(TelegramClient):
    """Sends via the Bot API: POST /bot<token>/sendMessage.

    Long replies are split on the 4096-char limit and sent as separate
    messages; the returned string joins their message ids with commas.
    """

    def __init__(
        self,
        *,
        bot_token: str,
        timeout: float = 15.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._token = bot_token
        self._timeout = timeout
        # Test seam — lets tests inject an httpx.MockTransport.
        self._transport = transport

    async def send_text(self, *, chat_id: int, text: str) -> str:
        url = f"{TELEGRAM_API_BASE}/bot{self._token}/sendMessage"
        parts = (
            [text]
            if len(text) <= MAX_MESSAGE_CHARS
            else [text[i : i + MAX_MESSAGE_CHARS] for i in range(0, len(text), MAX_MESSAGE_CHARS)]
        )
        message_ids: list[str] = []
        kwargs = {"timeout": self._timeout}
        if self._transport is not None:
            kwargs["transport"] = self._transport
        async with httpx.AsyncClient(**kwargs) as client:
            for part in parts:
                resp = await client.post(
                    url, json={"chat_id": chat_id, "text": part}
                )
                resp.raise_for_status()
                result = resp.json().get("result", {})
                message_ids.append(str(result.get("message_id", "")))
        return ",".join(message_ids)


class NullTelegramClient:
    """No-op sender for dev/tests when no bot token is configured — logs the
    reply instead of sending it, so the pipeline stays runnable."""

    async def send_text(self, *, chat_id: int, text: str) -> str:
        log.info("[null-telegram] To: %s | Body: %.140s", chat_id, text)
        return "null-telegram"


def build_telegram_client(
    bot_token: str | None,
) -> TelegramClient | NullTelegramClient:
    """Pick the outbound client for a channel's bot token.

    Tokens are per-venue (stored in Channel.config["bot_token"]), so the caller
    passes the resolved channel's token. Falls back to NullTelegramClient when
    missing so the endpoint is always safe to run.
    """
    if bot_token:
        return BotApiTelegramClient(bot_token=bot_token)
    return NullTelegramClient()


T = TypeVar("T")


async def send_with_retry(  # noqa: UP047 — keep 3.12-compatible generic
    send: Callable[[], Awaitable[T]],
    *,
    max_retries: int = 3,
    base_delay: float = 0.5,
) -> T:
    """Call an async send, retrying transient failures with exponential backoff.

    Only *failed* attempts are retried, so a successful send is never
    duplicated. Telegram rate limits (HTTP 429) respect the Retry-After header
    when present. Raises after the last attempt — a permanent failure is loud,
    never silent.
    """
    last_exc: Exception | None = None
    for attempt in range(max_retries):
        try:
            return await send()
        except httpx.HTTPStatusError as exc:
            last_exc = exc
            if exc.response.status_code == 429:
                wait = _retry_after_seconds(exc, base_delay * (2**attempt))
                log.warning(
                    "Telegram rate limited (attempt %d/%d) — sleeping %.1fs",
                    attempt + 1, max_retries, wait,
                )
                await asyncio.sleep(wait)
                continue
            if attempt < max_retries - 1:
                delay = base_delay * (2**attempt)
                log.warning(
                    "Telegram send failed (attempt %d/%d): %s — retrying in %.1fs",
                    attempt + 1, max_retries, exc, delay,
                )
                await asyncio.sleep(delay)
        except Exception as exc:  # noqa: BLE001 — retry any transient send failure
            last_exc = exc
            if attempt < max_retries - 1:
                delay = base_delay * (2**attempt)
                log.warning(
                    "Telegram send failed (attempt %d/%d): %s — retrying in %.1fs",
                    attempt + 1, max_retries, exc, delay,
                )
                await asyncio.sleep(delay)
    raise RuntimeError(
        f"Telegram send failed after {max_retries} attempts"
    ) from last_exc


def _retry_after_seconds(exc: httpx.HTTPStatusError, fallback: float) -> float:
    """Parse Telegram's Retry-After header (seconds) with a sane cap."""
    header = exc.response.headers.get("Retry-After")
    try:
        wait = float(header)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return fallback
    return min(max(wait, 0.0), 60.0)