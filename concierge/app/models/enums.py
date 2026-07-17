"""Domain enums, stored as VARCHAR + CHECK (native_enum=False) so adding a new
value later is a light migration instead of an ALTER TYPE."""
from __future__ import annotations

import enum

from sqlalchemy import Enum as SAEnum


class UserRole(enum.StrEnum):
    owner = "owner"
    manager = "manager"
    staff = "staff"


class ChannelType(enum.StrEnum):
    webchat = "webchat"
    whatsapp = "whatsapp"
    sms = "sms"
    voice = "voice"
    instagram = "instagram"
    email = "email"


class ConversationStatus(enum.StrEnum):
    active = "active"   # AI is handling it
    human = "human"     # escalated / staff has taken over
    closed = "closed"


class MessageRole(enum.StrEnum):
    guest = "guest"
    assistant = "assistant"
    staff = "staff"
    system = "system"
    tool = "tool"


class ReservationStatus(enum.StrEnum):
    pending = "pending"       # drafted by the concierge, awaiting approval
    approved = "approved"     # staff approved
    confirmed = "confirmed"   # committed to the booking system
    cancelled = "cancelled"
    rejected = "rejected"


class ActionStatus(enum.StrEnum):
    proposed = "proposed"
    executed = "executed"
    failed = "failed"


class ApprovalStatus(enum.StrEnum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"


def pg_enum(enum_cls: type[enum.Enum], name: str) -> SAEnum:
    """VARCHAR-backed enum: stores the value, validates via a CHECK constraint."""
    return SAEnum(
        enum_cls,
        name=name,
        native_enum=False,
        length=32,
        values_callable=lambda e: [m.value for m in e],
    )
