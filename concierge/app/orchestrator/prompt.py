"""Builds the system prompt from the tenant's own fields + retrieved knowledge.
This is where the concierge gets its voice *and* its facts."""
from __future__ import annotations

from ..models import Tenant

_BASE = (
    "You are the AI concierge for {name}, a hospitality business. "
    "You speak on behalf of the venue to its guests: warm, concise, and helpful. "
    "Answer as a knowledgeable member of the team would."
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


def build_system_prompt(tenant: Tenant, *, context: str | None = None) -> str:
    parts = [_BASE.format(name=tenant.name)]

    if tenant.brand_voice:
        parts.append(f"Brand voice to match: {tenant.brand_voice}")
    if tenant.timezone:
        parts.append(f"The venue's timezone is {tenant.timezone}.")
    if tenant.languages:
        langs = ", ".join(tenant.languages)
        parts.append(f"Reply in the guest's language when you can ({langs} supported).")

    parts.append(_GROUNDED.format(context=context) if context else _UNGROUNDED)
    parts.append("Keep replies to a few sentences.")
    return "\n\n".join(parts)
