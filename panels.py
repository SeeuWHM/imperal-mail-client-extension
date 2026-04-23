"""Mail Client · Panel handlers (Declarative UI)."""
from __future__ import annotations

import logging

from imperal_sdk import ui

from app import ext, _get_acc, _no_account_error
from providers import get_provider
from providers.helpers import _all_accounts, encode_cursor, decode_cursor, COLLECTION
from panels_email_viewer import build_email_viewer
from panels_accounts import build_accounts_panel
from panels_add_account import build_add_account_panel
from panels_compose import build_compose_panel
from providers.cache import get_cached_inbox, set_cached_inbox, invalidate_inbox

log = logging.getLogger(__name__)

FOLDERS = [
    {"key": "INBOX",   "label": "Inbox"},
    {"key": "sent",    "label": "Sent"},
    {"key": "drafts",  "label": "Drafts"},
    {"key": "spam",    "label": "Spam"},
    {"key": "trash",   "label": "Trash"},
    {"key": "starred", "label": "Starred"},
]


async def _execute_panel_action(ctx, provider, acc, action: str, message_id: str) -> None:
    """Execute a single-message action inline during panel render.

    Called BEFORE the inbox list is fetched so the result is immediately
    reflected without relying on event publishing (which only works from
    the full SessionWorkflow / LLM chat path, not from ui.Call / Fast RPC).
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
        # Always invalidate cache after action so the render below sees fresh data.
        await invalidate_inbox(ctx, email)
    except Exception as e:
        log.warning("panel action=%s message=%s failed: %s", action, message_id[:16], e)


def _build_email_list(
    messages: list[dict], next_cursor: str | None,
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

    on_end = None
    if has_more and next_cursor:
        on_end = ui.Call("__panel__inbox", cursor=next_cursor, folder=folder, account=active_email)

    # Bulk actions: SDK auto-injects selected IDs as `message_ids` list param.
    # These go through fn_mail_action (separate @chat.function path) because
    # we cannot embed a variable-length list in a panel call param.
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

    return ui.List(
        items=items,
        searchable=True,
        on_end_reached=on_end,
        selectable=True,
        bulk_actions=bulk,
        total_items=0,
        extra_info=f"{unread_count} unread" if unread_count > 0 else "",
    )


@ext.panel(
    "inbox", slot="left", title="Mail", icon="Mail",
    # NOTE: refresh="on_event:X" only fires when events are published by the
    # full SessionWorkflow (LLM chat path). ui.Call from panel buttons goes
    # through DirectCallWorkflow / Fast-RPC which does NOT publish events.
    # Single-message actions (do_action param) are handled inline in this
    # function so the panel re-renders immediately with fresh data — no events.
    # Bulk actions still use fn_mail_action; refresh on those is best-effort.
    refresh="on_event:mail.received,mail.archived,mail.deleted,mail.mail_action,mail.account_switched,mail.account_connected,mail.account_disconnected",
)
async def inbox_panel(
    ctx,
    cursor: str = "",
    folder: str = "INBOX",
    account: str = "",
    limit: int = 10,
    # Inline action params — filled by email-viewer action buttons.
    # The panel executes the action BEFORE fetching the list, so the result
    # is visible immediately without waiting for event propagation.
    do_action: str = "",
    do_message_id: str = "",
):
    accounts = await _all_accounts(ctx)
    if not accounts:
        return ui.Empty(message="No email accounts connected")

    acc, _ = await _get_acc(ctx, account)
    if not acc:
        return ui.Empty(message="No email account available")

    provider    = get_provider(acc)
    active_email = acc.get("email", "")

    # ── Execute inline action before fetching (guarantees fresh render) ──── #
    await _execute_panel_action(ctx, provider, acc, do_action, do_message_id)

    acc_options = [{"value": a.get("email", ""), "label": a.get("email", "?")} for a in accounts]

    # param_name injects the selected value as the named param in the Call.
    # Do NOT use account="$value" — that passes the literal string "$value".
    account_select = ui.Select(
        options=acc_options, value=active_email, placeholder="Select account",
        on_change=ui.Call("__panel__inbox", folder=folder),
        param_name="account",
    )

    cursor_data = decode_cursor(cursor) if cursor else None
    clamped     = max(1, min(limit, 100))

    # After an inline action, the cache was already cleared by _execute_panel_action.
    # get_cached_inbox will return None and fetch fresh from the provider.
    cached = await get_cached_inbox(ctx, active_email, folder, cursor)
    if cached:
        messages, next_cursor_data, has_more = cached
    else:
        try:
            messages, next_cursor_data, has_more = await provider.fetch_page(
                ctx, acc, folder, clamped, cursor_data,
            )
            await set_cached_inbox(ctx, active_email, folder, cursor,
                                   messages, next_cursor_data, has_more)
        except Exception as e:
            log.warning("inbox panel fetch_page failed folder=%s: %s", folder, e)
            return ui.Stack([account_select, ui.Error(message=f"Failed to load {folder}: {e}")])

    for msg in messages:
        if "id" in msg and "message_id" not in msg:
            msg["message_id"] = msg.pop("id")

    provider_key = acc.get("provider", "oauth")
    next_cursor  = encode_cursor(provider_key, next_cursor_data)

    unread_count = 0
    try:
        unread_count = await provider.get_unread_count(ctx, acc, folder)
    except Exception:
        unread_count = sum(1 for m in messages if m.get("unread"))

    email_list = _build_email_list(messages, next_cursor, has_more, folder, active_email, unread_count)

    folder_options = [{"value": f["key"], "label": f["label"]} for f in FOLDERS]
    folder_select = ui.Select(
        options=folder_options, value=folder, placeholder="Folder",
        on_change=ui.Call("__panel__inbox", account=active_email),
        param_name="folder",
    )

    refresh_btn = ui.Button(
        "", icon="RefreshCw", variant="ghost", size="sm",
        on_click=ui.Call("__panel__inbox", folder=folder, account=active_email),
    )

    return ui.Stack([
        ui.Stack([folder_select, account_select, refresh_btn], direction="horizontal"),
        email_list,
    ])


@ext.panel("email_viewer", slot="center", title="Email", icon="Mail")
async def email_viewer_panel(ctx, message_id: str = "", account: str = "",
                              email_list_ids: str = "", current_index: int = 0,
                              folder: str = "INBOX"):
    if not message_id:
        return await build_accounts_panel(ctx)
    return await build_email_viewer(ctx, message_id, account, email_list_ids, current_index, folder)


@ext.panel("accounts", slot="right", title="Accounts", icon="Users")
async def accounts_panel(ctx, show_add: bool = False):
    return await build_accounts_panel(ctx, show_add)


@ext.panel("compose", slot="center", title="Compose", icon="PenSquare")
async def compose_panel(ctx, mode: str = "new", message_id: str = "",
                         account: str = "", prefill_to: str = "",
                         prefill_subject: str = "", reply_all: str = ""):
    reply_all_bool = str(reply_all).lower() in ("true", "1", "yes")
    return await build_compose_panel(ctx, mode, message_id, account,
                                      prefill_to, prefill_subject, reply_all_bool)


@ext.panel("add_account", slot="right", title="Add Account", icon="UserPlus")
async def add_account_panel(ctx, step: str = "providers", email: str = "", error: str = ""):
    return await build_add_account_panel(ctx, step, email, error)
