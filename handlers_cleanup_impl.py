"""Mail Client — inbox_cleanup and inbox_analytics implementation."""
from __future__ import annotations

from collections import defaultdict

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

    acc, provider = await _get_acc(ctx, account)
    if not acc:
        raise RuntimeError("No email account connected.")

    is_gmail = hasattr(provider, "search_ids_only")
    cat_map = _GMAIL_CATEGORY_MAP if is_gmail else _GENERIC_CATEGORY_MAP

    query_parts: list[str] = []

    for cat in categories:
        cat = cat.lower().strip()
        q = cat_map.get(cat, "")
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

    if len(query_parts) == 1:
        query = query_parts[0].strip("()")
    else:
        query = " OR ".join(query_parts)

    if older_than_days > 0:
        query = f"({query}) older_than:{older_than_days}d"

    return await impl_mark_all_matching(ctx, query=query, operation=operation, account=account)


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
