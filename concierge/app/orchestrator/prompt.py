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
def _build_date_resolution(tenant: Tenant) -> str:
    from ..utils import venue_now

    now = venue_now(tenant.timezone)
    today_weekday = now.strftime("%A")

    return (
        "When a guest uses a relative date or time (e.g. 'this Friday', "
        "'tomorrow', 'next week', 'tonight'), resolve it to the exact date in "
        "the venue's timezone before calling any tool. For example, if today is "
        f"{today_weekday.lower()} {now.strftime('%B %d')}, "
        "'this Friday' resolves to next Friday in that timezone. Always pass "
        "YYYY-MM-DD and HH:MM format to tools."
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


def build_post_draft_message(tenant: Tenant, request_type: str = "reservation") -> str:
    """Build the post-draft confirmation message using the tenant's voice.

    D3 fix: replaces the hardcoded message with a brand-voiced one.
    Falls back to a sensible default when voice_config is not set.
    """
    vc = tenant.voice_config or {}
    template = vc.get("post_draft_message")
    if template:
        return template.format(
            name=tenant.name,
            type=request_type,
        )

    # Default messages by tone
    tone = vc.get("tone", "professional")
    defaults = {
        "professional": (
            f"I've sent your {request_type} request to our team for review. "
            "They'll confirm your booking shortly!"
        ),
        "casual": (
            f"All set! I've sent your {request_type} request to the team at {tenant.name}. "
            "They'll get back to you shortly!"
        ),
        "playful": (
            f"Awesome! Your {request_type} request is on its way to the {tenant.name} team. "
            "Sit tight — they'll confirm soon!"
        ),
        "formal": (
            f"Your {request_type} request has been submitted to the {tenant.name} team for review. "
            "A staff member will confirm your booking shortly."
        ),
    }
    return defaults.get(tone, defaults["professional"])


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


def _build_voice_section(tenant: Tenant, channel: str | None = None) -> str | None:
    """Build the voice/persona section from structured voice_config (D2).

    Falls back to the legacy brand_voice text when voice_config is empty.
    voice_config schema:
        tone: str          — "formal", "casual", "playful", "professional"
        do: list[str]      — things the concierge should do
        dont: list[str]    — things the concierge should NOT do
        length_by_channel: dict — e.g. {"whatsapp": "2 sentences", "webchat": "3 sentences"}
        greeting: str       — custom greeting for first message
        fallback: str       — what to say when it doesn't know
    """
    vc = tenant.voice_config or {}
    if not vc:
        # Legacy: plain text brand_voice
        if tenant.brand_voice:
            return f"Brand voice to match: {tenant.brand_voice}"
        return None

    lines = ["Brand voice rules:"]

    tone = vc.get("tone")
    if tone:
        lines.append(f"  Tone: {tone}")

    do_items = vc.get("do", [])
    if do_items:
        lines.append("  Always:")
        for item in do_items:
            lines.append(f"    - {item}")

    dont_items = vc.get("dont", [])
    if dont_items:
        lines.append("  Never:")
        for item in dont_items:
            lines.append(f"    - {item}")

    length = vc.get("length_by_channel", {})
    if channel and channel in length:
        lines.append(f"  Response length for {channel}: {length[channel]}")
    elif length:
        default_len = length.get("default", length.get("webchat", "a few sentences"))
        lines.append(f"  Response length: {default_len}")

    greeting = vc.get("greeting")
    if greeting:
        lines.append(f"  Greeting: {greeting}")

    fallback = vc.get("fallback")
    if fallback:
        lines.append(f"  When you don't know: {fallback}")

    # Also include legacy brand_voice if present alongside structured config
    if tenant.brand_voice:
        lines.append(f"  Additional notes: {tenant.brand_voice}")

    return "\n".join(lines) if len(lines) > 1 else None


def build_system_prompt(
    tenant: Tenant,
    *,
    context: str | None = None,
    guest_context: str | None = None,
    state: dict | None = None,
    channel: str | None = None,
) -> str:
    parts = [_BASE.format(name=tenant.name)]

    # D2: structured voice config takes precedence over plain text brand_voice
    voice_section = _build_voice_section(tenant, channel=channel)
    if voice_section:
        parts.append(voice_section)

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
    parts.append(_build_date_resolution(tenant))
    parts.append(_MULTI_TURN)
    parts.append("Keep replies to a few sentences.")
    return "\n\n".join(parts)