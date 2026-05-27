"""Mail Client · Inbox panel helpers — actions, account switch, list builders."""
from __future__ import annotations

import datetime as _dt
import email.utils as _eu
import logging

from imperal_sdk import ui

from providers.helpers import _invalidate_first_page, COLLECTION

log = logging.getLogger(__name__)

FOLDERS = [
    {"key": "INBOX",   "label": "Inbox"},
    {"key": "sent",    "label": "Sent"},
    {"key": "drafts",  "label": "Drafts"},
    {"key": "spam",    "label": "Spam"},
    {"key": "trash",   "label": "Trash"},
    {"key": "starred", "label": "Starred"},
    {"key": "archive", "label": "Archive"},
]


def _format_msg_date(date_str: str) -> str:
    """Today → HH:MM, yesterday → Yesterday, this year → Jan 05, older → Jan 05 2025."""
    if not date_str:
        return ""
    try:
        try:
            parsed = _eu.parsedate_to_datetime(date_str)
        except Exception:
            parsed = _dt.datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        now  = _dt.datetime.now(_dt.timezone.utc)
        msg  = parsed.astimezone(_dt.timezone.utc)
        diff = (now.date() - msg.date()).days
        if diff == 0:
            return msg.strftime("%H:%M")
        if diff == 1:
            return "Yesterday"
        if msg.year == now.year:
            return msg.strftime("%b %d")
        return msg.strftime("%b %d %Y")
    except Exception:
        return date_str[:10]


async def _execute_panel_action(ctx, provider, acc, action: str, message_id: str,
                                 folder: str = "INBOX") -> None:
    """Execute a single-message action inline before the inbox list renders."""
    if not action or not message_id:
        return
    email = acc.get("email", "")
    try:
        if action == "archive":
            await provider.archive(ctx, acc, message_id)
        elif action == "delete":
            await provider.delete(ctx, acc, message_id)
        elif action == "spam":
            await provider.move(ctx, acc, message_id, "INBOX", "spam")
        elif action == "mark_read":
            await provider.mark_read(ctx, acc, message_id, read=True)
        elif action == "mark_unread":
            await provider.mark_read(ctx, acc, message_id, read=False)
        elif action == "star":
            await provider.star(ctx, acc, message_id, starred=True)
        elif action == "unstar":
            await provider.star(ctx, acc, message_id, starred=False)
        elif action == "unspam":
            await provider.move(ctx, acc, message_id, "spam", "INBOX")
        elif action == "unarchive":
            await provider.move(ctx, acc, message_id, "archive", "INBOX")
        elif action == "restore":
            await provider.move(ctx, acc, message_id, "trash", "INBOX")
        # Only invalidate cache for structural changes (messages move between folders).
        # State-only changes (star/unstar/mark_read/mark_unread) are handled by
        # the optimistic patch in inbox_panel — no re-fetch needed, avoids
        # Gmail eventual-consistency returning stale unread state.
        if action in ("archive", "delete", "spam", "unspam", "unarchive", "restore"):
            await _invalidate_first_page(ctx, email, "INBOX")
            if folder.upper() != "INBOX":
                await _invalidate_first_page(ctx, email, folder)
    except Exception as e:
        log.warning("panel action=%s message=%s failed: %s", action, message_id[:16], e)


async def _switch_active_account(ctx, target_email: str) -> None:
    """Update is_active in the store so _get_acc returns the right account."""
    try:
        page = await ctx.store.query(COLLECTION)
        for d in page.data:
            should_be_active = (d.data.get("email") == target_email)
            if d.data.get("is_active") != should_be_active:
                await ctx.store.update(COLLECTION, d.id,
                                       {**d.data, "is_active": should_be_active})
    except Exception as e:
        log.warning("switch_active_account to %s failed: %s", target_email, e)


def _build_folder_tabs(folder: str, active_email: str,
                       folder_unread: dict | None = None) -> ui.UINode:
    """Folder tab buttons. folder_unread maps folder key → unread count."""
    counts = folder_unread or {}
    buttons = []
    for f in FOLDERS:
        key   = f["key"]
        label = f["label"]
        n     = counts.get(key, 0)
        label_str = f"{label} ({n})" if n > 0 else label
        buttons.append(ui.Button(
            label_str,
            variant="primary" if key == folder else "ghost",
            size="sm",
            on_click=ui.Call("__panel__inbox", folder=key,
                              page_cursor="", prev_cursor="", page_num=1,
                              folder_stats_unread=0),
        ))
    return ui.Stack(buttons, direction="h", wrap=True, gap=1)


