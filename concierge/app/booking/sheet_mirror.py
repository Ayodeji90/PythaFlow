"""Google Sheet mirror — best-effort pilot booking "system".

Appends/updates reservation rows so a pilot venue watches bookings arrive in
a familiar spreadsheet. Failures log a warning and never fail the booking —
the database is always the source of truth.
"""
from __future__ import annotations

import logging

from ..config import get_settings

log = logging.getLogger("concierge.booking.sheet_mirror")


class SheetMirror:
    """Best-effort Google Sheet sync. No-op if not configured."""

    def __init__(self) -> None:
        self._client = None
        self._worksheet = None
        self._enabled = self._connect()

    def _connect(self) -> bool:
        """Try to connect — return False gracefully on any failure."""
        settings = get_settings()
        sheet_id = settings.SHEET_ID
        creds_path = settings.SHEET_CREDENTIALS_JSON

        if not sheet_id or not creds_path:
            log.info("Sheet mirror not configured — skipping")
            return False

        try:
            import gspread  # noqa: PLC0415 — lazy import
        except ImportError:
            log.warning("gspread not installed — Sheet mirror disabled")
            return False

        try:
            self._client = gspread.service_account(filename=creds_path)
            self._worksheet = self._client.open_by_key(sheet_id).sheet1
            log.info("Sheet mirror connected to %s", sheet_id)
            return True
        except Exception:
            log.warning("Sheet mirror failed to connect", exc_info=True)
            return False

    async def append(self, data: dict) -> None:
        """Append a row to the sheet. Log and move on if it fails."""
        if not self._enabled or not self._worksheet:
            return

        try:
            row = [
                data.get("reservation_id", ""),
                str(data.get("date", "")),
                str(data.get("time", "")),
                data.get("party_size", ""),
                data.get("guest_name", ""),
                data.get("status", ""),
                data.get("summary", ""),
            ]
            self._worksheet.append_row(row)
        except Exception:
            log.warning("Sheet mirror append failed", exc_info=True)


_sheet_mirror: SheetMirror | None = None


def get_sheet_mirror() -> SheetMirror:
    """Singleton — connect once per process."""
    global _sheet_mirror
    if _sheet_mirror is None:
        _sheet_mirror = SheetMirror()
    return _sheet_mirror