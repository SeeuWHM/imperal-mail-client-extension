"""Mail Client · Email Viewer Panel (center overlay)."""
from __future__ import annotations

import logging
from html import escape as html_escape

from imperal_sdk import ui

from app import ext
from ctx_helpers import _get_acc
from mail_providers import get_provider

log = logging.getLogger(__name__)


def _is_forwarded(subject: str) -> bool:
    """Honest forward detection: providers themselves stamp this exact prefix
    when the user hits Forward (see mail_providers/imap.py, google_write.py,
    microsoft_write.py — all three build 'Fwd: {orig_subj}'). No guessing."""
    s = (subject or "").strip().lower()
    return s.startswith("fwd:") or s.startswith("fw:")


async def _fetch_thread(ctx, provider, acc, thread_id: str) -> tuple[list[dict], str | None]:
    """Fetch the thread once — reuses the SAME provider.get_thread() the
    get_thread() chat.function calls, so panel and chat tool never disagree
    about what a thread contains. Returns (messages, error_message)."""
    try:
        thread_result = await provider.get_thread(ctx, acc, thread_id)
    except Exception as e:
        return [], f"Could not load conversation: {e}"
    if thread_result.get("RESULT") == "ERROR":
        return [], thread_result.get("error") or "Conversation unavailable"
    return thread_result.get("messages", []), None


def _really_replied(messages: list[dict], current_message_id: str,
                     current_date: str, account_email: str) -> bool:
    """Honest 'did I reply to this' for Google/Microsoft: True only if the
    thread actually contains a LATER message sent from this account's own
    address — the same real-world fact IMAP's \\Answered flag encodes, just
    derived from data the providers already give us instead of a flag
    neither Gmail's nor Graph's read_email response exposes directly.
    """
    if not messages or not account_email:
        return False
    from email.utils import parsedate_to_datetime
    def _pd(raw):
        try:
            return parsedate_to_datetime(raw)
        except Exception:
            return None
    current_dt = _pd(current_date)
    for m in messages:
        if m.get("id") == current_message_id:
            continue
        sender = (m.get("from") or "").lower()
        if account_email.lower() not in sender:
            continue
        if current_dt is None:
            return True  # can't order reliably — presence of our own reply is still real
        m_dt = _pd(m.get("date"))
        if m_dt and m_dt > current_dt:
            return True
    return False


def _conversation_timeline(messages: list[dict], current_message_id: str) -> ui.UINode:
    if not messages:
        return ui.Empty(message="No other messages in this conversation", icon="MessagesSquare")
    items = []
    for m in messages:
        is_current = m.get("id") == current_message_id
        title = f"{m.get('from', 'unknown')} — {m.get('subject', '(no subject)')}"
        if is_current:
            title += "  (this message)"
        body_preview = (m.get("body") or "")[:400]
        items.append({
            "title": title,
            "description": body_preview,
            "time": m.get("date", ""),
            "icon": "Mail" if m.get("unread") else "MailOpen",
            "color": "blue" if is_current else "gray",
        })
    return ui.Timeline(items)


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
    thread_id   = result.get("thread_id", "")
    truncated   = result.get("truncated", False)
    forwarded   = _is_forwarded(subject)

    # Thread support varies by provider — IMAP has no real thread concept
    # (get_thread() returns a hard error there), so only fetch/show it when
    # it can actually succeed.
    supports_thread = bool(thread_id) and acc.get("provider") not in ("imap", "yahoo")
    thread_messages: list[dict] = []
    thread_error: str | None = None
    if supports_thread:
        thread_messages, thread_error = await _fetch_thread(ctx, provider, acc, thread_id)

    # replied: IMAP already gives us a real \Answered flag from the provider.
    # Google/Microsoft don't expose an equivalent flag on read_email, so it's
    # derived honestly from the thread data we just fetched (a later message
    # from our own address = we really did reply) instead of always False.
    replied = result.get("replied", False)
    if not replied and supports_thread and thread_messages:
        replied = _really_replied(thread_messages, message_id, date_str, account_email)

    # ── Tab 0: Message ──────────────────────────────────────────────────
    meta_items = [{"key": "From", "value": from_name}]
    if to_field:  meta_items.append({"key": "To",   "value": to_field})
    if cc_field:  meta_items.append({"key": "CC",   "value": cc_field})
    if date_str:  meta_items.append({"key": "Date", "value": date_str})

    subject_row: list = [ui.Header(text=subject, level=3)]
    if replied:
        subject_row.append(ui.Badge("↩ Replied", color="green"))
    if forwarded:
        subject_row.append(ui.Badge("➜ Forwarded", color="blue"))

    msg_children: list = [
        ui.Stack(subject_row, direction="h", gap=2, align="center")
        if (replied or forwarded) else ui.Header(text=subject, level=3),
        ui.KeyValue(items=meta_items, columns=1),
    ]
    if attachments:
        n = len(attachments)
        msg_children.append(ui.Stack([
            ui.Text(f"{n} attachment{'s' if n > 1 else ''}", variant="caption"),
            ui.Stack(_attachment_items(attachments), direction="v", gap=1),
        ]))
    msg_children.append(ui.Divider())
    if truncated:
        msg_children.append(ui.Alert(
            "This message was too long and has been shortened — some content "
            "at the end may be missing.",
            type="warn",
        ))
    # Fixed, generous height with its own scrollbar (ui.Html's default is an
    # unbounded auto-height up to 3000px, so a long email pushed the action
    # bar and the rest of the panel out of view instead of scrolling in place).
    if body:
        if body_type == "html":
            msg_children.append(ui.Html(content=body, sandbox=True, theme="light",
                                         max_height=900))
        else:
            safe_text = html_escape(body)
            msg_children.append(ui.Html(
                content=(
                    f'<pre style="white-space:pre-wrap;word-break:break-word;'
                    f'font-family:-apple-system,BlinkMacSystemFont,sans-serif;'
                    f'font-size:14px;line-height:1.65;margin:0">{safe_text}</pre>'
                ),
                sandbox=True, theme="light", max_height=900,
            ))
    else:
        msg_children.append(ui.Empty(message="No content", icon="FileText"))

    message_tab_content = ui.Stack(msg_children, gap=2)

    action_bar = _action_bar(message_id, account_email,
                              has_cc=bool(cc_field), folder=folder,
                              email_list_ids=email_list_ids, current_index=current_index)

    if supports_thread:
        conv_content = (ui.Alert(thread_error, type="warn") if thread_error
                        else _conversation_timeline(thread_messages, message_id))
        content = ui.Tabs(tabs=[
            {"label": "Message", "content": message_tab_content},
            {"label": "Conversation", "content": conv_content},
        ])
    else:
        content = message_tab_content

    return ui.Stack([action_bar, content], className="px-4 pb-4")
