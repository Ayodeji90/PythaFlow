"""Builds the system prompt from the tenant's own fields + retrieved knowledge.
This is where the concierge gets its voice *and* its facts."""
from __future__ import annotations

from ..models import Tenant

_BASE = (
    "You are the AI concierge for {name}, a hospitality business. "
    "You speak on behalf of the venue to its guests: warm, concise, and helpful. "
    "Answer as a knowledgeable member of the team would."
)

# Day 14: instruct the model to resolve relative dates into concrete ISO dates.
_DATE_RESOLUTION = (
    "When a guest uses a relative date or time ('this Friday', 'tomorrow', "
    "'next week', 'tonight'), resolve it to an exact date based on today's real "
    "date before calling any tool. The current real date is 2026-07-28 (Tuesday). "
    "For example, 'this Friday' = 2026-07-31, 'tomorrow' = 2026-07-29, "
    "'next Monday' = 2026-08-03. Always pass YYYY-MM-DD and HH:MM format to tools."
)

# When we DID retrieve relevant facts.
_GROUNDED = (
    "Answer using ONLY the facts in CONTEXT below. Do not use outside knowledge or "
    "guess. If the answer is not in CONTEXT, say you'll confirm with the team rather "
    "than inventing details. Never cite the context numbers or say 'the context' — "
    "just answer naturally.\n\nCONTEXT:\n{context}"
)

# When retrieval found nothing relevant (the similarity floor rejected everything).
_UNGROUNDED = (
    "You do NOT have the venue's specific facts for this question (menu, hours, "
    "prices, policies, availability). Do not invent any specifics. Warmly say you'll "
    "check with the team and offer to help another way. Keep it to a sentence or two."
)

# Day 12: multi-turn robustness — corrections, confirmations, empathy.
_MULTI_TURN = (
    "When a guest corrects themselves mid-conversation (e.g. 'actually 4 people' "
    "after saying 3, or 'make it 7pm instead'), treat it as an update to the "
    "current pending request if one exists. Do not ask them to start over. "
    "Acknowledge the change naturally and confirm what the current booking details "
    "are after each correction.\n\n"
    "If a guest's request is ambiguous (e.g. 'book a table for Friday' without "
    "specifying time or party size), ask targeted follow-up questions one at a time "
    "rather than listing everything at once.\n\n"
    "Before calling any draft_* tool, explicitly confirm the key details "
    "with the guest and ask for their confirmation. Summarise what you're about to "
    "submit for staff review and ask 'Shall I proceed?' before calling the tool.\n\n"
    "Track booking details (date, time, party_size, area, notes) across the "
    "conversation. If a guest says 'actually 3 people' after you detailed a 4-person "
    "draft, treat it as a correction to the in-progress booking — do not create a "
    "new draft until you've confirmed the full updated set of details."
)


def build_slot_context(state: dict | None) -> str | None:
    """Build a slot-context snippet from Conversation.state for the system prompt.

    Returns a short string like 'In-progress booking: Table for 4 on 2026-07-28 at 19:00 (terrace)'
    or None if no booking slot data is present.
    """
    if not state:
        return None
    date = state.get("date")
    time = state.get("time")
    party_size = state.get("party_size")
    area = state.get("area")
    if not (date and time and party_size):
        return None
    parts = [f"In-progress booking: Table for {party_size} on {date} at {time}"]
    if area:
        parts[-1] += f" ({area})"
    return "\n".join(parts)


def build_system_prompt(
    tenant: Tenant,
    *,
    context: str | None = None,
    guest_context: str | None = None,
    state: dict | None = None,
) -> str:
    parts = [_BASE.format(name=tenant.name)]

    if tenant.brand_voice:
        parts.append(f"Brand voice to match: {tenant.brand_voice}")
    if tenant.timezone:
        parts.append(f"The venue's timezone is {tenant.timezone}.")
    if tenant.languages:
        langs = ", ".join(tenant.languages)
        parts.append(f"Reply in the guest's language when you can ({langs} supported).")

    if guest_context:
        parts.append(guest_context)

    # Day 12: inject current booking slot state, if any.
    slot_context = build_slot_context(state)
    if slot_context:
        parts.append(slot_context)

    parts.append(_GROUNDED.format(context=context) if context else _UNGROUNDED)
    parts.append(_DATE_RESOLUTION)
    parts.append(_MULTI_TURN)
    parts.append("Keep replies to a few sentences.")
    return "\n\n".join(parts)