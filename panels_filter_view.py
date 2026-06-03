"""Mail Client · Filter view helper — loads and renders smart filter results in inbox panel.

Loads filter criteria from store, runs impl_search across ALL connected accounts,
returns messages in the same format as inbox page messages.
"""
from __future__ import annotations

import logging
from handlers_inbox_impl import impl_search

log = logging.getLogger("mail")

_FILTERS_COLLECTION = "mail_filters"


def _build_filter_query(doc_data: dict) -> str:
    """Build Gmail-compatible search query from stored filter criteria."""
    parts = []
    from_emails = doc_data.get("criteria_from_emails") or []
    if from_emails:
        if len(from_emails) == 1:
            parts.append(f"from:{from_emails[0]}")
        else:
            or_clause = " OR ".join(f"from:{e}" for e in from_emails)
            parts.append(f"{{{or_clause}}}")
    elif doc_data.get("criteria_from"):
        parts.append(f"from:{doc_data['criteria_from']}")
    if doc_data.get("criteria_subject"):
        subj = doc_data["criteria_subject"]
        parts.append(f'subject:"{subj}"' if " " in subj else f"subject:{subj}")
    return " ".join(parts) if parts else ""


async def get_filter_messages(ctx, filter_id: str, max_results: int = 50) -> tuple[list[dict], str]:
    """Load filter and run cross-account search. Returns (messages, filter_name)."""
    try:
        uid = ctx.user.imperal_id
        # Resolve by ID or by name
        doc = None
        try:
            doc = await ctx.store.get(_FILTERS_COLLECTION, filter_id)
            if doc and doc.data.get("owner_id") != uid:
                doc = None
        except Exception:
            pass
        if not doc:
            page = await ctx.store.query(_FILTERS_COLLECTION, where={"owner_id": uid}, limit=20)
            for d in page.data:
                if d.data.get("name", "").lower() == filter_id.lower():
                    doc = d
                    break
        if not doc:
            return [], ""

        query = _build_filter_query(doc.data)
        if not query:
            return [], doc.data.get("name", "")

        # Search ALL connected accounts (account="" = all)
        result = await impl_search(ctx, query=query, max_results=max_results, account="")
        messages = result.results or []
        # Normalise message_id field
        for m in messages:
            if "id" in m and "message_id" not in m:
                m["message_id"] = m["id"]
        return messages, doc.data.get("name", "filter")
    except Exception as e:
        log.warning(f"filter_view: failed to load filter {filter_id}: {e}")
        return [], ""


async def render_filter_panel(ctx, filter_id: str,
                               filters_bar, build_email_list_fn,
                               inbox_limit: int = 25):
    """Render the full filter view for the inbox left panel.

    Called from inbox_panel when filter_id is set.
    Returns a ui.Stack with header + filter bar + email list.
    """
    from imperal_sdk import ui

    filter_msgs, filter_name = await get_filter_messages(ctx, filter_id)
    header = ui.Stack([
        ui.Text(f"Filter: {filter_name}", variant="caption"),
        ui.Button("", icon="X", variant="ghost", size="sm",
                  on_click=ui.Call("__panel__inbox", filter_id="",
                                   page_cursor="", page_num=1)),
    ], direction="h", gap=1)

    from providers.helpers import _active_account
    acc = await _active_account(ctx, "")
    active_email = acc.get("email", "") if acc else ""
    email_list = build_email_list_fn(filter_msgs[:inbox_limit], active_email, "INBOX")

    children = [header]
    if filters_bar:
        children.append(filters_bar)
    if filter_msgs:
        children.append(email_list)
    else:
        children.append(ui.Empty(
            message=f"No emails match filter '{filter_name}'", icon="Filter"))
    return ui.Stack(children, gap=1)
