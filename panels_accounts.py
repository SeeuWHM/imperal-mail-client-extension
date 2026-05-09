"""Mail Client · Accounts Panel (right slot)."""
from __future__ import annotations

import logging

from imperal_sdk import ui

from providers.helpers import _all_accounts

log = logging.getLogger(__name__)

PROVIDER_LABELS = {
    "oauth": "Google", "microsoft": "Microsoft",
    "yahoo": "Yahoo",  "imap": "IMAP",
}


async def build_accounts_panel(ctx, show_add: bool = False,
                                do_switch: str = "", do_remove: str = "") -> ui.UINode:
    # Legacy params kept for compat — switching and removal now go through
    # fn_switch_account / fn_disconnect chat functions via ui.Call which
    # return refresh_panels=["inbox","accounts"] so both panels update instantly.
    accounts = await _all_accounts(ctx)

    if not accounts:
        return ui.Stack([
            ui.Empty(message="No email accounts connected", icon="Mail"),
            ui.Button("Add Account", icon="Plus", variant="outline",
                      on_click=ui.Call("__panel__add_account")),
        ])

    items = []
    for acc in accounts:
        email     = acc.get("email", "?")
        provider  = acc.get("provider", "oauth")
        is_active = acc.get("is_active", False)
        initial   = email[0].upper() if email else "?"

        items.append(ui.ListItem(
            id=email,
            title=email,
            subtitle=PROVIDER_LABELS.get(provider, "Unknown"),
            avatar=ui.Avatar(fallback=initial, size="sm"),
            badge=ui.Badge("Active", color="green") if is_active else None,
            on_click=ui.Call("switch_account", account=email),
            actions=[{
                "icon":     "Trash2",
                "on_click": ui.Call("disconnect", account=email),
            }],
        ))

    return ui.Stack([
        ui.Header(text="Accounts", level=3),
        ui.List(items=items),
        ui.Divider(),
        ui.Button("Add Account", icon="Plus", variant="outline",
                  on_click=ui.Call("__panel__add_account")),
    ], gap=2, className="pb-4")
