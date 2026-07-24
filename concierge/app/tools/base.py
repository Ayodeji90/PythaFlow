from __future__ import annotations

from abc import abstractmethod
from enum import Enum
from typing import Protocol, Any, Type
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession


class ToolKind(str, Enum):
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
    args_model: Type[BaseModel]
    kind: ToolKind

    @abstractmethod
    async def run(
        self, args: BaseModel, *, ctx: ToolContext, db: AsyncSession
    ) -> dict[str, Any]:
        ...