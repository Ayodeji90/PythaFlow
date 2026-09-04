"""API schemas for the approval flow: what the staff dashboard sends and receives."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class DecideRequest(BaseModel):
    request_id: UUID
    decision: str = Field(pattern=r"^(approved|rejected)$")
    note: str | None = None


class DecideResponse(BaseModel):
    request_id: UUID
    decision: str
    status: str


class ApprovalQueueItem(BaseModel):
    request_id: UUID
    type: str
    summary: str | None = None
    confidence: float | None = None
    priority: str
    status: str
    created_at: datetime
    conversation_id: UUID | None = None


class ApprovalQueueResponse(BaseModel):
    requests: list[ApprovalQueueItem]
    total: int
