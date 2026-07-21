"""PII-safe logging. A guest's email / phone / card number must never land in a
log line in plaintext, so we redact them in the formatter — after the message is
assembled, catching anything any module logged."""
from __future__ import annotations

import logging
import re

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
# 13–19 digits (optionally space/dash separated) — payment cards. Redact BEFORE
# phone, since a card also matches the looser phone shape.
_CARD = re.compile(r"\b(?:\d[ -]?){13,19}\b")
# +country and/or 8+ digits with common separators.
_PHONE = re.compile(r"(?<![\w.])\+?\d(?:[\d\s().-]{6,})\d(?![\w])")


def redact(text: str) -> str:
    text = _EMAIL.sub("[redacted-email]", text)
    text = _CARD.sub("[redacted-card]", text)
    text = _PHONE.sub("[redacted-phone]", text)
    return text


class RedactingFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return redact(super().format(record))


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(RedactingFormatter("%(levelname)s:%(name)s:%(message)s"))
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)
