"""Tool-calling loop — the bridge between LLM-generated tool calls and the
concrete tools registered in the registry.

The loop runs up to MAX_STEPS turns, each time:
1. Asking the LLM to respond (possibly with tool calls)
2. Executing any tool calls the LLM made
3. Feeding the results back as tool-role messages
4. Yielding the final natural-language answer when the LLM stops calling tools
"""
from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..llm.base import LLMMessage, LLMToolResult, ToolDefinition
from ..llm.service import LLMService
from ..models.enums import ActionStatus
from ..schemas.message import OutboundChunk
from ..tools.logging import log_action
from ..tools.registry import registry
from .base import TurnContext

log = logging.getLogger("concierge.orchestrator.tools_loop")


async def run_tool_loop(
    llm: LLMService,
    history: list[LLMMessage],
    *,
    system: str,
    ctx: TurnContext,
    db: AsyncSession,
    tier: str = "quality",
) -> AsyncIterator[OutboundChunk]:
    """Run the tool-calling loop.

    Yields OutboundChunk items:
    - ``type="action"``  for each tool call the LLM makes
    - ``type="token"``   for the final natural-language answer

    If the LLM never calls a tool, yields the answer directly (same as a plain
    LLM.generate call).
    """
    settings = get_settings()
    tools: list[ToolDefinition] = registry.definitions_for()
    max_steps = settings.TOOLS_MAX_STEPS

    for _step in range(max_steps):
        result: LLMToolResult = await llm.generate_with_tools(
            history,
            tools=tools,
            tier=tier,
            system=system,
        )

        if not result.tool_calls:
            # LLM chose to respond in plain text — yield tokens and we're done
            if result.text:
                yield OutboundChunk(type="token", content=result.text)
            return

        # --- Execute each tool call the LLM made ---
        for call in result.tool_calls:
            yield OutboundChunk(type="action", content=call.name)

            try:
                tool = registry.get(call.name)
                args = tool.args_model.model_validate(call.arguments)
                output = await tool.run(
                    args,
                    ctx=ctx.to_tool_context(),
                    db=db,
                )
                await log_action(
                    db,
                    tenant_id=ctx.tenant.id,
                    conversation_id=ctx.conversation.id,
                    type=call.name,
                    input=call.arguments,
                    output=output,
                    status=ActionStatus.executed,
                )
                history.append(
                    LLMMessage(role="tool", content=json.dumps(output, default=str))
                )
            except Exception as exc:  # noqa: BLE001 — surface tool errors gracefully
                log.warning("Tool %s failed: %s", call.name, exc)
                await log_action(
                    db,
                    tenant_id=ctx.tenant.id,
                    conversation_id=ctx.conversation.id,
                    type=call.name,
                    input=call.arguments,
                    output={"error": str(exc)},
                    status=ActionStatus.failed,
                )
                history.append(
                    LLMMessage(
                        role="tool",
                        content=json.dumps({"error": str(exc)}),
                    )
                )

    # Max steps exhausted without a plain-text response
    yield OutboundChunk(
        type="message",
        content="I need a moment to think — one of my tools is taking longer than expected.",
    )