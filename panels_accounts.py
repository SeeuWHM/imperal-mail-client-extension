"""Mail Client · Accounts Panel (right slot)."""
from __future__ import annotations

import logging

from imperal_sdk import ui

from providers.helpers import _all_accounts, _invalidate_first_page
from panels_inbox import FOLDERS, _switch_active_account

log = logging.getLogger(__name__)

PROVIDER_LABELS = {
    "oauth": "Google", "microsoft": "Microsoft",
    "yahoo": "Yahoo",  "imap": "IMAP",
}


async def build_accounts_panel(ctx, show_add: bool = False,
                                do_switch: str = "") -> ui.UINode:
    # Handle account switch directly here so Active badge updates immediately
    # (without waiting for interval — switch updates store, then we re-read it)
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

    items = []
    for acc in accounts:
        email     = acc.get("email", "?")
        provider  = acc.get("provider", "oauth")
        is_active = acc.get("is_active", False)
        initial   = email[0].upper() if email else "?"

        # ALL params passed explicitly so the platform can't inject stale
        # cursor/page_num/account from a previous paginated inbox render.
        items.append(ui.ListItem(
            id=email,
            title=email,
            subtitle=PROVIDER_LABELS.get(provider, "Unknown"),
            avatar=ui.Avatar(fallback=initial, size="sm"),
            badge=ui.Badge("Active", color="green") if is_active else None,
            on_click=ui.Call("__panel__inbox",
                             do_switch_account=email,
                             folder="INBOX",
                             cursor="", prev_cursor="", page_num=0),
        ))

    return ui.Stack([
        ui.Header(text="Accounts", level=3),
        ui.List(items=items),
        ui.Divider(),
        ui.Button("Add Account", icon="Plus", variant="outline",
                  on_click=ui.Call("__panel__add_account")),
        # After switching in accounts panel, user taps the active account
        # to open its inbox. Or inbox auto-refreshes on its next event.
    ], gap=2, className="pb-4")
