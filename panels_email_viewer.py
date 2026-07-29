"""Mail Client · Email Viewer Panel (center overlay)."""
from __future__ import annotations

import logging
from html import escape as html_escape

from imperal_sdk import ui

from app import ext
from ctx_helpers import _get_acc
from mail_providers import get_provider

log = logging.getLogger(__name__)


def _attachment_items(attachments: list[dict]) -> list[ui.UINode]:
    nodes = []
    for att in attachments:
        filename = att.get("filename", "attachment")
        size_kb  = att.get("size_kb", att.get("size", 0))
        if isinstance(size_kb, (int, float)) and size_kb > 1024:
            size_str = f"{size_kb / 1024:.1f} MB"
        else:
            size_str = f"{size_kb} KB" if size_kb else ""
        label = filename + (f"  ({size_str})" if size_str else "")
        nodes.append(ui.Text(label, variant="caption"))
    return nodes


def _action_bar(message_id: str, account_email: str, has_cc: bool,
                folder: str = "INBOX",
                email_list_ids: str = "", current_index: int = 0) -> ui.UINode:
    ids     = [i for i in email_list_ids.split(",") if i] if email_list_ids else []
    prev_id = ids[current_index - 1] if current_index > 0 and len(ids) > current_index - 1 else None
    next_id = ids[current_index + 1] if len(ids) > current_index + 1 else None

    buttons = [
        ui.Button("Back", icon="ArrowLeft", variant="ghost", size="sm",
                   on_click=ui.Call("__panel__inbox", folder=folder, account=account_email)),
    ]
    if prev_id:
        buttons.append(ui.Button("", icon="ChevronLeft", variant="ghost", size="sm",
            on_click=ui.Call("__panel__email_viewer", message_id=prev_id,
                             account=account_email, folder=folder,
                             email_list_ids=email_list_ids, current_index=current_index - 1)))
    if next_id:
        buttons.append(ui.Button("", icon="ChevronRight", variant="ghost", size="sm",
            on_click=ui.Call("__panel__email_viewer", message_id=next_id,
                             account=account_email, folder=folder,
                             email_list_ids=email_list_ids, current_index=current_index + 1)))
    buttons.append(ui.Button("Reply", icon="Reply", variant="primary", size="sm",
                   on_click=ui.Call("__panel__compose", mode="reply",
                                    message_id=message_id, account=account_email)))
    if has_cc:
        buttons.append(ui.Button("Reply All", icon="Reply", variant="outline", size="sm",
            on_click=ui.Call("__panel__compose", mode="reply",
                             message_id=message_id, account=account_email, reply_all=True)))
    buttons.extend([
        ui.Button("Forward", icon="Forward", variant="outline", size="sm",
                   on_click=ui.Call("__panel__compose", mode="forward",
                                    message_id=message_id, account=account_email)),
        ui.Button("Archive", icon="Archive", variant="outline", size="sm",
                   on_click=ui.Call("__panel__inbox", folder=folder, account=account_email,
                                    do_action="archive", do_message_id=message_id)),
        ui.Button("Spam", icon="Ban", variant="outline", size="sm",
                   on_click=ui.Call("__panel__inbox", folder=folder, account=account_email,
                                    do_action="spam", do_message_id=message_id)),
        ui.Button("Delete", icon="Trash2", variant="danger", size="sm",
                   on_click=ui.Call("__panel__inbox", folder=folder, account=account_email,
                                    do_action="delete", do_message_id=message_id)),
    ])
    return ui.Stack(buttons, direction="h", wrap=True, sticky=True)


async def build_email_viewer(
    ctx, message_id: str, account: str = "",
    email_list_ids: str = "", current_index: int = 0,
    folder: str = "INBOX",
) -> ui.UINode:
    acc, provider = await _get_acc(ctx, account)
    if not acc:
        return ui.Empty(message="No email account available")

    account_email = acc.get("email", "")

    try:
        result = await provider.read_email(ctx, acc, message_id)
    except Exception as e:
        log.warning("read_email failed mid=%s: %s", message_id, e)
        return ui.Error(message=f"Failed to load email: {e}",
                        retry=ui.Call("__panel__email_viewer", message_id=message_id,
                                      account=account_email, folder=folder))

    if result.get("RESULT") == "ERROR":
        return ui.Error(message=result.get("error") or "Failed to load email")

    subject     = result.get("subject", "(no subject)")
    from_name   = result.get("from", "Unknown")
    to_field    = result.get("to", "")
    cc_field    = result.get("cc", "")
    date_str    = result.get("date", "")
    body        = result.get("body", "")
    body_type   = result.get("body_type", "html")
    # Auto-detect HTML: RichEditor sends HTML bodies that some providers
    # return without body_type="html" (e.g. sent items with text/plain MIME).
    if body_type != "html" and body and body.lstrip().startswith("<"):
        body_type = "html"
    attachments = result.get("attachments", [])
    replied     = result.get("replied", False)

    # ── Tab 0: Message ──────────────────────────────────────────────────
    meta_items = [{"key": "From", "value": from_name}]
    if to_field:  meta_items.append({"key": "To",   "value": to_field})
    if cc_field:  meta_items.append({"key": "CC",   "value": cc_field})
    if date_str:  meta_items.append({"key": "Date", "value": date_str})

    subject_row: list = [ui.Header(text=subject, level=3)]
    if replied:
        subject_row.append(ui.Badge("↩ Replied", color="green"))

    msg_children: list = [
        ui.Stack(subject_row, direction="h", gap=2, align="center") if replied
        else ui.Header(text=subject, level=3),
        ui.KeyValue(items=meta_items, columns=1),
    ]
    if attachments:
        n = len(attachments)
        msg_children.append(ui.Stack([
            ui.Text(f"{n} attachment{'s' if n > 1 else ''}", variant="caption"),
            ui.Stack(_attachment_items(attachments), direction="v", gap=1),
        ]))
    msg_children.append(ui.Divider())
    if body:
        if body_type == "html":
            msg_children.append(ui.Html(content=body, sandbox=True, theme="light"))
        else:
            safe_text = html_escape(body)
            msg_children.append(ui.Html(
                content=(
                    f'<pre style="white-space:pre-wrap;word-break:break-word;'
                    f'font-family:-apple-system,BlinkMacSystemFont,sans-serif;'
                    f'font-size:14px;line-height:1.65;margin:0">{safe_text}</pre>'
                ),
                sandbox=True, theme="light",
            ))
    else:
        msg_children.append(ui.Empty(message="No content", icon="FileText"))

    return ui.Stack([
        _action_bar(message_id, account_email,
                    has_cc=bool(cc_field), folder=folder,
                    email_list_ids=email_list_ids, current_index=current_index),
        ui.Stack(msg_children, gap=2),
    ], className="px-4 pb-4")
