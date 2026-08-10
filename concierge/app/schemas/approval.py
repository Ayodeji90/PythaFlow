"""API schemas for the approval flow: what the staff dashboard sends and receives."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, model_validator


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
    # Day 18: channel badge + guest name so the console renders the queue
    # exactly like the Week-2 designer mock; payload so edit-before-approve
    # can prefill the form.
    channel_type: str | None = None
    guest_name: str | None = None
    payload: dict = Field(default_factory=dict)


class ApprovalQueueResponse(BaseModel):
    requests: list[ApprovalQueueItem]
    total: int


class EditRequest(BaseModel):
    """Edit-before-approve: staff fix what the AI misheard."""

    date: str | None = Field(None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    time: str | None = Field(None, pattern=r"^\d{2}:\d{2}$")
    party_size: int | None = Field(None, ge=1, le=50)
    area: str | None = None
    notes: str | None = None

    @model_validator(mode="after")
    def _at_least_one_change(self) -> EditRequest:
        if not any((self.date, self.time, self.party_size, self.area, self.notes)):
            raise ValueError("provide at least one field to edit")
        return self


class EditResponse(BaseModel):
    request_id: UUID
    summary: str
    payload: dict
    edited_at: datetime