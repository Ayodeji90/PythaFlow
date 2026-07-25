from __future__ import annotations

import enum
from abc import abstractmethod
from typing import Any, Protocol
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession


class ToolKind(enum.StrEnum):
    read_only = "read_only"
    draft = "draft"
    fulfilment = "fulfilment"


class ToolContext(BaseModel):
    tenant_id: UUID
    conversation_id: UUID
    guest_id: UUID | None = None


class Tool(Protocol):
    name: str
    description: str
    args_model: type[BaseModel]
    kind: ToolKind

    @abstractmethod
    async def run(
        self, args: BaseModel, *, ctx: ToolContext, db: AsyncSession
    ) -> dict[str, Any]:
        ...