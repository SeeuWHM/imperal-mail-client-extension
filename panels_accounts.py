"""Mail Client · Accounts Panel (right slot, default view)."""
from __future__ import annotations

import logging

from imperal_sdk import ui

from providers.helpers import _all_accounts

log = logging.getLogger(__name__)

PROVIDER_LABELS = {
    "oauth": "Google", "microsoft": "Microsoft",
    "yahoo": "Yahoo",  "imap": "IMAP",
}


async def build_accounts_panel(ctx, show_add: bool = False) -> ui.UINode:
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
            # Call __panel__inbox with do_switch_account so the inbox panel:
            # 1. Updates is_active in the store (previously used fn switch_account which
            #    went through DirectCallWorkflow — no event published, left panel ignored)
            # 2. Re-renders the inbox list for the switched account immediately
            on_click=ui.Call("__panel__inbox", do_switch_account=email),
        ))

    return ui.Stack([
        ui.Header(text="Accounts", level=3),
        ui.List(items=items),
        ui.Divider(),
        ui.Button("Add Account", icon="Plus", variant="outline",
                  on_click=ui.Call("__panel__add_account")),
    ], gap=2, className="pb-4")
