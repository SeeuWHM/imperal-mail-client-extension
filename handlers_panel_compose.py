"""Mail Client · Compose send handler for panel."""
from __future__ import annotations

import logging

from pydantic import BaseModel, Field

from app import chat, ActionResult, _get_acc, _no_account_error

log = logging.getLogger(__name__)


class ComposeSendParams(BaseModel):
    """Parameters for compose send from panel."""
    mode: str = Field(default="new", description="reply, forward, or new")
    message_id: str = Field(default="", description="Original message ID for reply/forward")
    to: str = Field(default="", description="Recipient email")
    subject: str = Field(default="", description="Email subject")
    body: str = Field(default="", description="Email body")
    cc: str = Field(default="", description="CC recipients")
    bcc: str = Field(default="", description="BCC recipients")
    account: str = Field(default="", description="Send from this account")
    attachments: list = Field(
        default_factory=list,
        description="File attachments (base64) — reserved for future provider support",
    )


@chat.function(
    "compose_send",
    action_type="write",
    event="sent",
    description="Send email from compose panel (reply/forward/new).",
)
async def fn_compose_send(ctx, params: ComposeSendParams) -> ActionResult:
    if not params.to:
        return ActionResult.error("Recipient (to) is required.")

    acc, provider = await _get_acc(ctx, params.account)
    if not acc:
        return _no_account_error()

    try:
        if params.mode == "reply" and params.message_id:
            result = await provider.reply(
                ctx, acc, message_id=params.message_id, body=params.body,
                to=params.to, cc=params.cc, bcc=params.bcc,
            )
        elif params.mode == "forward" and params.message_id:
            result = await provider.forward(
                ctx, acc, message_id=params.message_id, to=params.to, comment=params.body,
            )
        else:
            if not params.subject:
                return ActionResult.error("Subject is required for new emails.")
            result = await provider.send(
                ctx, acc, to=params.to, subject=params.subject,
                body=params.body, cc=params.cc, bcc=params.bcc,
            )
    except Exception as e:
        log.error("compose_send failed mode=%s: %s", params.mode, e)
        return ActionResult.error(f"Failed to send: {e}")

    if result.get("RESULT") == "ERROR":
        return ActionResult.error(result.get("error", "Send failed"))

    return ActionResult.success(
        data={"sent": True, "to": params.to, "mode": params.mode},
        summary=f"Email {params.mode} sent to {params.to}",
    )
