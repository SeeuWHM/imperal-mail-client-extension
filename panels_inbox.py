"""Mail Client · Inbox panel helpers — actions, account switch, list builders."""
from __future__ import annotations

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


async def _execute_panel_action(ctx, provider, acc, action: str, message_id: str) -> None:
    """Execute a single-message action BEFORE the inbox list is fetched.

    Called inline so the result is immediately reflected in the render
    without depending on event publishing (which only works from the
    full SessionWorkflow / LLM chat path, not from ui.Call / Fast-RPC).
    """
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
        await _invalidate_first_page(ctx, email, "INBOX")
    except Exception as e:
        log.warning("panel action=%s message=%s failed: %s", action, message_id[:16], e)


async def _switch_active_account(ctx, target_email: str) -> None:
    """Update is_active in the store so _get_acc returns the right account."""
    try:
        docs = await ctx.store.query(COLLECTION)
        for d in docs:
            _data = d.data if hasattr(d, "data") else d
            _id = d.id if hasattr(d, "id") else d["doc_id"]
            should_be_active = (_data.get("email") == target_email)
            if _data.get("is_active") != should_be_active:
                await ctx.store.update(COLLECTION, _id,
                                       {**_data, "is_active": should_be_active})
    except Exception as e:
        log.warning("switch_active_account to %s failed: %s", target_email, e)


def _build_folder_tabs(folder: str, active_email: str) -> ui.UINode:
    """Explicit folder tab buttons — no param_name injection needed."""
    buttons = [
        ui.Button(
            f["label"],
            variant="primary" if f["key"] == folder else "ghost",
            size="sm",
            on_click=ui.Call("__panel__inbox", folder=f["key"], account=active_email),
        )
        for f in FOLDERS
    ]
    return ui.Stack(buttons, direction="horizontal", wrap=True, gap=1)


def _build_email_list(
    messages: list[dict],
    has_more: bool, folder: str, active_email: str,
    unread_count: int = 0,
) -> ui.UINode:
    items = []
    msg_ids = []
    for msg in messages:
        mid = msg.get("message_id", msg.get("id", ""))
        msg_ids.append(mid)
        items.append(ui.ListItem(
            id=mid,
            title=msg.get("from", "Unknown")[:40],
            subtitle=msg.get("subject", "(no subject)")[:60],
            meta=msg.get("date", "")[:10],
            badge=ui.Badge("new", color="blue") if msg.get("unread") else None,
            on_click=ui.Call(
                "__panel__email_viewer",
                message_id=mid,
                account=active_email,
                folder=folder,
                email_list_ids=",".join(msg_ids),
                current_index=len(msg_ids) - 1,
            ),
        ))

    bulk = [
        {"label": "Archive", "icon": "Archive",
         "action": ui.Call("mail_action", action="archive", account=active_email)},
        {"label": "Delete",  "icon": "Trash2",
         "action": ui.Call("mail_action", action="delete",  account=active_email)},
        {"label": "Read",    "icon": "MailOpen",
         "action": ui.Call("mail_action", action="mark_read",   account=active_email)},
        {"label": "Unread",  "icon": "Mail",
         "action": ui.Call("mail_action", action="mark_unread", account=active_email)},
    ]

    # extra_info shows TOTAL folder unread (provider.get_unread_count scope = folder,
    # not page) + pagination hint.
    info_parts = []
    if unread_count > 0:
        info_parts.append(f"{unread_count} unread")
    if has_more:
        info_parts.append("more messages below")
    elif messages:
        info_parts.append(f"{len(messages)} messages")

    return ui.List(
        items=items,
        searchable=True,
        selectable=True,
        bulk_actions=bulk,
        total_items=0,
        extra_info=" · ".join(info_parts),
    )
