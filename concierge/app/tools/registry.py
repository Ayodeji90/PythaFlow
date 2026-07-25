from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import BaseModel

from ..llm.base import ToolDefinition
from .base import Tool, ToolContext, ToolKind


class Registry:
    def __init__(self):
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"Tool {tool.name} already registered")
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool:
        tool = self._tools.get(name)
        if not tool:
            raise ValueError(f"Unknown tool: {name}")
        return tool

    def all(self) -> dict[str, Tool]:
        return dict(self._tools)

    def schemas_for(self, tenant_id: UUID) -> list[dict[str, Any]]:
        """OpenAI-style tools[] -- only read_only + draft for LLM.

        fulfilment hidden -- safety gate.
        """
        return [
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.args_model.model_json_schema(),
                },
            }
            for tool in self._tools.values()
            if tool.kind in (ToolKind.read_only, ToolKind.draft)
        ]

    def definitions_for(self) -> list[ToolDefinition]:
        """ToolDefinition objects for the LLM layer -- only read_only + draft.

        fulfilment tools are hidden from the LLM.
        """
        return [
            ToolDefinition(
                name=tool.name,
                description=tool.description,
                parameters=tool.args_model.model_json_schema(),
            )
            for tool in self._tools.values()
            if tool.kind in (ToolKind.read_only, ToolKind.draft)
        ]

    def get_fulfilment(self, name: str) -> Tool:
        """Get a fulfilment tool by name (called by fulfilment worker, never LLM)."""
        tool = self._tools.get(name)
        if not tool:
            raise ValueError(f"Unknown tool: {name}")
        if tool.kind is not ToolKind.fulfilment:
            raise ValueError(f"Tool {name} is not a fulfilment tool")
        return tool


registry = Registry()