"""Mail Client · Accounts Panel (right slot)."""
from __future__ import annotations

import logging

from imperal_sdk import ui

from providers.helpers import _all_accounts, _invalidate_first_page
from panels_inbox import FOLDERS, _switch_active_account
from handlers_connect import impl_disconnect

log = logging.getLogger(__name__)

PROVIDER_LABELS = {
    "oauth": "Google", "microsoft": "Microsoft",
    "yahoo": "Yahoo",  "imap": "IMAP",
}


async def build_accounts_panel(ctx, show_add: bool = False,
                                do_switch: str = "", do_remove: str = "") -> ui.UINode:
    if do_remove:
        try:
            await impl_disconnect(ctx, account=do_remove)
        except Exception as e:
            log.warning("remove account %s: %s", do_remove, e)

    if do_switch:
        await _switch_active_account(ctx, do_switch)
        for fkey in [f["key"] for f in FOLDERS]:
            await _invalidate_first_page(ctx, do_switch, fkey)

    accounts = await _all_accounts(ctx)

    if not accounts:
        return ui.Stack([
            ui.Empty(message="No email accounts connected", icon="Mail"),
            ui.Button("Add Account", icon="Plus", variant="outline",
                      on_click=ui.Call("__panel__add_account")),
        ])

    rows = []
    for acc in accounts:
        email     = acc.get("email", "?")
        provider  = acc.get("provider", "oauth")
        is_active = acc.get("is_active", False)
        label     = f"{email}  ·  {PROVIDER_LABELS.get(provider, 'Unknown')}"

        rows.append(ui.Stack([
            ui.Button(
                label,
                variant="primary" if is_active else "ghost",
                on_click=ui.Call("__panel__accounts", do_switch=email),
            ),
            ui.Badge("Active", color="green") if is_active else ui.Stack([]),
            ui.Button("", icon="X", variant="ghost", size="sm",
                      on_click=ui.Call("__panel__accounts", do_remove=email)),
        ], direction="horizontal", gap=2))

    return ui.Stack([
        ui.Header(text="Accounts", level=3),
        ui.Stack(rows, gap=2),
        ui.Divider(),
        ui.Button("Add Account", icon="Plus", variant="outline",
                  on_click=ui.Call("__panel__add_account")),
    ], gap=2, className="pb-4")
