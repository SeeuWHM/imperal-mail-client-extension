"""Mail Client · Smart Filters bar — rendered inside the left inbox panel.

Filter buttons switch the inbox panel into search mode using the filter's
criteria as a search_query — results appear IN THE PANEL, not in chat.
"""
from __future__ import annotations

import logging
from imperal_sdk import ui

FILTERS_COLLECTION = "mail_filters"

log = logging.getLogger("mail")


def _build_search_query(data: dict) -> str:
    """Build Gmail-compatible search query from filter criteria."""
    parts = []
    if data.get("criteria_from"):
        parts.append(f"from:{data['criteria_from']}")
    if data.get("criteria_subject"):
        subj = data["criteria_subject"]
        parts.append(f'subject:"{subj}"' if " " in subj else f"subject:{subj}")
    return " ".join(parts) if parts else data.get("name", "")


async def build_filters_bar(ctx, active_query: str = "") -> ui.UINode | None:
    """Build the Smart Filters row shown below folder tabs in the left panel.

    Returns None when no filters are saved (hides the section cleanly).
    Clicking a filter button sets search_query on the inbox panel so results
    appear directly in the panel list — no chat involved.
    Active filter is highlighted (variant=primary).
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
            query = _build_search_query(d)
            is_active = bool(active_query and active_query == query)

            # Clicking sets search_query on __panel__inbox — shows results in panel
            buttons.append(ui.Button(
                f"⊙ {name}",
                variant="primary" if is_active else "ghost",
                size="sm",
                on_click=ui.Call("__panel__inbox",
                                 folder="INBOX",
                                 search_query=query,
                                 page_cursor="",
                                 prev_cursor="",
                                 page_num=1),
            ))

        # "Clear filter" button appears when a filter is active
        clear_btn = None
        if active_query:
            clear_btn = ui.Button(
                "✕",
                variant="ghost",
                size="sm",
                on_click=ui.Call("__panel__inbox",
                                 folder="INBOX",
                                 search_query="",
                                 page_cursor="",
                                 prev_cursor="",
                                 page_num=1),
            )

        row_children = list(buttons)
        if clear_btn:
            row_children.append(clear_btn)

        return ui.Stack([
            ui.Divider(),
            ui.Text("Smart Filters", variant="caption"),
            ui.Stack(row_children, direction="h", wrap=True, gap=1),
        ], gap=1)

    except Exception as e:
        log.debug(f"filters_bar load failed: {e}")
        return None
