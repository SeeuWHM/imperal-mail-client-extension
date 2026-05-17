"""Mail Client · Inline UI builders for ActionResult.ui chat responses."""
from __future__ import annotations

from imperal_sdk import ui


def _inbox_ui(messages: list, folder: str = "inbox") -> ui.UINode:
    """DataTable preview of inbox/folder messages rendered inline in chat."""
    if not messages:
        return ui.Empty(message=f"No messages in {folder}", icon="Mail")
    rows = [
        {
            "from":    (m.get("from") or "?")[:35],
            "subject": (m.get("subject") or "(no subject)")[:55],
            "date":    (m.get("date") or "")[:10],
            "status":  "unread" if m.get("unread") else "read",
        }
        for m in messages[:15]
    ]
    return ui.DataTable(
        columns=[
            ui.DataColumn("from",    "From",    sortable=False, width="25%"),
            ui.DataColumn("subject", "Subject", sortable=False, width="50%"),
            ui.DataColumn("date",    "Date",    sortable=False, width="15%"),
            ui.DataColumn("status",  "Status",  sortable=False, width="10%"),
        ],
        rows=rows,
    )


def _email_ui(body) -> ui.UINode:
    """KeyValue header block + body snippet rendered inline in chat."""
    kv = [{"key": "From", "value": (body.from_ or "?")[:60]}]
    if body.to:
        kv.append({"key": "To", "value": body.to[:60]})
    if body.cc:
        kv.append({"key": "CC", "value": body.cc[:60]})
    kv.append({"key": "Date",    "value": body.date    or "—"})
    kv.append({"key": "Subject", "value": body.subject or "(no subject)"})

    text    = (body.body or "").strip()
    snippet = text[:400] + "…" if len(text) > 400 else text

    children: list = [ui.KeyValue(items=kv, columns=1)]
    if body.attachments:
        n = len(body.attachments)
        children.append(ui.Alert(
            message=f"{n} attachment{'s' if n > 1 else ''}",
            type="info",
        ))
    if snippet:
        children.append(ui.Divider())
        children.append(ui.Markdown(content=snippet))

    return ui.Stack(children, gap=2)


def _search_ui(results: list, query: str) -> ui.UINode:
    """DataTable of search hits rendered inline in chat."""
    if not results:
        return ui.Empty(message=f'No results for "{query}"', icon="Search")
    rows = [
        {
            "from":    (m.get("from") or "?")[:30],
            "subject": (m.get("subject") or "(no subject)")[:55],
            "date":    (m.get("date") or "")[:10],
        }
        for m in results[:15]
    ]
    return ui.DataTable(
        columns=[
            ui.DataColumn("from",    "From",    sortable=False, width="25%"),
            ui.DataColumn("subject", "Subject", sortable=False, width="60%"),
            ui.DataColumn("date",    "Date",    sortable=False, width="15%"),
        ],
        rows=rows,
    )
