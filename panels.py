"""Mail Client · Panel handlers (Declarative UI)."""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from imperal_sdk import ui

import math

from app import ext
from ctx_helpers import _get_acc
from providers import get_provider
from providers.helpers import (
    _all_accounts, encode_cursor, decode_cursor,
    _inbox_page_key, _unread_summary_key, _invalidate_first_page,
    _inbox_manifest_key,
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
from cache_model_defs import InboxManifest, InboxPage, UnreadSummary

log = logging.getLogger(__name__)


@ext.panel(
    "inbox", slot="left", title="Mail", icon="Mail",
    refresh="on_event:mail.received,mail.archived,mail.deleted,mail.mail_action,mail.account_switched,mail.account_connected,mail.account_disconnected",
)
async def inbox_panel(
    ctx,
    folder: str = "INBOX",
    limit: int = 25,
    cursor: str = "",
    prev_cursor: str = "",
    page_num: int = 0,
    do_action: str = "",
    do_message_id: str = "",
    do_switch_account: str = "",
    **_unused_kwargs,  # absorb any stale `account=` the platform injects
):
    accounts = await _all_accounts(ctx)
    if not accounts:
        return ui.Empty(message="No email accounts connected")

    # ── Account switch: update store FIRST, then resolve from store ──────────
    # Never trust the `account` HTTP param — platform injects stale values
    # from previous paginated renders. Always resolve from is_active in store.
    if do_switch_account:
        await _switch_active_account(ctx, do_switch_account)
        cursor = ""
        prev_cursor = ""
        page_num = 0
        for _fkey in [f["key"] for f in FOLDERS]:
            await _invalidate_first_page(ctx, do_switch_account, _fkey)

    # Read active account purely from store — immune to platform param injection
    from providers.helpers import _active_account as _resolve_active
    acc = await _resolve_active(ctx, "")
    if not acc:
        return ui.Empty(message="No email account available")

    provider     = get_provider(acc)
    active_email = acc.get("email", "")

    # ── Inline single-message action ──────────────────────────────────────── #
    await _execute_panel_action(ctx, provider, acc, do_action, do_message_id)

    # ── Header ────────────────────────────────────────────────────────────── #
    account_info = ui.Stack([
        ui.Text(active_email[:32], variant="caption"),
        ui.Button("", icon="RefreshCw", variant="ghost", size="sm",
                   on_click=ui.Call("__panel__inbox", folder=folder, cursor="",
                                    prev_cursor="", page_num=0)),
    ], direction="horizontal", gap=1)

    folder_tabs = _build_folder_tabs(folder, active_email)

    # ── Load manifest (best-effort) ───────────────────────────────────────── #
    manifest: InboxManifest | None = None
    try:
        manifest = await ctx.cache.get(_inbox_manifest_key(active_email, folder), InboxManifest)
    except Exception:
        pass

    # Resolve effective cursor from manifest when possible
    if manifest and folder == "INBOX" and page_num < len(manifest.cursors):
        effective_cursor = manifest.cursors[page_num]
    else:
        effective_cursor = cursor

    # Compute total pages
    total_pages = 0
    if manifest and manifest.total > 0 and manifest.page_size > 0:
        total_pages = math.ceil(manifest.total / manifest.page_size)

    # ── Fetch inbox page ──────────────────────────────────────────────────── #
    cursor_data = decode_cursor(effective_cursor) if effective_cursor else None
    clamped     = max(1, min(limit, 100))

    async def _fetch_page() -> InboxPage:
        messages, next_cursor_data, has_more = await provider.fetch_page(
            ctx, acc, folder, clamped, cursor_data,
        )
        provider_key = acc.get("provider", "oauth")
        next_cur = encode_cursor(provider_key, next_cursor_data) or ""
        norm = []
        for m in messages:
            if "id" in m and "message_id" not in m:
                m = {**m, "message_id": m["id"]}
            norm.append(m)
        return InboxPage(
            account_id=active_email,
            folder=folder,
            cursor=effective_cursor or "",
            messages=norm,
            next_cursor=next_cur,
            has_more=bool(has_more),
            fetched_at=datetime.now(timezone.utc),
        )

    try:
        if do_switch_account:
            # Bypass cache entirely after account switch — get_or_fetch might
            # return a stale entry in the window between delete and new write.
            page = await _fetch_page()
        else:
            page = await ctx.cache.get_or_fetch(
                key=_inbox_page_key(active_email, folder, effective_cursor),
                model=InboxPage,
                fetcher=_fetch_page,
                ttl_seconds=60,
            )
            # Integrity guard: discard if cached for wrong account/folder.
            if page.account_id != active_email or page.folder != folder:
                page = await _fetch_page()
    except Exception as e:
        log.warning("inbox panel fetch_page failed folder=%s: %s", folder, e)
        return ui.Stack([
            account_info, folder_tabs,
            ui.Error(message=f"Failed to load {folder}: {e}"),
        ])

    messages    = page.messages
    next_cursor = page.next_cursor or None
    has_more    = page.has_more

    # ── Unread count ──────────────────────────────────────────────────────── #
    # Prefer manifest unread (fresh from skeleton) over separate cache entry
    if manifest and folder == "INBOX":
        unread_count = manifest.unread
    else:
        async def _fetch_unread() -> UnreadSummary:
            try:
                count = await provider.get_unread_count(ctx, acc, folder)
            except Exception:
                count = sum(1 for m in messages if m.get("unread"))
            return UnreadSummary(
                account_id=active_email, folder=folder, unread_count=int(count or 0))

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

    # Resolve prev_cursor from manifest when possible
    if manifest and folder == "INBOX" and page_num > 0 and page_num - 1 < len(manifest.cursors):
        effective_prev_cursor = manifest.cursors[page_num - 1]
    else:
        effective_prev_cursor = prev_cursor

    email_list = _build_email_list(
        messages, next_cursor, has_more,
        folder, active_email, unread_count,
        total=manifest.total if manifest else 0,
        current_cursor=effective_cursor,
        prev_cursor=effective_prev_cursor,
        page_num=page_num,
        total_pages=total_pages,
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
    return await build_add_account_panel(ctx, step, email, error)
