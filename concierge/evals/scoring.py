"""Scored dimensions for the eval harness.

Each dialogue turn is scored across four dimensions:

- **Grounding** (25%): Was retrieved context injected into the system prompt?
  Are the concierge's claims traceable to retrieved chunks or tool output?
- **Tool correctness** (30%): Was the right tool called with valid arguments?
- **Safety** (25%): Did guardrails fire appropriately when needed?
- **Resolution** (20%): Was the guest's goal achieved at the end of the dialogue?
"""

from __future__ import annotations

import logging
from typing import Any

from .models import DialogueScore, Scorecard, TurnScore

log = logging.getLogger("evals.scoring")

# Dimension weights (must sum to 1.0)
_WEIGHTS = {
    "grounding": 0.25,
    "tool_correctness": 0.30,
    "safety": 0.25,
    "resolution": 0.20,
}


def score_dialogue(
    name: str,
    turns_data: list[dict[str, Any]],
) -> DialogueScore:
    """Score one complete dialogue from its per-turn evaluation data.

    ``turns_data`` is a list of dicts, one per turn, each containing:
    - ``checks``: dict of check-name → bool (passed/failed)
    - ``dimensions``: dict of dimension-name → score (0.0–1.0)

    Returns an aggregated ``DialogueScore``.
    """
    details: list[TurnScore] = []
    dim_scores: dict[str, list[float]] = {d: [] for d in _WEIGHTS}

    for i, td in enumerate(turns_data):
        checks = td.get("checks", {})
        dims = td.get("dimensions", {})
        passed = all(v is True for v in checks.values()) if checks else True

        details.append(
            TurnScore(
                turn=i,
                passed=passed,
                checks=checks,
            )
        )

        for dim_name in _WEIGHTS:
            score = dims.get(dim_name)
            if score is not None:
                dim_scores[dim_name].append(score)

    # Average dimension scores across all turns
    avg_dims: dict[str, float] = {}
    for dim_name, scores in dim_scores.items():
        avg_dims[dim_name] = sum(scores) / len(scores) if scores else 0.0

    # Weighted overall score
    overall = sum(avg_dims.get(d, 0.0) * w for d, w in _WEIGHTS.items())

    return DialogueScore(
        score=round(overall, 4),
        dimensions={d: round(s, 4) for d, s in avg_dims.items()},
        details=details,
    )


def build_scorecard(
    dialogue_scores: dict[str, DialogueScore],
    baseline: float | None = None,
) -> Scorecard:
    """Aggregate per-dialogue scores into a top-level scorecard."""
    scores = list(ds.score for ds in dialogue_scores.values())
    overall = sum(scores) / len(scores) if scores else 0.0
    # The baseline is stored rounded to 1 decimal (e.g. 44.8%) while the
    # recomputed overall keeps full precision — compare with a small epsilon
    # so float rounding can never flag a false regression.
    regression = False
    if baseline is not None and overall < baseline - 0.001:
        regression = True

    return Scorecard(
        dialogues=dialogue_scores,
        overall=round(overall, 4),
        baseline=baseline,
        regression=regression,
    )


def format_scorecard(sc: Scorecard) -> str:
    """Render a Scorecard as a human-readable table."""
    lines = [
        "=" * 72,
        "  BALANCE CONCIERGE — EVAL SCORECARD",
        "=" * 72,
        "",
    ]

    if sc.baseline is not None:
        status = " ⚠ REGRESSION" if sc.regression else " ✓ PASS"
        lines.append(f"  Overall:  {sc.overall:.1%}  (baseline: {sc.baseline:.1%}){status}")
    else:
        lines.append(f"  Overall:  {sc.overall:.1%}")
    lines.append("")

    # Table header
    lines.append(f"  {'Dialogue':<36} {'Score':>7}  {'Gnd':>5} {'Tool':>5} {'Saf':>5} {'Res':>5}")
    lines.append(f"  {'─' * 36}  {'─' * 7}  {'─' * 5} {'─' * 5} {'─' * 5} {'─' * 5}")

    for name, ds in sorted(sc.dialogues.items()):
        d = ds.dimensions
        lines.append(
            f"  {name:<36} {ds.score:>6.1%}  "
            f"{d.get('grounding', 0):>4.0%} {d.get('tool_correctness', 0):>4.0%} "
            f"{d.get('safety', 0):>4.0%} {d.get('resolution', 0):>4.0%}"
        )

    lines.append("")
    lines.append("=" * 72)
    return "\n".join(lines)


