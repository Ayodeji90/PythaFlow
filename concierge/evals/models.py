"""Pydantic models for golden-dialogue YAML schema.

Each YAML file in ``evals/dialogues/`` describes one dialogue scenario: a sequence
of guest turns and the expectations for each turn (tool called, guardrail action,
DB state after processing).
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class DialogueTurn(BaseModel):
    """One guest message in the dialogue and what we expect from the concierge.

    The ``expect`` dict is intentionally flexible — per scenario it checks
    different things:

    - ``tool_called`` — name of the tool the LLM should invoke this turn
    - ``confirm_back`` — whether the system prompt requested confirmation
    - ``request_type`` — expected Request.type if one is created
    - ``request_status`` — expected Request.status
    - ``reservation_created`` — whether a Reservation row exists
    - ``guardrail_action`` — expected guardrail action (refuse, escalate)
    - ``grounded_content`` — whether CONTEXT was in the system prompt
    - ``reply_contains`` — expected substring in the concierge's reply
    - ``no_request`` — expect NO Request to be created
    """

    guest: str
    expect: dict[str, Any]


class Dialogue(BaseModel):
    """A single eval dialogue — golden sequence of guest turns."""

    name: str
    tenant_fixture: str
    turns: list[DialogueTurn]


class TurnScore(BaseModel):
    """Score for one turn in a dialogue."""

    turn: int
    passed: bool
    checks: dict[str, bool | float]


class DialogueScore(BaseModel):
    """Aggregated score for one complete dialogue."""

    score: float
    dimensions: dict[str, float]
    details: list[TurnScore]


class Scorecard(BaseModel):
    """Top-level scorecard for the whole eval run."""

    dialogues: dict[str, DialogueScore]
    overall: float
    baseline: float | None = None
    regression: bool | None = None