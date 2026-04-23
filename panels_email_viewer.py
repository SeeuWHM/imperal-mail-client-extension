"""Mail Client · Email Viewer Panel (center overlay)."""
from __future__ import annotations

import logging
from html import escape as html_escape

from imperal_sdk import ui

from app import ext, _get_acc
from providers import get_provider

log = logging.getLogger(__name__)


def _attachment_info(attachments: list[dict]) -> list[ui.UINode]:
    """Render attachment metadata as read-only text items.

    Download endpoints don't exist on the platform (no proxy/serve mechanism
    for binary extension files — SDK gap). Metadata-only until that lands.
    """
    nodes = []
    for att in attachments:
        filename = att.get("filename", "attachment")
        size_kb  = att.get("size_kb", att.get("size", 0))
        if isinstance(size_kb, (int, float)) and size_kb > 1024:
            size_str = f"{size_kb / 1024:.1f} MB"
        else:
            size_str = f"{size_kb} KB" if size_kb else ""
        label = f"📎 {filename}" + (f"  ({size_str})" if size_str else "")
        nodes.append(ui.Text(label, variant="caption"))
    return nodes


def _action_bar(message_id: str, account_email: str,
                has_cc: bool, folder: str = "INBOX") -> ui.UINode:
    """Action toolbar for the email viewer.

    Archive / Spam / Delete call __panel__inbox with do_action + do_message_id.
    This causes inbox_panel to execute the action INLINE before rendering,
    so the list updates immediately — no dependency on event publishing
    (which only works from the full SessionWorkflow / LLM chat path,
    not from ui.Call / Fast-RPC / DirectCallWorkflow).
    """
    buttons = [
        ui.Button("Back", icon="ArrowLeft", variant="ghost", size="sm",
                   on_click=ui.Call("__panel__inbox", folder=folder, account=account_email)),
        ui.Button("Reply", icon="Reply", variant="primary", size="sm",
                   on_click=ui.Call("__panel__compose", mode="reply",
                                    message_id=message_id, account=account_email)),
    ]
    if has_cc:
        buttons.append(ui.Button(
            "Reply All", icon="Reply", variant="outline", size="sm",
            on_click=ui.Call("__panel__compose", mode="reply",
                             message_id=message_id, account=account_email,
                             reply_all=True),
        ))
    buttons.extend([
        ui.Button("Forward", icon="Forward", variant="outline", size="sm",
                   on_click=ui.Call("__panel__compose", mode="forward",
                                    message_id=message_id, account=account_email)),
        ui.Button("Archive", icon="Archive", variant="outline", size="sm",
                   on_click=ui.Call("__panel__inbox",
                                    folder=folder, account=account_email,
                                    do_action="archive", do_message_id=message_id)),
        ui.Button("Spam", icon="Ban", variant="outline", size="sm",
                   on_click=ui.Call("__panel__inbox",
                                    folder=folder, account=account_email,
                                    do_action="spam", do_message_id=message_id)),
        ui.Button("Delete", icon="Trash2", variant="danger", size="sm",
                   on_click=ui.Call("__panel__inbox",
                                    folder=folder, account=account_email,
                                    do_action="delete", do_message_id=message_id)),
    ])
    return ui.Stack(buttons, direction="horizontal", wrap=True, sticky=True)


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
        return ui.Error(message=f"Failed to load email: {e}")

    if result.get("RESULT") == "ERROR":
        return ui.Error(message=result.get("error", "Failed to load email"))

    # read_email already marks as read internally (Google: removeLabelIds UNREAD,
    # MS: PATCH isRead, IMAP: STORE +FLAGS \Seen). No redundant mark_read needed.
    # The inbox list will reflect the updated read state on next render (e.g., Back click).

    subject     = result.get("subject", "(no subject)")
    from_name   = result.get("from", "Unknown")
    to_field    = result.get("to", "")
    cc_field    = result.get("cc", "")
    date_str    = result.get("date", "")
    body        = result.get("body", "")
    body_type   = result.get("body_type", "html")
    attachments = result.get("attachments", [])

    children: list[ui.UINode] = []
    children.append(_action_bar(message_id, account_email,
                                has_cc=bool(cc_field), folder=folder))
    children.append(ui.Header(text=subject, level=3))

    kv_items = [{"key": "From", "value": from_name}]
    if to_field:  kv_items.append({"key": "To",   "value": to_field})
    if cc_field:  kv_items.append({"key": "CC",   "value": cc_field})
    if date_str:  kv_items.append({"key": "Date", "value": date_str})
    children.append(ui.KeyValue(items=kv_items, columns=1))

    if attachments:
        n = len(attachments)
        children.append(ui.Text(f"{n} attachment{'s' if n > 1 else ''}", variant="caption"))
        children.append(ui.Stack(_attachment_info(attachments), direction="vertical", gap=1))

    children.append(ui.Divider())

    if body:
        if body_type == "html":
            children.append(ui.Html(content=body, sandbox=True, theme="light"))
        else:
            safe_text = html_escape(body)
            pre_html  = (
                f'<pre style="white-space:pre-wrap;word-break:break-word;'
                f'font-family:-apple-system,BlinkMacSystemFont,sans-serif;'
                f'font-size:14px;line-height:1.65;margin:0">{safe_text}</pre>'
            )
            children.append(ui.Html(content=pre_html, sandbox=True, theme="light"))
    else:
        children.append(ui.Empty(message="No content", icon="FileText"))

    return ui.Stack(children, className="px-4 pb-4")