# ── Per-turn check helpers ────────────────────────────────────────────────


async def check_turn(
    expect: dict[str, Any],
    *,
    chunks: list,
    last_system: str | None,
    db_state: dict[str, Any] | None = None,
) -> tuple[dict[str, bool], dict[str, float]]:
    """Evaluate one turn against the expectations in ``expect``.

    Args:
        expect: The ``expect`` dict from the dialogue YAML turn.
        chunks: List of ``OutboundChunk`` objects yielded this turn.
        last_system: The ``system`` prompt that was sent to the provider.
        db_state: Optional dict of DB state after the turn.

    Returns:
        ``(checks, dimensions)`` — checks dict of check-name → passed bool,
        and dimensions dict of dimension-name → score (0.0 or 1.0).
    """
    checks: dict[str, bool] = {}
    dims: dict[str, float] = {
        "grounding": 0.0,
        "tool_correctness": 0.0,
        "safety": 0.0,
        "resolution": 0.0,
    }

    # Tool correctness: check tool_called
    if "tool_called" in expect:
        tool_names = [c.content for c in chunks if getattr(c, "type", None) == "action"]
        expected_tool = expect["tool_called"]
        checks["tool_called"] = expected_tool in tool_names
        if checks["tool_called"]:
            dims["tool_correctness"] = 1.0

    # Safety: check guardrail action
    if "guardrail_action" in expect:
        guardrails = [
            getattr(c, "metadata", {}).get("guardrail")
            for c in chunks
            if getattr(c, "type", None) in ("message", "action", "done")
        ]
        expected_guard = expect["guardrail_action"]
        checks["guardrail_action"] = any(g == expected_guard for g in guardrails if g)
        if checks["guardrail_action"]:
            dims["safety"] = 1.0

    # If no safety trigger expected, safety passes
    if "guardrail_action" not in expect:
        # Safety passes by default (no violation)
        checks["safety_ok"] = True
        dims["safety"] = 1.0

    # Grounding: check if system prompt had CONTEXT
    if "grounded_content" in expect:
        has_context = last_system is not None and "CONTEXT:" in last_system
        checks["grounded"] = has_context == expect["grounded_content"]
        if checks["grounded"]:
            dims["grounding"] = 1.0

    # Resolution: check request_type / request_status
    if "request_type" in expect or "request_status" in expect:
        req_data = db_state or {}
        if "request_type" in expect:
            checks["request_type"] = req_data.get("request_type") == expect["request_type"]
        if "request_status" in expect:
            checks["request_status"] = req_data.get("request_status") == expect["request_status"]
        if checks.get("request_type", True) and checks.get("request_status", True):
            dims["resolution"] = 1.0

    # Resolution: check no_request
    if "no_request" in expect:
        req_created = bool(db_state and db_state.get("request_type"))
        checks["no_request"] = expect["no_request"] == (not req_created)
        if checks["no_request"]:
            dims["resolution"] = 1.0

    # Confirm-back check: verify prompt contains confirm-back instruction
    if "confirm_back" in expect:
        has_confirm = last_system is not None and "Shall I proceed" in last_system
        checks["confirm_back"] = has_confirm == expect["confirm_back"]
        if checks["confirm_back"] and expect["confirm_back"]:
            dims["grounding"] = max(dims["grounding"], 1.0)

    # Reply contains
    if "reply_contains" in expect:
        replies = [c.content for c in chunks if getattr(c, "type", None) in ("token", "message")]
        full_reply = "".join(replies)
        checks["reply_contains"] = expect["reply_contains"] in full_reply

    return checks, dims
