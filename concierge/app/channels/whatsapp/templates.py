"""Approved outbound templates (Day 16).

Meta requires every proactive outbound message outside the 24h service window
to use an **approved** template. This module is the ops registry: template
name → ordered variables, matching the ``{{1}}``, ``{{2}}`` placeholders, so
the transport fills them in the right order.

**Ops action (started Day 16, lead time = days):** submit these templates in
the BSP dashboard (360dialog / Twilio / Meta Business) exactly as specified —
see ``docs/whatsapp_templates.md``. Until one is approved, an out-of-window
send of that intent is a loud error, never a silent drop (enforced by
``window.choose_send_mode``).
"""
from __future__ import annotations

from dataclasses import dataclass

# Explicitly registered here so the transport never invents a template name.
APPROVED_TEMPLATES = frozenset(
    {"booking_confirmed", "booking_reminder", "booking_updated"}
)


@dataclass(frozen=True)
class TemplateSpec:
    name: str
    # Ordered variable names — the order a BSP fills the {{1}}, {{2}} body
    # placeholders. Changing this order breaks every live template.
    variables: tuple[str, ...]


# name → spec. The transport builds variables only from spec.variables.
TEMPLATES: dict[str, TemplateSpec] = {
    "booking_confirmed": TemplateSpec(
        name="booking_confirmed", variables=("party_size", "date", "time", "area")
    ),
    "booking_reminder": TemplateSpec(
        name="booking_reminder", variables=("party_size", "date", "time", "area")
    ),
    "booking_updated": TemplateSpec(
        name="booking_updated", variables=("party_size", "date", "time", "area")
    ),
}

# Which notification intent maps to which template.
INTENT_TO_TEMPLATE = {
    "confirmation": "booking_confirmed",
    "reminder": "booking_reminder",
    "update": "booking_updated",
}


def resolve_template_name(
    payload: dict,
    *,
    defaults: dict[str, str] | None = None,
) -> str | None:
    """Map a notify() payload to an approved template name, if any.

    Precedence: an explicit ``payload["template"]`` wins; otherwise the
    payload's ``subject`` is mapped through ``defaults`` (per-tenant names,
    e.g. from settings) and then ``INTENT_TO_TEMPLATE``. Returns None when the
    payload names no template intent.
    """
    explicit = payload.get("template")
    if explicit:
        name = str(explicit)
        return name if name in APPROVED_TEMPLATES else None
    subject = payload.get("subject")
    if not subject:
        return None
    if defaults and subject in defaults:
        return defaults[subject]
    return INTENT_TO_TEMPLATE.get(subject)
