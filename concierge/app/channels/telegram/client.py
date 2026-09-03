"""Telegram MTProto outbound client using Telethon.

Telethon is a mature, pure-Python MTProto implementation that handles
session management, encryption, and connection lifecycle.
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import TypeVar

from ...config import get_settings

log = logging.getLogger("concierge.telegram")


class TelegramClient:
    """Abstract outbound Telegram sender."""

    async def send_text(self, *, chat_id: int, text: str) -> str:
        """Send a text message. Returns the message ID."""
        ...

    async def start(self) -> None:
        """Start the client connection."""
        ...

    async def stop(self) -> None:
        """Stop the client connection."""
        ...


class TelethonClient(TelegramClient):
    """Sends Telegram messages via MTProto using Telethon."""

    def __init__(
        self,
        *,
        api_id: int,
        api_hash: str,
        phone_number: str | None = None,
        session_string: str | None = None,
        timeout: float = 15.0,
    ) -> None:
        self._api_id = api_id
        self._api_hash = api_hash
        self._phone_number = phone_number
        self._session_string = session_string
        self._timeout = timeout
        self._client = None
        self._started = False

    async def _create_client(self):
        """Create the Telethon client."""
        from telethon import TelegramClient as TelethonTelegramClient
        from telethon.sessions import StringSession

        if self._session_string:
            session = StringSession(self._session_string)
        else:
            session = "concierge_session"  # file-based session for dev

        client = TelethonTelegramClient(
            session,
            self._api_id,
            self._api_hash,
            timeout=self._timeout,
        )
        return client

    async def start(self) -> None:
        """Start the MTProto connection and authenticate if needed."""
        if self._started and self._client and self._client.is_connected():
            return

        self._client = await self._create_client()
        await self._client.connect()

        if not await self._client.is_user_authorized():
            if not self._phone_number:
                raise RuntimeError(
                    "Telegram client not authorized and no phone number provided "
                    "for authentication. Run initial authentication manually."
                )
            await self._client.send_code_request(self._phone_number)
            # In production, you'd need a way to get the code from the user
            # For now, this will wait for manual code entry
            code = input("Enter Telegram authentication code: ")
            await self._client.sign_in(self._phone_number, code)

        self._started = True
        log.info("Telegram MTProto client started and authorized")

    async def stop(self) -> None:
        """Stop the MTProto connection."""
        if self._client and self._client.is_connected():
            await self._client.disconnect()
            self._started = False
            log.info("Telegram MTProto client stopped")

    async def send_text(self, *, chat_id: int, text: str) -> str:
        """Send a text message via MTProto."""
        if not self._started:
            await self.start()

        if not self._client:
            raise RuntimeError("Telegram client not started")

        # Split long messages (Telegram limit is 4096 chars)
        if len(text) > 4096:
            parts = [text[i:i+4096] for i in range(0, len(text), 4096)]
            message_ids = []
            for part in parts:
                msg = await self._client.send_message(chat_id, part)
                message_ids.append(str(msg.id))
            return ",".join(message_ids)

        msg = await self._client.send_message(chat_id, text)
        return str(msg.id)


class NullTelegramClient:
    """No-op sender for dev/tests when MTProto isn't configured."""

    async def send_text(self, *, chat_id: int, text: str) -> str:
        log.info("[null-telegram] To: %s | Body: %.140s", chat_id, text)
        return "null-telegram"

    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        pass


def build_telegram_client() -> TelegramClient | NullTelegramClient:
    """Pick the outbound client from config."""
    settings = get_settings()

    if settings.TELEGRAM_API_ID and settings.TELEGRAM_API_HASH:
        return TelethonClient(
            api_id=settings.TELEGRAM_API_ID,
            api_hash=settings.TELEGRAM_API_HASH,
            phone_number=settings.TELEGRAM_PHONE_NUMBER or None,
            session_string=settings.TELEGRAM_SESSION_STRING or None,
        )
    return NullTelegramClient()


T = TypeVar("T")


async def send_with_retry(  # noqa: UP047 — keep 3.12-compatible generic
    send: Callable[[], Awaitable[T]],
    *,
    max_retries: int = 3,
    base_delay: float = 0.5,
) -> T:
    """Call an async send, retrying transient failures with exponential backoff.

    Only *failed* attempts are retried, so a successful send is never duplicated.
    Raises after the last attempt (a permanent failure is loud, never silent).
    """
    last_exc: Exception | None = None
    for attempt in range(max_retries):
        try:
            return await send()
        except Exception as exc:  # noqa: BLE001 — retry any transient send failure
            last_exc = exc
            # Check for Telegram flood wait
            if "FLOOD_WAIT" in str(exc).upper() or "flood" in str(exc).lower():
                # Try to extract wait time from error
                import re
                match = re.search(r"(\d+)", str(exc))
                if match:
                    wait_time = int(match.group(1))
                    log.warning(
                        "Telegram flood wait: %ds, sleeping", wait_time
                    )
                    await asyncio.sleep(wait_time)
                    continue

            if attempt < max_retries - 1:
                delay = base_delay * (2 ** attempt)
                log.warning(
                    "Telegram send failed (attempt %d/%d): %s — retrying in %.1fs",
                    attempt + 1, max_retries, exc, delay,
                )
                await asyncio.sleep(delay)
    raise RuntimeError(
        f"Telegram send failed after {max_retries} attempts"
    ) from last_exc