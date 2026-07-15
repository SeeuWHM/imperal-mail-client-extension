"""Mail Client · Compose send handler for panel (SDK 5.2.0 / SDL)."""
from __future__ import annotations

import logging

from app import chat
from imperal_sdk.chat.action_result import ActionResult
from ctx_helpers import _get_acc

from schemas import ComposeSendParams, ComposeSendResult
from schemas_sdl_builders import ComposeSentResult, build_compose_sent

log = logging.getLogger(__name__)


# ─── impl_* business logic ────────────────────────────────────────────── #


async def impl_compose_send(ctx, mode: str = "new", message_id: str = "", to: str = "",
                            subject: str = "", body: str = "", cc: str = "", bcc: str = "",
                            account: str = "") -> ComposeSendResult:
    if not to and mode == "reply" and message_id:
        try:
            acc_tmp, prov_tmp = await _get_acc(ctx, account)
            if acc_tmp:
                orig = await prov_tmp.read_email(ctx, acc_tmp, message_id)
                if orig.get("RESULT") != "ERROR":
                    to = orig.get("from", "")
        except Exception:
            pass
    if not to:
        raise RuntimeError("Recipient (to) is required.")
    acc, provider = await _get_acc(ctx, account)
    if not acc:
        raise RuntimeError("No email account connected. Connect one first.")
    try:
        # This panel's compose form uses ui.RichEditor for the body (see
        # panels_compose.py) — its content is ALWAYS an HTML string, never
        # plain text, so is_html=True unconditionally for these two paths.
        # (forward's `comment` still goes through the plain-text quoting
        # path in provider.forward — out of scope here.)
        if mode == "reply" and message_id:
            result = await provider.reply(ctx, acc, message_id=message_id, body=body,
                                          to=to, cc=cc, bcc=bcc, is_html=True)
        elif mode == "forward" and message_id:
            result = await provider.forward(ctx, acc, message_id=message_id, to=to, comment=body)
        else:
            if not subject:
                raise RuntimeError("Subject is required for new emails.")
            result = await provider.send(ctx, acc, to=to, subject=subject, body=body, cc=cc, bcc=bcc,
                                         is_html=True)
    except RuntimeError:
        raise
    except Exception as e:
        log.error("compose_send failed mode=%s: %s", mode, e)
        raise RuntimeError(f"Failed to send: {e}")
    if result.get("RESULT") == "ERROR":
        raise RuntimeError(result.get("error") or "Send failed")
    return ComposeSendResult(sent=True, to=to, mode=mode)


# ─── @chat.function wrapper ───────────────────────────────────────────── #


@chat.function("compose_send", action_type="write", event="sent",
               effects=["create:email"],
               data_model=ComposeSentResult,
               description="Panel compose form submit — sends from the UI compose panel (mode: new/reply/forward). From LLM chat use send(), reply(), or forward() instead.")
async def fn_compose_send(ctx, params: ComposeSendParams) -> ActionResult:
    """Panel compose form submit — sends from the UI compose panel (mode: new/reply/forward)."""
    try:
        r = await impl_compose_send(ctx, mode=params.mode, message_id=params.message_id,
                                    to=params.to, subject=params.subject, body=params.body,
                                    cc=params.cc, bcc=params.bcc, account=params.account)
        return ActionResult.success(
            data=build_compose_sent(r, to=params.to),
            summary=f"Email sent to {params.to}.",
            refresh_panels=["inbox"],
        )
    except Exception as e:
        return ActionResult.error(str(e), retryable=False)
