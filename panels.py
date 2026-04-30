"""Mail Client · Panel handlers (Declarative UI)."""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from imperal_sdk import ui

from app import ext
from ctx_helpers import _get_acc
from providers import get_provider
from providers.helpers import (
    _all_accounts, _invalidate_first_page,
    _inbox_messages_key, _inbox_manifest_key,
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

INBOX_FLAT_LIMIT = 150   # max messages to load per folder
INBOX_PAGE_SIZE  = 25    # items shown per page in ui.List
INBOX_CACHE_TTL  = 90    # seconds


async def _fetch_inbox_messages(ctx, provider, acc, folder) -> InboxMessages:
    """Fetch up to INBOX_FLAT_LIMIT messages for a folder in one or two provider calls."""
    email = acc.get("email", "")

    # Folder stats (total + unread) — single lightweight API call
    try:
        stats = await provider.get_folder_stats(ctx, acc, folder)
        total_in_folder  = stats.get("total", 0)
        unread_in_folder = stats.get("unread", 0)
    except Exception:
        total_in_folder = unread_in_folder = 0

    # Fetch up to INBOX_FLAT_LIMIT messages — single provider call with large limit
    all_messages: list[dict] = []
    cursor_data = None
    while len(all_messages) < INBOX_FLAT_LIMIT:
        remaining = INBOX_FLAT_LIMIT - len(all_messages)
        try:
            messages, next_cursor_data, has_more = await provider.fetch_page(
                ctx, acc, folder, remaining, cursor_data,
            )
        except Exception as e:
            log.warning("inbox fetch_page failed folder=%s: %s", folder, e)
            break
        for m in messages:
            if "id" in m and "message_id" not in m:
                m = {**m, "message_id": m["id"]}
        all_messages.extend(messages)
        if not has_more or not next_cursor_data or len(messages) < remaining:
            break
        cursor_data = next_cursor_data

    return InboxMessages(
        account_id=email, folder=folder,
        messages=all_messages,
        total_in_folder=total_in_folder,
        unread_in_folder=unread_in_folder,
        fetched_at=datetime.now(timezone.utc),
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

    # Header
    account_info = ui.Stack([
        ui.Text(active_email[:32], variant="caption"),
        ui.Button("", icon="RefreshCw", variant="ghost", size="sm",
                   on_click=ui.Call("__panel__inbox", folder=folder)),
    ], direction="horizontal", gap=1)

    folder_tabs = _build_folder_tabs(folder, active_email)

    # Load flat message list (cache-first, inline populate on miss — DB ext pattern)
    msgs_key = _inbox_messages_key(active_email, folder)

    async def _fetcher() -> InboxMessages:
        return await _fetch_inbox_messages(ctx, provider, acc, folder)

    try:
        if do_switch_account:
            inbox_msgs = await _fetcher()
        else:
            inbox_msgs = await ctx.cache.get_or_fetch(
                msgs_key, InboxMessages, _fetcher, ttl_seconds=INBOX_CACHE_TTL,
            )
            if inbox_msgs.account_id != active_email or inbox_msgs.folder != folder:
                inbox_msgs = await _fetcher()
    except Exception as e:
        log.warning("inbox panel load failed folder=%s: %s", folder, e)
        return ui.Stack([account_info, folder_tabs,
                         ui.Error(message=f"Failed to load {folder}: {e}")])

    email_list = _build_email_list(
        inbox_msgs.messages, active_email, folder,
        unread_count=inbox_msgs.unread_in_folder,
    )

    return ui.Stack([account_info, folder_tabs, email_list])


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
    from panels_add_account import build_add_account_panel as _build
    return await _build(ctx, step, email, error)
