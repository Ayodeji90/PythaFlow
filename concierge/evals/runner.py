#!/usr/bin/env python3
"""Eval harness runner — golden-dialogue test suite for the concierge.

Usage:

    # Run all dialogues in replay mode (default, deterministic, no API key needed)
    uv run python -m evals.runner

    # Run a single dialogue live (records new responses)
    uv run python -m evals.runner --live --dialogue 01_happy_path_booking

    # Run with baseline comparison
    uv run python -m evals.runner --baseline

    # Run in regression-detection mode (removes grounding instructions)
    uv run python -m evals.runner --break-grounding
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path
from typing import Any

import yaml

from .models import Dialogue, DialogueScore

logging.basicConfig(
    level=logging.WARNING,
    format="%(levelname)s  %(name)s  %(message)s",
)
log = logging.getLogger("evals.runner")

# ── Paths ────────────────────────────────────────────────────────────────

HERE = Path(__file__).resolve().parent
DIALOGUES_DIR = HERE / "dialogues"
RECORDINGS_DIR = HERE / "recordings"
BASELINE_PATH = HERE / "BASELINE.md"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="PythaFlow Concierge — eval harness runner",
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="Run against the real LLM and record responses (default: replay)",
    )
    parser.add_argument(
        "--dialogue",
        type=str,
        default=None,
        help="Run only the named dialogue (without .yaml extension)",
    )
    parser.add_argument(
        "--baseline",
        action="store_true",
        help="Compare results against committed baseline",
    )
    parser.add_argument(
        "--break-grounding",
        action="store_true",
        help="Remove grounding prompt instructions to verify regression detection",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output scorecard as JSON only (no human-readable table)",
    )
    return parser.parse_args()


# ── Main entry point ─────────────────────────────────────────────────────


async def main() -> int:
    args = _parse_args()

    # Discover dialogue files
    if args.dialogue:
        paths = [DIALOGUES_DIR / f"{args.dialogue}.yaml"]
    else:
        paths = sorted(DIALOGUES_DIR.glob("*.yaml"))

    if not paths:
        log.error("No dialogue files found in %s", DIALOGUES_DIR)
        return 1

    # Load baseline if requested
    baseline = _load_baseline() if args.baseline else None

    # Run each dialogue
    all_scores: dict[str, DialogueScore] = {}

    for yaml_path in paths:
        dialogue_name = yaml_path.stem
        log.info("Running dialogue: %s", dialogue_name)

        # Parse YAML
        dialogue = _parse_dialogue(yaml_path)

        # Load or prepare recording
        recording_path = RECORDINGS_DIR / f"{dialogue_name}.yaml"

        if args.live:
            score = await _run_live(dialogue, recording_path, break_grounding=args.break_grounding)
        else:
            if not recording_path.exists():
                log.error(
                    "No recording found at %s. Run with --live first to record responses.",
                    recording_path,
                )
                return 1
            score = await _run_replay(dialogue, recording_path)

        all_scores[dialogue_name] = score
        status = "✓" if score.score >= 0.5 else "✗"
        log.info("  %s %s: %.1f%%", status, dialogue_name, score.score * 100)

    # Build scorecard
    from .scoring import build_scorecard, format_scorecard

    scorecard = build_scorecard(all_scores, baseline=baseline)

    if args.json:
        print(json.dumps(scorecard.model_dump(), indent=2))
    else:
        print()
        print(format_scorecard(scorecard))
        print()

    # Save baseline if requested
    if args.baseline and not args.live:
        _save_baseline(scorecard.overall)
        log.info("Baseline saved: %.1f%%", scorecard.overall * 100)

    if scorecard.regression:
        log.warning(
            "REGRESSION: overall %.1f%% < baseline %.1f%%",
            scorecard.overall * 100,
            baseline * 100 if baseline else 0,
        )
        return 1

    return 0


# ── Per-dialogue runners ─────────────────────────────────────────────────


async def _run_live(
    dialogue: Dialogue,
    recording_path: Path,
    *,
    break_grounding: bool = False,
) -> DialogueScore:
    """Run a dialogue against the real LLM, recording responses."""
    from .recorder import RecordingProvider

    db, tenant_info = await _setup_db(dialogue.tenant_fixture)

    # Build real LLM service + real embedder (needed for retrieval in live mode)
    from app.config import get_settings
    from app.llm.embeddings import build_embedding_service
    from app.llm.factory import build_llm_service

    settings = get_settings()
    real_llm = build_llm_service(settings)
    recording_provider = RecordingProvider(real_llm._provider)

    from app.llm.service import LLMService

    recording_llm = LLMService(
        recording_provider,
        settings.LLM_MODEL_FAST,
        settings.LLM_MODEL_QUALITY,
        temperature=settings.LLM_TEMPERATURE,
        max_tokens=settings.LLM_MAX_TOKENS,
    )

    from app.orchestrator.engine import LLMOrchestrator

    orch = LLMOrchestrator(
        llm=recording_llm,
        tier=settings.CHAT_TIER,
        embedder=build_embedding_service(settings),
        _skip_extractor=True,
    )

    score = await _run_turns(dialogue, orch, db, break_grounding=break_grounding)

    # Save recording
    recording_provider.save_recording(recording_path)
    log.info("Recording saved to %s", recording_path)

    await _teardown_db(db)
    return score


async def _run_replay(dialogue: Dialogue, recording_path: Path) -> DialogueScore:
    """Run a dialogue using pre-recorded LLM responses."""
    from .recorder import FakeEmbedder, ReplayProvider

    replay_provider = ReplayProvider.load(recording_path)

    db, tenant_info = await _setup_db(dialogue.tenant_fixture)

    from app.config import get_settings
    from app.llm.service import LLMService

    settings = get_settings()
    replay_llm = LLMService(
        replay_provider,
        settings.LLM_MODEL_FAST,
        settings.LLM_MODEL_QUALITY,
        temperature=settings.LLM_TEMPERATURE,
        max_tokens=settings.LLM_MAX_TOKENS,
    )

    from app.orchestrator.engine import LLMOrchestrator

    orch = LLMOrchestrator(
        llm=replay_llm,
        tier=settings.CHAT_TIER,
        embedder=FakeEmbedder(),
        _skip_extractor=True,
    )

    score = await _run_turns(dialogue, orch, db, break_grounding=False)

    await _teardown_db(db)
    return score


async def _run_turns(
    dialogue: Dialogue,
    orch,
    db,
    *,
    break_grounding: bool = False,
) -> DialogueScore:
    """Execute all turns of a dialogue and return the scored result."""
    from uuid import uuid4

    from .scoring import check_turn, score_dialogue

    # All turns share one conversation ref so multi-turn state propagates
    conv_ref = uuid4().hex
    turns_data: list[dict] = []

    for i, turn in enumerate(dialogue.turns):
        log.debug("  Turn %d: %s", i, turn.guest)

        msg = _message_for_turn(turn, conv_ref=conv_ref)

        chunks, db_state = await _execute_turn(
            msg, orch, db, break_grounding=break_grounding
        )

        # Get last system prompt from the provider
        provider = orch._llm._provider
        last_system = getattr(provider, "last_system", None)

        checks, dims = await check_turn(
            turn.expect,
            chunks=chunks,
            last_system=last_system,
            db_state=db_state,
        )

        turns_data.append({
            "checks": checks,
            "dimensions": dims,
        })

    return score_dialogue(dialogue.name, turns_data)


# ── Turn execution ───────────────────────────────────────────────────────


async def _execute_turn(
    msg,
    orch,
    db,
    *,
    break_grounding: bool = False,
) -> tuple[list, dict[str, Any]]:
    """Run one guest turn through the orchestrator pipeline.

    Returns ``(chunks, db_state)`` where ``chunks`` is the list of yielded
    ``OutboundChunk`` objects and ``db_state`` is a dict of relevant DB state
    after the turn (request info, etc.).
    """
    from app.channels.base import handle_inbound

    chunks: list = []

    # The `handle_inbound` pipeline opens a transaction and commits. We let it
    # do so — our outer transaction uses savepoint mode so the test fixture
    # (or in this case the eval session) rolls back cleanly afterwards.
    async for chunk in handle_inbound(
        msg, db=db, redis=None, orchestrator=orch,
    ):
        chunks.append(chunk)

    # Gather DB state after the turn
    db_state = await _gather_db_state(db)

    return chunks, db_state


async def _gather_db_state(db) -> dict[str, Any]:
    """Inspect the DB for relevant state after a turn."""
    from sqlalchemy import select

    from app.models import Request

    state: dict[str, Any] = {}

    requests = (
        (await db.execute(select(Request).limit(5))).scalars().all()
    )
    if requests:
        latest = requests[-1]
        req_type = latest.type
        state["request_type"] = (
            req_type.value if hasattr(req_type, "value") else str(req_type)
        )
        req_status = latest.status
        state["request_status"] = (
            req_status.value if hasattr(req_status, "value") else str(req_status)
        )
        state["request_count"] = len(requests)

    return state


# ── Fixture setup / teardown ─────────────────────────────────────────────


async def _setup_db(fixture_name: str) -> tuple[Any, dict]:
    """Set up a DB session with fixture data.

    Returns ``(session, tenant_info)``.
    """
    from sqlalchemy.pool import NullPool

    from app.config import get_settings
    from app.db import async_sessionmaker, create_async_engine

    from .fixtures import load_fixture

    engine = create_async_engine(
        get_settings().DATABASE_URL,
        poolclass=NullPool,
    )
    conn = await engine.connect()
    trans = await conn.begin()
    maker = async_sessionmaker(
        bind=conn,
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    )
    session = maker()

    # Store engine/conn for teardown
    session._eval_engine = engine
    session._eval_conn = conn
    session._eval_trans = trans

    tenant_info = await load_fixture(session, fixture_name)
    return session, tenant_info


async def _teardown_db(session) -> None:
    """Roll back the fixture transaction and close connections."""
    conn = getattr(session, "_eval_conn", None)
    engine = getattr(session, "_eval_engine", None)
    await session.close()
    if conn:
        await conn.rollback()
        await conn.close()
    if engine:
        await engine.dispose()


# ── Helpers ──────────────────────────────────────────────────────────────


def _parse_dialogue(yaml_path: Path) -> Dialogue:
    """Parse a dialogue YAML file."""
    with open(yaml_path) as f:
        data = yaml.safe_load(f)
    return Dialogue(**data)


def _message_for_turn(turn, *, conv_ref: str) -> Any:
    """Create an InboundMessage for a guest turn using the shared conversation ref."""
    from app.channels.webchat import WebChatAdapter

    return WebChatAdapter.to_inbound(
        tenant_slug="demo-bistro-eval",
        conversation_ref=conv_ref,
        content=turn.guest,
    )


def _load_baseline() -> float:
    """Read baseline from BASELINE.md."""
    if not BASELINE_PATH.exists():
        log.warning("No BASELINE.md found at %s", BASELINE_PATH)
        return None
    text = BASELINE_PATH.read_text()
    for line in text.splitlines():
        if line.startswith("baseline:"):
            try:
                return float(line.split(":")[1].strip().strip("%")) / 100.0
            except (ValueError, IndexError):
                pass
    return None


def _save_baseline(overall: float) -> None:
    """Write or update BASELINE.md."""
    BASELINE_PATH.write_text(
        f"# Eval Baseline\n\n"
        f"Recorded: {__import__('datetime').datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n"
        f"baseline: {overall:.1%}\n\n"
        f"## Notes\n\n"
        f"Run `uv run python -m evals.runner --baseline` to verify against this baseline.\n"
        f"Regenerate with `uv run python -m evals.runner --live` first.\n"
    )


# ── CLI entry point ──────────────────────────────────────────────────────

if __name__ == "__main__":
    sys.exit(asyncio.run(main()))