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

    Download endpoints don't exist on the platform yet (SDK gap — no proxy/serve
    mechanism for binary extension files). Showing honest metadata is better than
    broken download buttons.
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
    buttons = [
        ui.Button("Back", icon="ArrowLeft", variant="ghost", size="sm",
                   on_click=ui.Call("__panel__inbox", folder=folder)),
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
                   on_click=ui.Call("mail_action", action="archive",
                                    message_id=message_id, account=account_email)),
        ui.Button("Spam", icon="Ban", variant="outline", size="sm",
                   on_click=ui.Call("mail_action", action="spam",
                                    message_id=message_id, account=account_email)),
        ui.Button("Delete", icon="Trash2", variant="danger", size="sm",
                   on_click=ui.Call("mail_action", action="delete",
                                    message_id=message_id, account=account_email)),
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

    # read_email already marks the message as read internally (Google: removeLabelIds UNREAD,
    # MS: PATCH isRead, IMAP: STORE +FLAGS \Seen). No second mark_read call needed.

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
            # Render HTML as-is inside the sandboxed iframe. The sandbox attr
            # blocks scripts; external images load from their original servers
            # (standard email client behaviour). Image proxy was removed because
            # the /api/mail/proxy endpoint doesn't exist on the platform.
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
