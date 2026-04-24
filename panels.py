"""Mail Client · Panel handlers (Declarative UI)."""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from imperal_sdk import ui

from app import ext
from ctx_helpers import _get_acc
from providers import get_provider
from providers.helpers import (
    _all_accounts, encode_cursor, decode_cursor, COLLECTION,
    _inbox_page_key, _unread_summary_key, _invalidate_first_page,
)
from panels_email_viewer import build_email_viewer
from panels_accounts import build_accounts_panel
from panels_add_account import build_add_account_panel
from panels_compose import build_compose_panel
from cache_models import InboxPage, UnreadSummary

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
    """Explicit folder tab buttons — no param_name injection needed.

    Each button has the folder value hardcoded in the Call, so the correct
    folder is always passed regardless of SDK Select injection behavior.
    """
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

    # Bulk actions — SDK injects selected IDs as `message_ids` list into fn_mail_action.
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
    refresh="on_event:mail.received,mail.archived,mail.deleted,mail.mail_action,mail.account_switched,mail.account_connected,mail.account_disconnected",
)
async def inbox_panel(
    ctx,
    cursor: str = "",
    folder: str = "INBOX",
    account: str = "",
    limit: int = 10,
    # Inline action — executed BEFORE fetching (no event dependency).
    do_action: str = "",
    do_message_id: str = "",
    # Inline account switch — updates DB + uses new account for this render.
    do_switch_account: str = "",
    # Tolerate unknown UI params (e.g. active_message_id from newer panel
    # clients) so a UI-side evolution never 500s the render.
    **_unused_kwargs,
):
    accounts = await _all_accounts(ctx)
    if not accounts:
        return ui.Empty(message="No email accounts connected")

    # ── Inline account switch ─────────────────────────────────────────────── #
    if do_switch_account:
        await _switch_active_account(ctx, do_switch_account)
        # Use the switched account for this render (don't rely on DB re-query).
        account = do_switch_account

    acc, _ = await _get_acc(ctx, account)
    if not acc:
        return ui.Empty(message="No email account available")

    provider     = get_provider(acc)
    active_email = acc.get("email", "")

    # ── Inline single-message action ──────────────────────────────────────── #
    await _execute_panel_action(ctx, provider, acc, do_action, do_message_id)

    # ── Header: account indicator + refresh ───────────────────────────────── #
    # No Select — account switching via right Accounts panel is reliable.
    # Select's param_name injection is fragile; explicit button calls are not.
    account_info = ui.Stack([
        ui.Text(active_email[:32], variant="caption"),
        ui.Button("", icon="Users", variant="ghost", size="sm",
                   on_click=ui.Call("__panel__accounts")),
        ui.Button("", icon="RefreshCw", variant="ghost", size="sm",
                   on_click=ui.Call("__panel__inbox", folder=folder, account=active_email)),
    ], direction="horizontal", gap=1)

    # ── Folder tabs: explicit buttons, no param_name injection ────────────── #
    folder_tabs = _build_folder_tabs(folder, active_email)

    # ── Fetch inbox page via ctx.cache.get_or_fetch (SDK v1.6.0) ──────────── #
    cursor_data = decode_cursor(cursor) if cursor else None
    clamped     = max(1, min(limit, 100))

    async def _fetch_page() -> InboxPage:
        messages, next_cursor_data, has_more = await provider.fetch_page(
            ctx, acc, folder, clamped, cursor_data,
        )
        provider_key = acc.get("provider", "oauth")
        next_cur = encode_cursor(provider_key, next_cursor_data) or ""
        # Normalise message dicts (id → message_id) so the consumer is consistent.
        norm = []
        for m in messages:
            if "id" in m and "message_id" not in m:
                m = {**m, "message_id": m["id"]}
            norm.append(m)
        return InboxPage(
            account_id=active_email,
            folder=folder,
            cursor=cursor or "",
            messages=norm,
            next_cursor=next_cur,
            has_more=bool(has_more),
            fetched_at=datetime.now(timezone.utc),
        )

    try:
        page = await ctx.cache.get_or_fetch(
            key=_inbox_page_key(active_email, folder, cursor),
            model=InboxPage,
            fetcher=_fetch_page,
            ttl_seconds=120,
        )
    except Exception as e:
        log.warning("inbox panel fetch_page failed folder=%s: %s", folder, e)
        return ui.Stack([
            account_info, folder_tabs,
            ui.Error(message=f"Failed to load {folder}: {e}"),
        ])

    messages = page.messages
    next_cursor = page.next_cursor or None
    has_more = page.has_more

    # ── Unread count via ctx.cache.get_or_fetch ───────────────────────────── #
    async def _fetch_unread() -> UnreadSummary:
        try:
            count = await provider.get_unread_count(ctx, acc, folder)
        except Exception:
            count = sum(1 for m in messages if m.get("unread"))
        return UnreadSummary(account_id=active_email, folder=folder, unread_count=int(count or 0))

    try:
        summary = await ctx.cache.get_or_fetch(
            key=_unread_summary_key(active_email, folder),
            model=UnreadSummary,
            fetcher=_fetch_unread,
            ttl_seconds=30,
        )
        unread_count = summary.unread_count
    except Exception:
        unread_count = sum(1 for m in messages if m.get("unread"))

    email_list = _build_email_list(messages, next_cursor, has_more, folder, active_email, unread_count)

    return ui.Stack([account_info, folder_tabs, email_list])


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
