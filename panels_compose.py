"""Mail Client · Compose Panel (center overlay for reply/forward/new)."""
from __future__ import annotations

import logging
import re

from imperal_sdk import ui

from ctx_helpers import _get_acc

log = logging.getLogger(__name__)


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
    to_value      = prefill_to
    cc_value      = ""
    subject_value = prefill_subject

    if mode in ("reply", "forward") and message_id and not prefill_to:
        try:
            original = await provider.read_email(ctx, acc, message_id)
            if original.get("RESULT") != "ERROR":
                orig_subject = original.get("subject", "")
                if mode == "reply":
                    to_value = original.get("from", "")
                    if reply_all:
                        orig_cc = original.get("cc", "")
                        orig_to = original.get("to", "")
                        all_recipients = []
                        for addr in (orig_to + "," + orig_cc).split(","):
                            addr = addr.strip()
                            if addr:
                                m = re.match(r'.*<([^>]+)>', addr)
                                parsed = m.group(1).strip().lower() if m else addr.lower()
                                if parsed and parsed != account_email.lower():
                                    all_recipients.append(addr)
                        cc_value = ", ".join(all_recipients)
                    subject_value = (
                        f"Re: {orig_subject}" if not orig_subject.lower().startswith("re:") else orig_subject
                    )
                elif mode == "forward":
                    subject_value = (
                        f"Fwd: {orig_subject}" if not orig_subject.lower().startswith("fwd:") else orig_subject
                    )
        except Exception:
            pass

    title = {
        "reply":   f"Reply to {to_value[:40]}" if to_value else "Reply",
        "forward": f"Forward: {subject_value[:40]}" if subject_value else "Forward",
        "new":     "New Email",
    }.get(mode, "Compose")

    back_target = (
        ui.Call("__panel__email_viewer", message_id=message_id, account=account_email)
        if message_id else ui.Call("__panel__inbox")
    )

    return ui.Stack([
        ui.Stack([
            ui.Button("Back", icon="ArrowLeft", variant="ghost", size="sm", on_click=back_target),
            ui.Text(title, variant="body"),
        ], direction="horizontal", sticky=True),
        ui.Form(
            children=[
                ui.Input(placeholder="To", value=to_value, param_name="to"),
                ui.Input(placeholder="CC", value=cc_value, param_name="cc"),
                ui.Input(placeholder="BCC", param_name="bcc"),
                ui.Input(placeholder="Subject", value=subject_value, param_name="subject"),
                ui.TextArea(placeholder="Write your message...", rows=12, param_name="body"),
                # Attachments are not yet supported — the platform has no SDK mechanism
                # to serve binary files from extensions (proxy/download endpoint missing).
                # FileUpload is removed until that SDK gap is closed.
                ui.Text("📎 Attachments: coming in a future update", variant="caption"),
            ],
            action="compose_send",
            submit_label="Send",
            defaults={"mode": mode, "message_id": message_id, "account": account_email},
        ),
    ], className="px-4 pb-4")
