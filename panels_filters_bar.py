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
    """Build the Smart Filters dropdown for the current active account."""
    try:
        from providers.helpers import _active_account
        acc = await _active_account(ctx, "")
        active_email = acc.get("email", "") if acc else ""
        page = await ctx.store.query(FILTERS_COLLECTION,
                                     where={"owner_id": ctx.user.imperal_id}, limit=20)
        page_data = [f for f in page.data
                     if not f.data.get("account_email") or
                     f.data.get("account_email") == active_email]
        if not page_data:
            return None

        options = [{"value": f.id, "label": f.data.get("name", "filter")}
                   for f in page_data]

        row = [
            ui.Form(
                children=[
                    ui.Select(
                        options=options,
                        value=active_filter_id or "",
                        param_name="filter_id",
                        placeholder="◉ Smart filters…",
                    ),
                ],
                action="__panel__inbox",
                submit_label="Apply",
                defaults={
                    "search_query": "",
                    "page_cursor": "",
                    "prev_cursor": "",
                    "page_num": 1,
                },
            ),
        ]

        if active_filter_id:
            row.append(ui.Button(
                "Clear", icon="X", variant="ghost", size="sm",
                on_click=ui.Call("__panel__inbox",
                                 filter_id="", search_query="",
                                 page_cursor="", prev_cursor="", page_num=1),
            ))

        return ui.Stack([
            ui.Divider(),
            ui.Stack(row, direction="h", gap=1, align="center"),
        ], gap=1)

    except Exception as e:
        log.debug(f"filters_bar: {e}")
        return None
