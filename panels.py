"""Mail Client · Panel handlers — email_viewer, accounts, compose, add_account."""
from __future__ import annotations

from imperal_sdk import ui

from app import ext
from panels_email_viewer import build_email_viewer
from panels_accounts import build_accounts_panel
from panels_add_account import build_add_account_panel
from panels_compose import build_compose_panel

import panels_inbox_panel  # noqa: F401 — registers @ext.panel("inbox")


@ext.panel("email_viewer", slot="center", title="Email", icon="Mail", center_overlay=True)
async def email_viewer_panel(ctx, message_id: str = "", account: str = "",
                              email_list_ids: str = "", current_index: int = 0,
                              folder: str = "INBOX"):
    if not message_id:
        return None  # center slot stays null → chat fills full width
    return await build_email_viewer(ctx, message_id, account, email_list_ids, current_index, folder)


@ext.panel(
    "accounts", slot="right", title="Accounts", icon="Users",
    refresh="on_event:account.switched,account.connected,account.disconnected",
)
async def accounts_panel(ctx, show_add: bool = False, do_switch: str = "", do_remove: str = ""):
    return await build_accounts_panel(ctx, show_add, do_switch, do_remove)


@ext.panel("compose", slot="center", title="Compose", icon="PenSquare",
           center_overlay=True, refresh="on_event:account.switched")
async def compose_panel(ctx, mode: str = "", message_id: str = "",
                         account: str = "", prefill_to: str = "",
                         prefill_subject: str = "", reply_all: str = ""):
    if not mode:
        return None  # only render when explicitly opened with mode=reply/forward/new
    reply_all_bool = str(reply_all).lower() in ("true", "1", "yes")
    return await build_compose_panel(ctx, mode, message_id, account,
                                      prefill_to, prefill_subject, reply_all_bool)


@ext.panel("add_account", slot="overlay", title="Add Account", icon="UserPlus",
           center_overlay=True)
async def add_account_panel(ctx, step: str = "providers", email: str = "", error: str = ""):
    return await build_add_account_panel(ctx, step, email, error)
