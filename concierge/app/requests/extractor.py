"""Request extractor: post-turn LLM classifier for unhandled intents."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from ..config import get_settings
from ..llm.base import LLMMessage
from ..llm.service import LLMService
from ..models.enums import RequestPriority, RequestType


async def extract_request(
    llm: LLMService,
    *,
    tenant_id: UUID,
    conversation_id: UUID,
    guest_id: UUID | None,
    turns: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Run a fast-tier LLM to classify the latest exchange into a Request.

    Returns a dict with keys:
        type: RequestType
        summary: str (one line for staff queue)
        payload: dict (structured data for fulfilment)
        confidence: float (0-1)
        priority: RequestPriority

    Returns None if the exchange is a pure FAQ already answered by the KB
    (type == "none"). The caller should not create a Request in that case.

    If the exchange cannot be classified with confidence, type is set to
    "other" and confidence < 0.5.
    """
    settings = get_settings()
    if not settings.REQUEST_EXTRACTOR_ENABLED:
        return None

    # Build a short prompt: last user + assistant turn (if any)
    # We assume the orchestrator already persisted the guest turn and the
    # assistant turn; we read them back from turns (simpler than hitting DB).
    # Each turn: {role: "guest"|"assistant", content: str}
    user_turn = turns[-2] if len(turns) >= 2 else {"role": "guest", "content": ""}
    assistant_turn = turns[-1] if len(turns) >= 1 else {"role": "assistant", "content": ""}

    user_content = user_turn.get("content", "")
    assistant_content = assistant_turn.get("content", "")

    # If the assistant already said something that looks like a tool confirmation,
    # we might skip extraction? The spec says: runs after the assistant turn is
    # streamed, never blocking the guest's reply. If the turn already produced a
    # Request via a draft_* tool, it does nothing. We'll leave that check to the
    # orchestrator (look for Request already created in this turn).

    prompt = (
        "Classify the guest's last message into a structured work request for the venue staff. "
        "Use the conversation context if needed. Return ONLY a JSON object "
        "with the following keys: "
        "type (one of: reservation, modification, cancellation, order, "
        "enquiry, complaint, callback, other, none), "
        "summary (a single line staff will read in the queue), "
        "payload (JSON object with the structured data needed to fulfil the request), "
        "confidence (float between 0 and 1), "
        "priority (either \"normal\" or \"high\")). "
        "\n\nGuest message: \"\"\""
        + user_content
        + "\"\"\"\n\nAssistant response: \"\"\""
        + assistant_content
        + "\"\"\"\n\nJSON:"
    )

    # Call the LLM with fast tier, low temperature for deterministic classification
    result = await llm.generate(
        messages=[LLMMessage(role="user", content=prompt)],
        tier=settings.REQUEST_EXTRACTOR_TIER,
        temperature=0.0,
        max_tokens=512,
    )

    # Try to parse JSON from the LLM output
    import json
    import re

    # Find the first {...} block
    match = re.search(r"\{.*\}", result, re.DOTALL)
    if not match:
        # If no JSON, treat as unclassifiable
        extracted = {
            "type": RequestType.other,
            "summary": "Unclassifiable request",
            "payload": {},
            "confidence": 0.0,
            "priority": RequestPriority.normal,
        }
    else:
        try:
            data = json.loads(match.group(0))
            # Validate and coerce types
            req_type = RequestType(data.get("type", "other"))
            summary = str(data.get("summary", "")).strip()[:255]
            payload = data.get("payload", {}) if isinstance(data.get("payload"), dict) else {}
            confidence = float(data.get("confidence", 0.0))
            # Clamp confidence
            confidence = max(0.0, min(1.0, confidence))
            priority_str = data.get("priority", "normal")
            priority = (
                RequestPriority.high
                if priority_str == "high"
                else RequestPriority.normal
            )
            extracted = {
                "type": req_type,
                "summary": summary,
                "payload": payload,
                "confidence": confidence,
                "priority": priority,
            }
        except (json.JSONDecodeError, ValueError, KeyError):
            # If parsing fails, treat as unclassifiable
            extracted = {
                "type": RequestType.other,
                "summary": "Failed to parse extraction",
                "payload": {},
                "confidence": 0.0,
                "priority": RequestPriority.normal,
            }

    # If the extractor says "none", the KB already answered -> no Request
    if extracted["type"] == "none":
        return None

    return extracted