"""Mail Client · Smart Filters bar — rendered inside the left inbox panel."""
from __future__ import annotations

import logging
from imperal_sdk import ui

FILTERS_COLLECTION = "mail_filters"
COLOR_MAP = {
    "blue": "blue", "green": "green", "red": "red",
    "yellow": "yellow", "purple": "purple", "orange": "orange",
}

log = logging.getLogger("mail")


async def build_filters_bar(ctx) -> ui.UINode | None:
    """Build the Smart Filters row shown below folder tabs in the left panel.

    Returns None when no filters are saved (hides the section cleanly).
    Each filter button triggers apply_filter() in chat to show results.
    """
    try:
        page = await ctx.store.query(FILTERS_COLLECTION,
                                     where={"owner_id": ctx.user.imperal_id}, limit=10)
        if not page.data:
            return None

        buttons = []
        for f in page.data:
            d = f.data
            name  = d.get("name", "filter")
            color = COLOR_MAP.get(d.get("color", "blue"), "blue")
            # Clicking a filter runs apply_filter in chat (results appear in chat)
            buttons.append(ui.Button(
                f"◉ {name}",
                variant="ghost",
                size="sm",
                on_click=ui.Call("apply_filter", filter_id=f.id),
            ))

        return ui.Stack([
            ui.Divider(),
            ui.Text("Smart Filters", variant="caption"),
            ui.Stack(buttons, direction="h", wrap=True, gap=1),
        ], gap=1)
    except Exception as e:
        log.debug(f"filters_bar load failed: {e}")
        return None
