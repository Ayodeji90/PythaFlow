"""Importing this package registers every model on `Base.metadata`, which is what
Alembic autogenerate and `create_all` rely on."""
from .action import Action, Approval
from .base import Base, TenantMixin, TimestampMixin, UUIDMixin
from .channel import Channel
from .conversation import Conversation, Message
from .guest import Guest
from .knowledge import KnowledgeChunk
from .reservation import Reservation
from .tenant import Tenant, User

__all__ = [
    "Base",
    "UUIDMixin",
    "TimestampMixin",
    "TenantMixin",
    "Tenant",
    "User",
    "Channel",
    "Guest",
    "Conversation",
    "Message",
    "Reservation",
    "Action",
    "Approval",
    "KnowledgeChunk",
]
