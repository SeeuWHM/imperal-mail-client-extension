"""Mail Client · Compose send handler for panel (SDK v2.0.0)."""
from __future__ import annotations

import logging

from ctx_helpers import _get_acc

from schemas import ComposeSendResult

log = logging.getLogger(__name__)


async def impl_compose_send(
    ctx, mode: str = "new", message_id: str = "", to: str = "",
    subject: str = "", body: str = "", cc: str = "", bcc: str = "",
    account: str = "", attachments: list | None = None,
) -> ComposeSendResult:
    if not to:
        raise RuntimeError("Recipient (to) is required.")

    acc, provider = await _get_acc(ctx, account)
    if not acc:
        raise RuntimeError("No email account connected. Connect one first.")

    try:
        if mode == "reply" and message_id:
            result = await provider.reply(
                ctx, acc, message_id=message_id, body=body,
                to=to, cc=cc, bcc=bcc,
            )
        elif mode == "forward" and message_id:
            result = await provider.forward(
                ctx, acc, message_id=message_id, to=to, comment=body,
            )
        else:
            if not subject:
                raise RuntimeError("Subject is required for new emails.")
            result = await provider.send(
                ctx, acc, to=to, subject=subject, body=body, cc=cc, bcc=bcc,
            )
    except RuntimeError:
        raise
    except Exception as e:
        log.error("compose_send failed mode=%s: %s", mode, e)
        raise RuntimeError(f"Failed to send: {e}")

    if result.get("RESULT") == "ERROR":
        raise RuntimeError(result.get("error", "Send failed"))

    return ComposeSendResult(sent=True, to=to, mode=mode)
