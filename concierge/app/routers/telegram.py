"""Telegram webhook endpoints — re-exported from channels/telegram for consistent routing."""
from __future__ import annotations

from app.channels.telegram.router import router

__all__ = ["router"]