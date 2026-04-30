"""Mail Client · Panel handlers (Declarative UI)."""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from imperal_sdk import ui

from app import ext
from providers import get_provider
from providers.helpers import (
    _all_accounts, _invalidate_first_page,
    _inbox_messages_key, _refresh_token_if_needed,
    encode_cursor,
)
from panels_inbox import (
    FOLDERS,
    _execute_panel_action, _switch_active_account,
    _build_folder_tabs, _build_email_list,
)
from panels_email_viewer import build_email_viewer
from panels_accounts import build_accounts_panel
from panels_add_account import build_add_account_panel
from panels_compose import build_compose_panel
from cache_model_defs import InboxMessages

log = logging.getLogger(__name__)

INBOX_INLINE_LIMIT = 200
INBOX_CACHE_TTL    = 90


async def _fetch_inbox_messages(ctx, provider, acc, folder) -> InboxMessages:
    email = acc.get("email", "")
    try:
        acc = await _refresh_token_if_needed(ctx, acc)
    except Exception:
        pass
    try:
        stats            = await provider.get_folder_stats(ctx, acc, folder)
        total_in_folder  = stats.get("total", 0)
        unread_in_folder = stats.get("unread", 0)
    except Exception:
        total_in_folder = unread_in_folder = 0

    messages, next_cursor_encoded = [], ""
    try:
        msgs, next_cursor_data, has_more = await provider.fetch_page(
            ctx, acc, folder, INBOX_INLINE_LIMIT, None,
        )
        for m in msgs:
            if "id" in m and "message_id" not in m:
                m = {**m, "message_id": m["id"]}
        messages = msgs
        if has_more and next_cursor_data:
            next_cursor_encoded = encode_cursor(acc.get("provider", "oauth"), next_cursor_data) or ""
    except Exception as e:
        log.warning("inbox fetch_page failed folder=%s: %s", folder, e)

    return InboxMessages(
        account_id=email, folder=folder, messages=messages,
        total_in_folder=total_in_folder, unread_in_folder=unread_in_folder,
        next_cursor=next_cursor_encoded, fetched_at=datetime.now(timezone.utc),
    )


@ext.panel(
    "inbox", slot="left", title="Mail", icon="Mail",
    refresh="on_event:archived,deleted,bulk_archived,bulk_deleted,marked_read,"
            "marked_unread,mail.action,account.switched,account.connected,account.disconnected",
)
async def inbox_panel(
    ctx,
    folder: str = "INBOX",
    do_action: str = "",
    do_message_id: str = "",
    do_switch_account: str = "",
    search_query: str = "",
    **_unused_kwargs,
):
    accounts = await _all_accounts(ctx)
    if not accounts:
        return ui.Empty(message="No email accounts connected")

    if do_switch_account:
        await _switch_active_account(ctx, do_switch_account)
        folder, search_query = "INBOX", ""
        for _fkey in [f["key"] for f in FOLDERS]:
            await _invalidate_first_page(ctx, do_switch_account, _fkey)

    from providers.helpers import _active_account as _resolve_active
    acc = await _resolve_active(ctx, "")
    if not acc:
        return ui.Empty(message="No email account available")

    provider     = get_provider(acc)
    active_email = acc.get("email", "")

    await _execute_panel_action(ctx, provider, acc, do_action, do_message_id)

    header = ui.Stack([
        ui.Text(active_email[:32], variant="caption"),
        ui.Button("", icon="RefreshCw", variant="ghost", size="sm",
                   on_click=ui.Call("__panel__inbox", folder=folder)),
    ], direction="horizontal", gap=1)

    folder_tabs = _build_folder_tabs(folder, active_email)

    # Load cached messages
    msgs_key = _inbox_messages_key(active_email, folder)
    try:
        if do_switch_account:
            inbox_msgs = await _fetch_inbox_messages(ctx, provider, acc, folder)
        else:
            inbox_msgs = await ctx.cache.get_or_fetch(
                msgs_key, InboxMessages,
                lambda: _fetch_inbox_messages(ctx, provider, acc, folder),
                ttl_seconds=INBOX_CACHE_TTL,
            )
            if inbox_msgs.account_id != active_email or inbox_msgs.folder != folder:
                inbox_msgs = await _fetch_inbox_messages(ctx, provider, acc, folder)
    except Exception as e:
        log.warning("inbox panel load failed folder=%s: %s", folder, e)
        return ui.Stack([header, folder_tabs,
                         ui.Error(message=f"Failed to load {folder}: {e}")])

    # Search: combined local filter + server query
    q = search_query.strip()
    if q and len(q) >= 2:
        ql = q.lower()
        local = [
            m for m in inbox_msgs.messages
            if ql in (m.get("subject", "") + " " + m.get("from", "") + " " + m.get("snippet", "")).lower()
        ]
        local_ids = {m.get("message_id", "") for m in local}
        server_extra: list[dict] = []
        try:
            sr = await provider.search(ctx, acc, query=q, max_results=30)
            for m in sr.get("results", []):
                mid = m.get("message_id", m.get("id", ""))
                if mid and mid not in local_ids:
                    if "message_id" not in m:
                        m = {**m, "message_id": mid}
                    server_extra.append(m)
        except Exception:
            pass
        display_messages = local + server_extra
        unread_display   = 0
    else:
        display_messages = inbox_msgs.messages
        unread_display   = inbox_msgs.unread_in_folder

    search_bar = ui.Input(
        placeholder="Search…",
        param_name="search_query",
        value=search_query,
        on_submit=ui.Call("__panel__inbox", folder=folder),
    )

    # When search is active — show query badge + clear button
    search_status = None
    if q:
        n = len(display_messages)
        search_status = ui.Stack([
            ui.Badge(f'"{q}"', color="blue"),
            ui.Text(f"{n} result{'s' if n != 1 else ''}", variant="caption"),
            ui.Button("✕", variant="ghost", size="sm",
                      on_click=ui.Call("__panel__inbox", folder=folder, search_query="")),
        ], direction="horizontal", gap=1)

    email_list = _build_email_list(
        display_messages, active_email, folder,
        unread_count=unread_display,
    )

    children = [header, folder_tabs, search_bar]
    if search_status:
        children.append(search_status)
    children.append(email_list)
    return ui.Stack(children, gap=1)


@ext.panel("email_viewer", slot="center", title="Email", icon="Mail")
async def email_viewer_panel(ctx, message_id: str = "", account: str = "",
                              email_list_ids: str = "", current_index: int = 0,
                              folder: str = "INBOX"):
    if not message_id:
        return await build_accounts_panel(ctx)
    return await build_email_viewer(ctx, message_id, account, email_list_ids, current_index, folder)


@ext.panel(
    "accounts", slot="right", title="Accounts", icon="Users",
    refresh="interval:30s",
)
async def accounts_panel(ctx, show_add: bool = False, do_switch: str = ""):
    return await build_accounts_panel(ctx, show_add, do_switch)


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
