"""Notification/stub tool: sends a confirmation or reminder message to a guest.

This is a fulfilment tool (hidden from the LLM) invoked after staff approval to
notify the guest that their booking was confirmed/modified/cancelled. For now
the actual delivery is a log + notify() call; later it can dispatch via SMS,
email, or WhatsApp.
"""

from __future__ import annotations

import logging

from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ..notifications import NOTIF_MESSAGE_SENT, notify
from .base import ToolContext, ToolKind

log = logging.getLogger("concierge.tools.send_message")


class SendMessageArgs(BaseModel):
    recipient_id: str = Field(description="Guest ID or phone/email to send to")
    subject: str = Field(description="Type: confirmation, reminder, cancel_notification")
    message: str = Field(description="Message content to deliver")
    channel_type: str = Field(default="webchat", description="Delivery channel")


class SendMessageTool:
    name = "send_message"
    description = "Send a confirmation/reminder notification to a guest"
    args_model: type[BaseModel] = SendMessageArgs
    kind = ToolKind.fulfilment

    async def run(self, args: SendMessageArgs, *, ctx: ToolContext, db: AsyncSession) -> dict:
        log.info(
            "Notification: [%s] to %s via %s: %s",
            args.subject,
            args.recipient_id,
            args.channel_type,
            args.message[:120],
        )
        await notify(
            NOTIF_MESSAGE_SENT,
            tenant_id=ctx.tenant_id,
            request_id=None,
            payload={
                "recipient_id": args.recipient_id,
                "subject": args.subject,
                "message": args.message,
                "channel_type": args.channel_type,
            },
        )
        return {"status": "logged", "subject": args.subject, "recipient_id": args.recipient_id}


send_message = SendMessageTool()