def _build_email_list(
    messages: list[dict],
    active_email: str,
    folder: str,
    unread_count: int = 0,
) -> ui.UINode:
    """Email list with contextual per-folder actions, per-message star/read toggles,
    smart date formatting, and on-demand pagination via on_end_reached."""
    folder_lower = folder.lower()
    msg_ids  = [msg.get("message_id", msg.get("id", "")) for msg in messages]
    full_ids = ",".join(msg_ids)

    # ── Folder-context primary action (archive vs unarchive vs unspam etc.) ──
    if folder_lower in ("spam", "junk"):
        def _primary(mid):
            return {"label": "Not Spam", "icon": "ShieldCheck",
                    "on_click": ui.Call("__panel__inbox", folder=folder,
                                        do_action="unspam", do_message_id=mid)}
    elif folder_lower == "archive":
        def _primary(mid):
            return {"label": "To Inbox", "icon": "Inbox",
                    "on_click": ui.Call("__panel__inbox", folder=folder,
                                        do_action="unarchive", do_message_id=mid)}
    elif folder_lower in ("trash", "deleted"):
        def _primary(mid):
            return {"label": "Restore", "icon": "Undo",
                    "on_click": ui.Call("__panel__inbox", folder=folder,
                                        do_action="restore", do_message_id=mid)}
    else:
        def _primary(mid):
            return {"label": "Archive", "icon": "Archive",
                    "on_click": ui.Call("__panel__inbox", folder=folder,
                                        do_action="archive", do_message_id=mid)}

    # ── Bulk actions (context-aware per folder) ──────────────────────────────
    if folder_lower in ("spam", "junk"):
        bulk = [
            {"label": "Not Spam", "icon": "ShieldCheck",
             "action": ui.Call("mail_action", action="unspam",     account=active_email)},
            {"label": "Delete",   "icon": "Trash2",
             "action": ui.Call("mail_action", action="delete",     account=active_email)},
            {"label": "Read",     "icon": "MailOpen",
             "action": ui.Call("mail_action", action="mark_read",  account=active_email)},
            {"label": "Unread",   "icon": "Mail",
             "action": ui.Call("mail_action", action="mark_unread",account=active_email)},
        ]
    elif folder_lower == "archive":
        bulk = [
            {"label": "To Inbox", "icon": "Inbox",
             "action": ui.Call("mail_action", action="unarchive",  account=active_email)},
            {"label": "Delete",   "icon": "Trash2",
             "action": ui.Call("mail_action", action="delete",     account=active_email)},
            {"label": "Read",     "icon": "MailOpen",
             "action": ui.Call("mail_action", action="mark_read",  account=active_email)},
            {"label": "Unread",   "icon": "Mail",
             "action": ui.Call("mail_action", action="mark_unread",account=active_email)},
        ]
    elif folder_lower in ("trash", "deleted"):
        bulk = [
            {"label": "Restore", "icon": "Undo",
             "action": ui.Call("mail_action", action="restore",    account=active_email)},
            {"label": "Delete",  "icon": "Trash2",
             "action": ui.Call("mail_action", action="delete",     account=active_email)},
            {"label": "Read",    "icon": "MailOpen",
             "action": ui.Call("mail_action", action="mark_read",  account=active_email)},
        ]
    elif folder_lower == "starred":
        bulk = [
            {"label": "Unstar",  "icon": "StarOff",
             "action": ui.Call("mail_action", action="unstar",     account=active_email)},
            {"label": "Archive", "icon": "Archive",
             "action": ui.Call("mail_action", action="archive",    account=active_email)},
            {"label": "Delete",  "icon": "Trash2",
             "action": ui.Call("mail_action", action="delete",     account=active_email)},
            {"label": "Read",    "icon": "MailOpen",
             "action": ui.Call("mail_action", action="mark_read",  account=active_email)},
        ]
    else:
        bulk = [
            {"label": "Archive", "icon": "Archive",
             "action": ui.Call("mail_action", action="archive",    account=active_email)},
            {"label": "Delete",  "icon": "Trash2",
             "action": ui.Call("mail_action", action="delete",     account=active_email)},
            {"label": "Star",    "icon": "Star",
             "action": ui.Call("mail_action", action="star",       account=active_email)},
            {"label": "Read",    "icon": "MailOpen",
             "action": ui.Call("mail_action", action="mark_read",  account=active_email)},
            {"label": "Unread",  "icon": "Mail",
             "action": ui.Call("mail_action", action="mark_unread",account=active_email)},
        ]

    # ── Per-message items ────────────────────────────────────────────────────
    items = []
    for i, msg in enumerate(messages):
        mid       = msg_ids[i]
        starred   = msg.get("starred", False)
        is_unread = msg.get("unread", False)

        # Star toggle based on current message state
        star_act   = "unstar" if starred else "star"
        star_label = "Unstar" if starred else "Star"
        star_icon  = "StarOff" if starred else "Star"

        # Read/Unread toggle based on current message state
        read_act   = "mark_read" if is_unread else "mark_unread"
        read_label = "Read"      if is_unread else "Unread"
        read_icon  = "MailOpen"  if is_unread else "Mail"

        item_actions = [
            {"label": "Reply",    "icon": "Reply",
             "on_click": ui.Call("__panel__compose", mode="reply",
                                 message_id=mid, account=active_email)},
            {"label": star_label, "icon": star_icon,
             "on_click": ui.Call("__panel__inbox", folder=folder,
                                 do_action=star_act, do_message_id=mid,
                                 do_was_unread=is_unread)},
            _primary(mid),
            {"label": "Delete",   "icon": "Trash2",
             "on_click": ui.Call("__panel__inbox", folder=folder,
                                 do_action="delete", do_message_id=mid)},
            {"label": read_label, "icon": read_icon,
             "on_click": ui.Call("__panel__inbox", folder=folder,
                                 do_action=read_act, do_message_id=mid)},
        ]

        # Badge: unread=blue, starred-but-read=yellow, neither=None
        if is_unread:
            badge = ui.Badge("new", color="blue")
        elif starred:
            badge = ui.Badge("★", color="yellow")
        else:
            badge = None

        items.append(ui.ListItem(
            id=mid,
            title=msg.get("from", "Unknown")[:40],
            subtitle=msg.get("subject", "(no subject)")[:60],
            meta=_format_msg_date(msg.get("date", "")),
            icon="Star" if starred else "",
            badge=badge,
            on_click=ui.Call(
                "__panel__email_viewer",
                message_id=mid,
                account=active_email,
                folder=folder,
                email_list_ids=full_ids,
                current_index=i,
            ),
            actions=item_actions,
        ))

    info = f"{unread_count} unread" if unread_count > 0 else ""

    return ui.Stack([
        ui.Text(info, variant="caption") if info else ui.Stack([]),
        ui.List(items=items, selectable=True, bulk_actions=bulk),
    ], gap=1)
