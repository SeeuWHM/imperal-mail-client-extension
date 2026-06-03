"""Mail Client · Smart Filters bar — left inbox panel, below folder tabs.

Clicking a filter loads filtered emails from ALL accounts directly in the left panel.
No delete buttons here — filter management is in the RIGHT panel Filters tab.
"""
from __future__ import annotations

import logging
from imperal_sdk import ui

FILTERS_COLLECTION = "mail_filters"
log = logging.getLogger("mail")


async def build_filters_bar(ctx, active_filter_id: str = "") -> ui.UINode | None:
    """Build the Smart Filters row for the current active account. Returns None if none saved."""
    try:
        from providers.helpers import _active_account
        acc = await _active_account(ctx, "")
        active_email = acc.get("email", "") if acc else ""
        page = await ctx.store.query(FILTERS_COLLECTION,
                                     where={"owner_id": ctx.user.imperal_id}, limit=20)
        # Show only filters for this account (or legacy filters with no account)
        page_data = [f for f in page.data
                     if not f.data.get("account_email") or
                     f.data.get("account_email") == active_email]
        if not page_data:
            return None

        buttons = []
        for f in page_data:
            name = f.data.get("name", "filter")
            is_active = f.id == active_filter_id

            buttons.append(ui.Button(
                f"◉ {name}",
                variant="primary" if is_active else "ghost",
                size="sm",
                on_click=ui.Call("__panel__inbox",
                                 filter_id=f.id,
                                 search_query="",
                                 page_cursor="",
                                 prev_cursor="",
                                 page_num=1),
            ))

        # Clear filter button — only shown when a filter is active
        if active_filter_id:
            buttons.append(ui.Button(
                "✕ clear",
                variant="ghost",
                size="sm",
                on_click=ui.Call("__panel__inbox",
                                 filter_id="",
                                 page_cursor="",
                                 prev_cursor="",
                                 page_num=1),
            ))

        return ui.Stack([
            ui.Divider(),
            ui.Text("Smart Filters", variant="caption"),
            ui.Stack(buttons, direction="h", wrap=True, gap=1),
        ], gap=1)

    except Exception as e:
        log.debug(f"filters_bar: {e}")
        return None
