"""Mail Client · Smart Filters bar — shown in left inbox panel below folder tabs.

Clicking a filter name calls apply_filter in chat (results appear in chat).
Each filter row has a ✕ delete button on the right.
"""
from __future__ import annotations

import logging
from imperal_sdk import ui

FILTERS_COLLECTION = "mail_filters"

log = logging.getLogger("mail")


async def build_filters_bar(ctx, active_query: str = "") -> ui.UINode | None:
    """Build the Smart Filters row. Returns None when no filters saved."""
    try:
        page = await ctx.store.query(FILTERS_COLLECTION,
                                     where={"owner_id": ctx.user.imperal_id}, limit=10)
        if not page.data:
            return None

        rows = []
        for f in page.data:
            d = f.data
            name = d.get("name", "filter")

            # Filter name — calls apply_filter in chat (shows results there)
            name_chip = ui.Button(
                f"◉ {name}",
                variant="ghost",
                size="sm",
                on_click=ui.Call("apply_filter", filter_id=f.id),
            )
            # ✕ — deletes the filter without affecting panel view
            del_btn = ui.Button(
                "✕",
                variant="ghost",
                size="sm",
                on_click=ui.Call("delete_filter", filter_id=f.id),
            )
            rows.append(ui.Stack([name_chip, del_btn], direction="h", gap=0))

        return ui.Stack([
            ui.Divider(),
            ui.Text("Smart Filters", variant="caption"),
            *rows,
        ], gap=1)

    except Exception as e:
        log.debug(f"filters_bar load failed: {e}")
        return None
