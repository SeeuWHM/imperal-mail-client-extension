"""Mail Client — inbox_cleanup, inbox_analytics, and unsubscribe implementation."""
from __future__ import annotations

import re
from collections import defaultdict

_UNSUB_URL_RE = re.compile(r'<(https?://[^>]+)>', re.IGNORECASE)
_UNSUB_MAILTO_RE = re.compile(r'<(mailto:[^>]+)>', re.IGNORECASE)

from handlers_manage_impl import impl_mark_all_matching, _get_acc
from handlers_inbox_impl import impl_top_senders
from schemas import BulkOperationResult

# ── Category → query maps ─────────────────────────────────────────────────────

_GMAIL_CATEGORY_MAP: dict[str, str] = {
    "promotions":  "category:promotions",
    "social":      "category:social",
    "updates":     "category:updates",
    "forums":      "category:forums",
    "newsletters": "list:true",
    "outreach":    "category:promotions",
    "spam":        "in:spam",
}

_GENERIC_CATEGORY_MAP: dict[str, str] = {
    "promotions":  "from:noreply OR from:no-reply OR from:newsletter",
    "social":      "from:facebook OR from:twitter OR from:linkedin OR from:instagram",
    "newsletters": "from:newsletter OR from:digest",
    "outreach":    "from:info OR from:hello OR from:team",
    "updates":     "from:noreply OR from:notifications",
    "forums":      "from:forum OR from:community",
    "spam":        "",   # spam folder handled separately
}

_VALID_CLEANUP_OPS = ("archive", "delete", "read", "star")


async def impl_inbox_cleanup(
    ctx,
    categories: list[str],
    from_senders: list[str],
    older_than_days: int,
    operation: str,
    account: str = "",
) -> BulkOperationResult:
    """Build provider-aware query from categories/senders, then run mark_all_matching."""
    if operation not in _VALID_CLEANUP_OPS:
        raise ValueError(
            f"Invalid operation '{operation}'. Use: {', '.join(_VALID_CLEANUP_OPS)}"
        )

    query = await _build_cleanup_query(ctx, categories, from_senders, older_than_days, account)
    return await impl_mark_all_matching(ctx, query=query, operation=operation, account=account)


async def _build_cleanup_query(ctx, categories: list, from_senders: list,
                                older_than_days: int, account: str = "") -> str:
    """Build provider-aware search query from cleanup params."""
    acc, provider = await _get_acc(ctx, account)
    is_gmail = acc and hasattr(provider, "search_ids_only")
    cat_map = _GMAIL_CATEGORY_MAP if is_gmail else _GENERIC_CATEGORY_MAP

    query_parts: list[str] = []
    for cat in categories:
        q = cat_map.get(cat.lower().strip(), "")
        if q:
            query_parts.append(f"({q})")
    for sender in from_senders:
        s = sender.strip()
        if s:
            query_parts.append(f"(from:{s})")

    if not query_parts:
        raise ValueError(
            "Specify at least one category or from_senders. "
            f"Supported categories: {', '.join(_GMAIL_CATEGORY_MAP)}"
        )
    query = query_parts[0].strip("()") if len(query_parts) == 1 else " OR ".join(query_parts)
    if older_than_days > 0:
        query = f"({query}) older_than:{older_than_days}d"
    return query


async def impl_unsubscribe_from_query(ctx, query: str, account: str = "") -> dict:
    """Find the most recent email matching query, extract List-Unsubscribe, call it."""
    from handlers_inbox_impl import impl_search

    try:
        acc, provider = await _get_acc(ctx, account)
        if not acc:
            return {"success": False, "url": "", "note": "No email account connected."}

        sr = await impl_search(ctx, query=query, max_results=1, account=account)
        if not sr.results:
            return {"success": False, "url": "", "note": "No email found matching the query."}

        message_id = (sr.results[0].get("message_id") or sr.results[0].get("id") or "").strip()
        if not message_id:
            return {"success": False, "url": "", "note": "Could not retrieve message ID."}

        unsub_header, post_data = await provider.get_list_unsubscribe(ctx, acc, message_id)

        if not unsub_header:
            return {"success": False, "url": "",
                    "note": "No List-Unsubscribe header. Manual unsubscribe required."}

        url_match = _UNSUB_URL_RE.search(unsub_header)
        if not url_match:
            mailto_match = _UNSUB_MAILTO_RE.search(unsub_header)
            note = (f"Unsubscribe via email: {mailto_match.group(1)}" if mailto_match
                    else f"Header found but no HTTP URL: {unsub_header}")
            return {"success": False, "url": unsub_header, "note": note}

        url = url_match.group(1)
        try:
            if post_data and "One-Click" in post_data:
                resp = await ctx.http.post(url, data={"List-Unsubscribe": "One-Click"},
                                           headers={"Content-Type": "application/x-www-form-urlencoded"},
                                           timeout=10.0)
            else:
                resp = await ctx.http.get(url, timeout=10.0)
            success = resp.status_code < 400
            return {"success": success, "url": url, "status": resp.status_code,
                    "note": "Unsubscribed." if success else f"HTTP {resp.status_code}"}
        except Exception as e:
            return {"success": False, "url": url, "note": f"HTTP call failed: {type(e).__name__}"}

    except Exception as e:
        return {"success": False, "url": "", "note": f"Error: {type(e).__name__}: {e}"}


async def impl_inbox_analytics(
    ctx,
    period_days: int = 90,
    group_by: str = "sender",
    limit: int = 10,
    account: str = "",
) -> list[dict]:
    """Inbox analytics — top senders or top domains over a period."""
    limit = min(max(limit, 1), 50)
    period_days = max(period_days, 1)

    if group_by == "domain":
        # Fetch more senders to get good domain coverage, then aggregate
        senders = await impl_top_senders(ctx, days=period_days, limit=50, account=account)
        domain_counts: dict[str, int] = defaultdict(int)
        for s in senders:
            email = s.get("email", "")
            domain = email.split("@")[-1].lower() if "@" in email else email
            domain_counts[domain] += s.get("count", 0)
        top = sorted(domain_counts.items(), key=lambda x: x[1], reverse=True)[:limit]
        return [{"sender": d, "email": f"*@{d}", "count": c} for d, c in top]

    # Default: group_by="sender"
    return await impl_top_senders(ctx, days=period_days, limit=limit, account=account)
