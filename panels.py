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
    encode_cursor, decode_cursor,
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

INBOX_INLINE_LIMIT = 75   # initial fetch (fast, ~1 API call)
INBOX_LOAD_MORE    = 75   # each "load more" batch
INBOX_PAGE_SIZE    = 25   # ui.List page_size
INBOX_CACHE_TTL    = 90   # seconds


async def _fetch_inbox_messages(ctx, provider, acc, folder) -> InboxMessages:
    """Fetch INBOX_INLINE_LIMIT messages. Token refreshed once upfront."""
    email = acc.get("email", "")
    try:
        acc = await _refresh_token_if_needed(ctx, acc)
    except Exception:
        pass

    try:
        stats = await provider.get_folder_stats(ctx, acc, folder)
        total_in_folder  = stats.get("total", 0)
        unread_in_folder = stats.get("unread", 0)
    except Exception:
        total_in_folder = unread_in_folder = 0

    all_messages: list[dict] = []
    next_cursor_encoded = ""
    try:
        messages, next_cursor_data, has_more = await provider.fetch_page(
            ctx, acc, folder, INBOX_INLINE_LIMIT, None,
        )
        for m in messages:
            if "id" in m and "message_id" not in m:
                m = {**m, "message_id": m["id"]}
        all_messages = messages
        if has_more and next_cursor_data:
            next_cursor_encoded = encode_cursor(acc.get("provider", "oauth"), next_cursor_data) or ""
    except Exception as e:
        log.warning("inbox fetch_page failed folder=%s: %s", folder, e)

    return InboxMessages(
        account_id=email, folder=folder,
        messages=all_messages,
        total_in_folder=total_in_folder,
        unread_in_folder=unread_in_folder,
        next_cursor=next_cursor_encoded,
        fetched_at=datetime.now(timezone.utc),
    )


async def _extend_inbox_messages(ctx, provider, acc, folder, msgs_key) -> InboxMessages:
    """Load next INBOX_LOAD_MORE messages and append to cached list."""
    try:
        acc = await _refresh_token_if_needed(ctx, acc)
    except Exception:
        pass
    email = acc.get("email", "")
    try:
        cached = await ctx.cache.get(msgs_key, InboxMessages)
    except Exception:
        cached = None

    if not cached or not cached.next_cursor:
        return cached or await _fetch_inbox_messages(ctx, provider, acc, folder)

    cursor_data = decode_cursor(cached.next_cursor)
    try:
        more_msgs, next_cursor_data2, has_more2 = await provider.fetch_page(
            ctx, acc, folder, INBOX_LOAD_MORE, cursor_data,
        )
        for m in more_msgs:
            if "id" in m and "message_id" not in m:
                m = {**m, "message_id": m["id"]}
        next_cur2 = (encode_cursor(acc.get("provider", "oauth"), next_cursor_data2) or "") if has_more2 else ""
        updated = InboxMessages(
            account_id=email, folder=folder,
            messages=cached.messages + more_msgs,
            total_in_folder=cached.total_in_folder,
            unread_in_folder=cached.unread_in_folder,
            next_cursor=next_cur2,
            fetched_at=datetime.now(timezone.utc),
        )
        await ctx.cache.set(msgs_key, updated, ttl_seconds=INBOX_CACHE_TTL)
        return updated
    except Exception as e:
        log.warning("load_more failed: %s", e)
        return cached


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
    load_more: bool = False,
    search_query: str = "",
    **_unused_kwargs,
):
    accounts = await _all_accounts(ctx)
    if not accounts:
        return ui.Empty(message="No email accounts connected")

    if do_switch_account:
        await _switch_active_account(ctx, do_switch_account)
        folder = "INBOX"
        for _fkey in [f["key"] for f in FOLDERS]:
            await _invalidate_first_page(ctx, do_switch_account, _fkey)

    from providers.helpers import _active_account as _resolve_active
    acc = await _resolve_active(ctx, "")
    if not acc:
        return ui.Empty(message="No email account available")

    provider     = get_provider(acc)
    active_email = acc.get("email", "")

    await _execute_panel_action(ctx, provider, acc, do_action, do_message_id)

    # Header: email address + refresh button
    account_info = ui.Stack([
        ui.Text(active_email[:32], variant="caption"),
        ui.Button("", icon="RefreshCw", variant="ghost", size="sm",
                   on_click=ui.Call("__panel__inbox", folder=folder)),
    ], direction="horizontal", gap=1)

    # Search input — always visible, server-side search on submit
    search_input = ui.Input(
        placeholder="Search all emails…",
        param_name="search_query",
        value=search_query,
        on_submit=ui.Call("__panel__inbox", folder=folder),
    )

    # ── Search mode ──────────────────────────────────────────────────────── #
    if search_query:
        try:
            acc = await _refresh_token_if_needed(ctx, acc)
        except Exception:
            pass
        try:
            result  = await provider.search(ctx, acc, query=search_query, max_results=50)
            results = result.get("results", [])
            for m in results:
                if "id" in m and "message_id" not in m:
                    m["message_id"] = m["id"]
        except Exception as e:
            return ui.Stack([account_info, search_input,
                             ui.Error(message=f"Search failed: {e}")])

        back_btn = ui.Button("← Back to inbox", variant="ghost", size="sm",
                              on_click=ui.Call("__panel__inbox", folder=folder))
        info = ui.Text(f'{len(results)} results for "{search_query}"', variant="caption")
        email_list = _build_email_list(results, active_email, folder,
                                        unread_count=0, has_more=False)
        return ui.Stack([account_info, search_input, back_btn, info, email_list], gap=1)

    # ── Normal mode ──────────────────────────────────────────────────────── #
    folder_tabs = _build_folder_tabs(folder, active_email)
    msgs_key    = _inbox_messages_key(active_email, folder)

    try:
        if do_switch_account:
            inbox_msgs = await _fetch_inbox_messages(ctx, provider, acc, folder)
        elif load_more:
            inbox_msgs = await _extend_inbox_messages(ctx, provider, acc, folder, msgs_key)
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
        return ui.Stack([account_info, search_input, folder_tabs,
                         ui.Error(message=f"Failed to load {folder}: {e}")])

    email_list = _build_email_list(
        inbox_msgs.messages, active_email, folder,
        unread_count=inbox_msgs.unread_in_folder,
        has_more=bool(inbox_msgs.next_cursor),
        folder_for_more=folder,
    )

    return ui.Stack([account_info, search_input, folder_tabs, email_list], gap=1)


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
