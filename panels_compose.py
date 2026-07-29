"""Mail Client · Compose Panel (center overlay for reply/forward/new)."""
from __future__ import annotations

import logging
import re

from imperal_sdk import ui

from ctx_helpers import _get_acc
from mail_providers.helpers import CONTACTS_COLLECTION

log = logging.getLogger(__name__)


def _parse_tags(value: str) -> list[str]:
    """Split a comma/semicolon-separated address string into a tag list."""
    return [v.strip() for v in re.split(r"[,;]", value) if v.strip()]


async def build_compose_panel(
    ctx,
    mode: str = "new",
    message_id: str = "",
    account: str = "",
    prefill_to: str = "",
    prefill_subject: str = "",
    reply_all: bool = False,
) -> ui.UINode:
    acc, provider = await _get_acc(ctx, account)
    if not acc:
        return ui.Empty(message="No email account available")

    account_email = acc.get("email", "")

    # Load contacts for TagInput autocomplete
    suggestions: list[str] = []
    try:
        docs = await ctx.store.query(CONTACTS_COLLECTION, limit=200)
        suggestions = sorted({d.data.get("email", "") for d in docs.data if d.data.get("email")})
    except Exception:
        pass

    to_tags      = _parse_tags(prefill_to)
    cc_tags: list[str] = []
    subject_value = prefill_subject

    if mode in ("reply", "forward") and message_id and not prefill_to:
        try:
            original = await provider.read_email(ctx, acc, message_id)
            if original.get("RESULT") != "ERROR":
                orig_subject = original.get("subject", "")
                if mode == "reply":
                    to_tags = _parse_tags(original.get("from", ""))
                    if reply_all:
                        recipients = []
                        for field in ("to", "cc"):
                            for addr in re.split(r"[,;]", original.get(field, "")):
                                addr = addr.strip()
                                if addr:
                                    m = re.match(r".*<([^>]+)>", addr)
                                    parsed = (m.group(1).strip() if m else addr).lower()
                                    if parsed and parsed != account_email.lower():
                                        recipients.append(parsed)
                        cc_tags = recipients
                    subject_value = (
                        f"Re: {orig_subject}"
                        if not orig_subject.lower().startswith("re:")
                        else orig_subject
                    )
                elif mode == "forward":
                    subject_value = (
                        f"Fwd: {orig_subject}"
                        if not orig_subject.lower().startswith("fwd:")
                        else orig_subject
                    )
        except Exception:
            pass

    title = {
        "reply":   f"Reply to {to_tags[0][:40]}" if to_tags else "Reply",
        "forward": f"Forward: {subject_value[:40]}" if subject_value else "Forward",
        "new":     "New Email",
    }.get(mode, "Compose")

    back_target = (
        ui.Call("__panel__email_viewer", message_id=message_id, account=account_email)
        if message_id else ui.Call("__panel__inbox")
    )

    _tag = dict(
        suggestions=suggestions,
        delimiters=[",", ";"],
        validate=r"^[^@\s]+@[^@\s]+\.[^@\s]+$",
        validate_message="Enter a valid email address",
    )

    return ui.Stack([
        ui.Stack([
            ui.Button("Back", icon="ArrowLeft", variant="ghost", size="sm", on_click=back_target),
            ui.Text(title, variant="body"),
        ], direction="h", sticky=True),
        ui.Form(
            children=[
                ui.TagInput(placeholder="To", values=to_tags, param_name="to", **_tag),
                ui.TagInput(placeholder="CC", values=cc_tags, param_name="cc", **_tag),
                ui.TagInput(placeholder="BCC", param_name="bcc", **_tag),
                ui.Input(placeholder="Subject", value=subject_value, param_name="subject"),
                ui.RichEditor(
                    placeholder="Write your message…",
                    param_name="body",
                    toolbar=True,
                ),
            ],
            action="compose_send",
            submit_label="Send",
            defaults={"mode": mode, "message_id": message_id, "account": account_email,
                      "to": ",".join(to_tags), "cc": ",".join(cc_tags)},
        ),
    ], className="px-4 pb-4")
