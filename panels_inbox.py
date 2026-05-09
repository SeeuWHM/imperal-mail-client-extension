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
        await _invalidate_first_page(ctx, email, "INBOX")
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


def _build_folder_tabs(folder: str, active_email: str) -> ui.UINode:
    buttons = [
        ui.Button(
            f["label"],
            variant="primary" if f["key"] == folder else "ghost",
            size="sm",
            on_click=ui.Call("__panel__inbox", folder=f["key"]),
        )
        for f in FOLDERS
    ]
    return ui.Stack(buttons, direction="horizontal", wrap=True, gap=1)


def _build_email_list(
    messages: list[dict],
    active_email: str,
    folder: str,
    unread_count: int = 0,
    next_cursor: str = "",
    total_items: int = 0,
) -> ui.UINode:
    """Email list with native pagination and search via ui.List(page_size=25).

    total_items: real inbox size so the paginator shows the full < 1/N > range.
    next_cursor: when set, enables on_end_reached — clicking > beyond cached
    pages fires a panel call that fetches the next batch from API and extends
    the cached list seamlessly.
    """
    msg_ids  = [msg.get("message_id", msg.get("id", "")) for msg in messages]
    full_ids = ",".join(msg_ids)

    items = []
    for i, msg in enumerate(messages):
        mid     = msg_ids[i]
        snippet = (msg.get("snippet") or msg.get("preview") or "")[:120]
        starred = msg.get("starred", False)

        quick_actions = ui.Stack([
            ui.Button("", icon="Reply", size="sm", variant="ghost",
                      on_click=ui.Call("__panel__compose", mode="reply",
                                       message_id=mid, account=active_email)),
            ui.Button("", icon="Archive", size="sm", variant="ghost",
                      on_click=ui.Call("__panel__inbox", folder=folder,
                                       do_action="archive", do_message_id=mid)),
            ui.Button("", icon="Trash2", size="sm", variant="ghost",
                      on_click=ui.Call("__panel__inbox", folder=folder,
                                       do_action="delete", do_message_id=mid)),
            ui.Button("", icon="MailOpen", size="sm", variant="ghost",
                      on_click=ui.Call("__panel__inbox", folder=folder,
                                       do_action="mark_read", do_message_id=mid)),
        ], direction="horizontal", gap=1)

        items.append(ui.ListItem(
            id=mid,
            title=msg.get("from", "Unknown")[:40],
            subtitle=msg.get("subject", "(no subject)")[:60],
            meta=msg.get("date", "")[:10],
            icon="Star" if starred else "",
            badge=ui.Badge("new", color="blue") if msg.get("unread") else None,
            on_click=ui.Call(
                "__panel__email_viewer",
                message_id=mid,
                account=active_email,
                folder=folder,
                email_list_ids=full_ids,
                current_index=i,
            ),
            expandable=True,
            expanded_content=ui.Stack([
                ui.Text(snippet or "(no preview)", variant="caption"),
                quick_actions,
            ], gap=1),
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

    info = f"{unread_count} unread" if unread_count > 0 else ""

    # on_end_reached fires when user navigates beyond the last loaded page.
    # total_items tells the paginator the real inbox size so the < > arrows
    # show the full page range even before all messages are fetched.
    on_end = (
        ui.Call("__panel__inbox", folder=folder, load_more_cursor=next_cursor)
        if next_cursor else None
    )
    show_total = total_items if total_items > len(messages) else 0

    return ui.Stack([
        ui.Text(info, variant="caption") if info else ui.Stack([]),
        ui.List(
            items=items, page_size=25, selectable=True, bulk_actions=bulk,
            on_end_reached=on_end,
            total_items=show_total,
        ),
    ], gap=1)
