"""Mail Client · Inbox panel handler + fetch helper."""
from __future__ import annotations

import asyncio
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
from panels_filters_bar import build_filters_bar
from cache_model_defs import InboxMessages

log = logging.getLogger(__name__)

INBOX_INLINE_LIMIT = 25
INBOX_CACHE_TTL    = 60


async def _fetch_inbox_messages(ctx, provider, acc, folder,
                                cursor_data: dict | None = None) -> InboxMessages:
    """Fetch one page of messages. cursor_data=None → page 1; dict → next page."""
    email = acc.get("email", "")
    try:
        acc = await asyncio.wait_for(_refresh_token_if_needed(ctx, acc), timeout=5.0)
    except (asyncio.TimeoutError, Exception):
        pass

    total_in_folder = unread_in_folder = 0
    if cursor_data is None:
        try:
            stats = await asyncio.wait_for(
                provider.get_folder_stats(ctx, acc, folder), timeout=5.0)
            total_in_folder  = stats.get("total", 0)
            unread_in_folder = stats.get("unread", 0)
        except (asyncio.TimeoutError, Exception):
            pass

    messages, next_cursor_encoded = [], ""
    try:
        msgs, next_cursor_data, has_more = await asyncio.wait_for(
            provider.fetch_page(ctx, acc, folder, INBOX_INLINE_LIMIT, cursor_data),
            timeout=10.0,
        )
        messages = [
            {**m, "message_id": m["id"]} if "id" in m and "message_id" not in m else m
            for m in msgs
        ]
        if has_more and next_cursor_data:
            next_cursor_encoded = encode_cursor(
                acc.get("provider", "oauth"), next_cursor_data,
                account=email) or ""
    except asyncio.TimeoutError:
        log.warning("fetch_page timeout folder=%s account=%s", folder, email)
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
            "marked_unread,sent,mail.action,account.switched,account.connected,"
            "account.disconnected,prefs.updated",
)
async def inbox_panel(
    ctx,
    folder: str = "INBOX",
    do_action: str = "",
    do_message_id: str = "",
    do_switch_account: str = "",
    page_cursor: str = "",
    prev_cursor: str = "",
    page_num: int = 1,
    folder_stats_unread: int = 0,
    search_query: str = "",
    do_was_unread: bool = False,
    **_unused_kwargs,
):
    accounts = await _all_accounts(ctx)
    if not accounts:
        return ui.Empty(message="No email accounts connected")

    if do_switch_account:
        await _switch_active_account(ctx, do_switch_account)
        folder, search_query = "INBOX", ""
        page_cursor, prev_cursor, page_num, folder_stats_unread = "", "", 1, 0
        for _fkey in [f["key"] for f in FOLDERS]:
            await _invalidate_first_page(ctx, do_switch_account, _fkey)

    from providers.helpers import _active_account as _resolve_active
    acc = await _resolve_active(ctx, "")
    if not acc:
        return ui.Empty(message="No email account available")

    provider     = get_provider(acc)
    active_email = acc.get("email", "")

    await _execute_panel_action(ctx, provider, acc, do_action, do_message_id, folder)
    if do_action in ("archive", "delete", "spam", "restore", "unarchive", "unspam"):
        page_cursor, prev_cursor, page_num, folder_stats_unread = "", "", 1, 0
        base_key = _inbox_messages_key(active_email, folder)
        for _p in range(2, 6):
            try:
                await ctx.cache.delete(f"{base_key}:p{_p}")
            except Exception:
                pass
        if folder.upper() != "INBOX":
            base_inbox = _inbox_messages_key(active_email, "INBOX")
            for _p in range(2, 6):
                try:
                    await ctx.cache.delete(f"{base_inbox}:p{_p}")
                except Exception:
                    pass

    msgs_key = _inbox_messages_key(active_email, folder)
    current_page_key = msgs_key if page_num <= 1 else f"{msgs_key}:p{page_num}"

    header = ui.Stack([
        ui.Text(active_email[:32], variant="caption"),
        ui.Button("", icon="RefreshCw", variant="ghost", size="sm",
                   on_click=ui.Call("__panel__inbox", folder=folder)),
    ], direction="h", gap=1)

    try:
        if page_cursor:
            raw_cursor = decode_cursor(page_cursor)
            clean_cursor = (
                {k: v for k, v in raw_cursor.items() if k != "_a"}
                if raw_cursor else None
            )
            inbox_msgs = await ctx.cache.get_or_fetch(
                current_page_key, InboxMessages,
                lambda: _fetch_inbox_messages(ctx, provider, acc, folder, clean_cursor),
                ttl_seconds=INBOX_CACHE_TTL,
            )
        elif do_switch_account:
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
        folder_tabs = _build_folder_tabs(folder, active_email)
        return ui.Stack([header, folder_tabs,
                         ui.Error(message=f"Failed to load {folder}: {e}")])

    if do_action in ("mark_read", "mark_unread", "star", "unstar") and do_message_id:
        patched = []
        for m in inbox_msgs.messages:
            if m.get("message_id") == do_message_id:
                m = dict(m)
                if do_action == "mark_read":
                    m["unread"] = False
                elif do_action == "mark_unread":
                    m["unread"] = True
                elif do_action == "star":
                    m["starred"] = True
                    m["unread"] = do_was_unread  # restore state shown in UI at click time
                elif do_action == "unstar":
                    m["starred"] = False
                    m["unread"] = do_was_unread  # restore state shown in UI at click time
            patched.append(m)
        inbox_msgs = InboxMessages(
            account_id=inbox_msgs.account_id, folder=inbox_msgs.folder,
            messages=patched,
            total_in_folder=inbox_msgs.total_in_folder,
            unread_in_folder=inbox_msgs.unread_in_folder,
            next_cursor=inbox_msgs.next_cursor,
            fetched_at=inbox_msgs.fetched_at,
        )
        try:
            await ctx.cache.set(current_page_key, inbox_msgs, ttl_seconds=INBOX_CACHE_TTL)
        except Exception:
            pass

    # Read folder visibility preferences
    visible_folders: list | None = None
    try:
        prefs_page = await ctx.store.query("mail_prefs",
                                           where={"owner_id": ctx.user.imperal_id}, limit=1)
        if prefs_page.data:
            vf = prefs_page.data[0].data.get("visible_folders")
            visible_folders = vf if vf else None
    except Exception:
        pass

    effective_unread = inbox_msgs.unread_in_folder or (folder_stats_unread if page_num > 1 else 0)
    folder_tabs = _build_folder_tabs(
        folder, active_email,
        folder_unread={folder: effective_unread} if effective_unread else None,
        visible_folders=visible_folders,
    )

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
        show_cursor      = ""
        show_total       = 0
        carried_unread   = folder_stats_unread
    else:
        display_messages = inbox_msgs.messages
        unread_display   = effective_unread
        show_cursor      = inbox_msgs.next_cursor
        show_total       = inbox_msgs.total_in_folder
        carried_unread   = inbox_msgs.unread_in_folder or folder_stats_unread

    search_bar = ui.Input(
        placeholder="Search…",
        param_name="search_query",
        value=search_query,
        on_submit=ui.Call("__panel__inbox", folder=folder,
                           page_cursor="", prev_cursor="", page_num=1, folder_stats_unread=0),
    )

    search_status = None
    if q:
        n = len(display_messages)
        search_status = ui.Stack([
            ui.Badge(f'"{q}"', color="blue"),
            ui.Text(f"{n} result{'s' if n != 1 else ''}", variant="caption"),
            ui.Button("✕", variant="ghost", size="sm",
                      on_click=ui.Call("__panel__inbox", folder=folder, search_query="",
                                        page_cursor="", prev_cursor="", page_num=1)),
        ], direction="h", gap=1)

    email_list = _build_email_list(
        display_messages, active_email, folder,
        unread_count=unread_display,
    )

    nav_buttons: list = []
    if not q:
        has_prev = page_num > 1
        has_next = bool(show_cursor)
        if has_prev or has_next:
            if has_prev:
                nav_buttons.append(ui.Button(
                    "←", variant="ghost", size="sm",
                    on_click=ui.Call("__panel__inbox", folder=folder,
                                      page_cursor=prev_cursor, prev_cursor="",
                                      page_num=max(1, page_num - 1),
                                      folder_stats_unread=carried_unread),
                ))
            nav_buttons.append(ui.Text(str(page_num), variant="caption"))
            if has_next:
                nav_buttons.append(ui.Button(
                    "→", variant="ghost", size="sm",
                    on_click=ui.Call("__panel__inbox", folder=folder,
                                      page_cursor=show_cursor, prev_cursor=page_cursor,
                                      page_num=page_num + 1,
                                      folder_stats_unread=carried_unread),
                ))

    filters_bar = await build_filters_bar(ctx)
    children = [header, folder_tabs]
    if filters_bar:
        children.append(filters_bar)
    children.append(search_bar)
    if search_status:
        children.append(search_status)
    children.append(email_list)
    if nav_buttons:
        children.append(ui.Stack(nav_buttons, direction="h", gap=2))
    return ui.Stack(children, gap=1)
