"""Mail Client · Skeleton tools.

The skeleton does:
1. Surface ``unread_total`` + per-account ``unread_count`` for the classifier.
2. Diff against ``last_message_ids`` to fire ``ctx.notify()`` for new mail.
3. Write first page of INBOX to ctx.cache so the panel opens instantly (0 extra API calls).
"""
from __future__ import annotations

import asyncio
import logging
import time as _time
from datetime import datetime, timezone

from app import ext

from cache_model_defs import InboxMessages
from providers import get_provider
from providers.helpers import (
    _all_accounts, _inbox_messages_key, _refresh_token_if_needed,
    COLLECTION, INBOX_FETCH_SIZE, encode_cursor,
)

log = logging.getLogger("mail")


# ─── Skeleton ─────────────────────────────────────────────────────────── #

@ext.skeleton("mail_inbox_summary", ttl=60, alert=True,
              description="Per-account unread summary for classifier envelope + new-mail alerts.")
async def skeleton_refresh_mail_inbox_summary(ctx) -> dict:
    accounts = await _all_accounts(ctx)
    if not accounts:
        return {"response": {
            "unread_total": 0, "accounts_connected": 0, "per_account": [],
            "active_account": "", "filter_count": 0, "rule_count": 0,
        }}

    per_account: list[dict] = []
    unread_total = 0

    for acc in accounts:
        email = acc.get("email", "")
        prev_ids = set(acc.get("last_message_ids", []) or [])

        try:
            acc = await asyncio.wait_for(_refresh_token_if_needed(ctx, acc), timeout=5.0)
            provider = get_provider(acc)

            # Get folder stats (total + unread) via dedicated API endpoint
            try:
                stats = await asyncio.wait_for(
                    provider.get_folder_stats(ctx, acc, "INBOX"), timeout=5.0)
                total = stats.get("total", 0)
                unread = int(stats.get("unread", 0))
            except (asyncio.TimeoutError, Exception):
                total = 0
                unread = 0

            # Fetch page 1 via fetch_page (gives us message IDs for new-mail detection)
            messages, next_cursor_data, has_more = await asyncio.wait_for(
                provider.fetch_page(ctx, acc, "INBOX", INBOX_FETCH_SIZE, None),
                timeout=10.0,
            )
            curr_ids = {
                m.get("id", m.get("message_id", ""))
                for m in messages
                if m.get("id") or m.get("message_id")
            }
            truly_new = curr_ids - prev_ids

            # Fall back to counting unread from messages if stats returned 0
            if unread == 0:
                unread = sum(1 for m in messages if m.get("unread"))

            unread_total += unread
            # Use total from get_folder_stats (real mailbox total, e.g. 18624+).
            # Falls back to len(messages) only if stats unavailable.
            real_total = int(total) if total and total > 0 else len(messages)
            per_account.append({
                "email": email,
                "unread_count": unread,
                "is_active": bool(acc.get("is_active", False)),
            })

            try:
                await ctx.store.update(COLLECTION, acc["doc_id"], {
                    **{k: v for k, v in acc.items() if k != "doc_id"},
                    "last_fetched": int(_time.time()),
                    "unread_count": unread,
                    "last_message_ids": list(curr_ids),
                })
            except Exception:
                pass

            # Write first inbox page to cache — panel reads this instantly, no extra API call.
            try:
                _normalized = [
                    {**m, "message_id": m["id"]} if "id" in m and "message_id" not in m else m
                    for m in messages
                ]
                _next_cursor = ""
                if has_more and next_cursor_data:
                    _next_cursor = encode_cursor(
                        acc.get("provider", "oauth"), next_cursor_data, account=email
                    ) or ""
                await ctx.cache.set(
                    _inbox_messages_key(email, "INBOX"),
                    InboxMessages(
                        account_id=email, folder="INBOX",
                        messages=_normalized,
                        total_in_folder=total,
                        unread_in_folder=unread,
                        next_cursor=_next_cursor,
                        fetched_at=datetime.now(timezone.utc),
                    ),
                    ttl_seconds=60,
                )
            except Exception as e:
                log.debug("skeleton cache write failed %s: %s", email, e)

            if truly_new:
                try:
                    new_msgs = [
                        m for m in messages
                        if m.get("id") in truly_new or m.get("message_id") in truly_new
                    ]
                    subjects = ", ".join(
                        f'"{m.get("subject", "(no subject)")}"' for m in new_msgs[:2]
                    )
                    await ctx.notify(
                        f"New mail — {email}: {len(truly_new)} new. {subjects}"
                    )
                except Exception:
                    pass
        except (asyncio.TimeoutError, Exception) as e:
            log.error(f"Mail refresh error {email}: {e}")
            # Best-effort fallback — preserve last known per-account unread.
            per_account.append({
                "email": email,
                "unread_count": int(acc.get("unread_count", 0) or 0),
                "is_active": bool(acc.get("is_active", False)),
            })
            unread_total += int(acc.get("unread_count", 0) or 0)

    # Build per_account as plain dicts — no Pydantic objects, no model_dump()
    active_account = ""
    pa_list = []
    for p in per_account:
        email = str(p.get("email") or "")
        unread_count = int(p.get("unread_count") or 0)
        is_active = bool(p.get("is_active"))
        if is_active and not active_account:
            active_account = email
        pa_list.append({"email": email, "unread_count": unread_count, "is_active": is_active})
    if not active_account and pa_list:
        active_account = pa_list[0]["email"]

    # counts of configured filters and rules via ctx.store.query
    filter_count = 0
    rule_count = 0
    try:
        fpage = await ctx.store.query("mail_filters",
                                      where={"owner_id": ctx.user.imperal_id}, limit=1)
        filter_count = int(getattr(fpage, "total", 0) or 0)
    except Exception:
        pass
    try:
        rpage = await ctx.store.query("mail_rules",
                                      where={"owner_id": ctx.user.imperal_id,
                                             "enabled": True}, limit=1)
        rule_count = int(getattr(rpage, "total", 0) or 0)
    except Exception:
        pass

    return {"response": {
        "unread_total": int(unread_total),
        "accounts_connected": int(len(accounts)),
        "per_account": pa_list,
        "active_account": str(active_account),
        "filter_count": int(filter_count),
        "rule_count": int(rule_count),
    }}


@ext.tool("skeleton_alert_mail_inbox_summary",
          description="Alert check for new unread emails — fires when unread count changes.")
async def skeleton_alert_mail_inbox_summary(ctx,
                                             old: dict | None = None,
                                             new: dict | None = None) -> dict:
    """Compare old vs new skeleton snapshot — return notification string if unread changed."""
    try:
        if not new:
            return {"response": ""}
        new_unread = int(new.get("unread_total") or 0)
        old_unread = int((old or {}).get("unread_total") or 0)
        if new_unread > old_unread:
            diff = new_unread - old_unread
            return {"response": f"{diff} new unread email{'s' if diff != 1 else ''}"}
        return {"response": ""}
    except Exception as e:
        log.debug("skeleton_alert failed: %s", e)
        return {"response": ""}
