"""Mail Client · Skeleton tools.

The skeleton does:
1. Surface a 5-field classifier envelope of READ-query counts (docs recipe
   ``recipes/skeleton-data-surface`` — counts + per-item array ≤5):
   ``active_account``, ``unread_total``, ``today_total``, ``total_all``,
   ``per_account`` [≤5 {email, total, unread, spam, archive}].
   Counts come from ``provider.get_counts`` / ``provider.get_today_count``
   (normalized across Google / Microsoft / IMAP) — NOT from search, so the
   brain answers "сколько всего / непрочитано / спам / архив / сегодня" directly.
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
    uid = ctx.user.imperal_id
    if not uid:
        return {"response": {"note": "no user on context"}}

    accounts = await _all_accounts(ctx)
    if not accounts:
        return {"response": {
            "active_account": "", "unread_total": 0, "today_total": 0,
            "total_all": 0, "per_account": [],
        }}

    per_account: list[dict] = []
    unread_total = 0
    today_total = 0
    total_all = 0

    for acc in accounts:
        email = acc.get("email", "")
        prev_ids = set(acc.get("last_message_ids", []) or [])

        try:
            acc = await asyncio.wait_for(_refresh_token_if_needed(ctx, acc), timeout=5.0)
            provider = get_provider(acc)

            # Mailbox counts {total, inbox_total, unread, spam, archive} — normalized
            # per provider (Gmail profile / Graph $count / IMAP STATUS), not search.
            try:
                counts = await asyncio.wait_for(provider.get_counts(ctx, acc), timeout=8.0)
            except (asyncio.TimeoutError, Exception):
                counts = {}
            try:
                today = int(await asyncio.wait_for(
                    provider.get_today_count(ctx, acc), timeout=8.0))
            except (asyncio.TimeoutError, Exception):
                today = 0

            unread        = int(counts.get("unread", 0) or 0)
            total_mailbox = int(counts.get("total", 0) or 0)
            inbox_total   = int(counts.get("inbox_total", 0) or 0)
            spam          = int(counts.get("spam", 0) or 0)
            archive       = int(counts.get("archive", 0) or 0)

            # Fetch page 1 — message IDs for new-mail detection + cache warmup.
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

            # Fallbacks if the counts API returned nothing.
            if unread == 0:
                unread = sum(1 for m in messages if m.get("unread"))
            if inbox_total == 0:
                inbox_total = len(messages)
            if total_mailbox == 0:
                total_mailbox = inbox_total

            unread_total += unread
            today_total  += today
            total_all    += total_mailbox
            per_account.append({
                "email":     email,
                "total":     total_mailbox,
                "unread":    unread,
                "spam":      spam,
                "archive":   archive,
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
                        total_in_folder=inbox_total,
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
            _last_unread = int(acc.get("unread_count", 0) or 0)
            per_account.append({
                "email": email, "total": 0, "unread": _last_unread,
                "spam": 0, "archive": 0,
                "is_active": bool(acc.get("is_active", False)),
            })
            unread_total += _last_unread

    # per_account — count cards {email, total, unread, spam, archive}. The active
    # mailbox is surfaced once as the top-level `active_account`; the per-item
    # is_active flag is used only to derive it, then dropped (≤5 fields/item).
    active_account = ""
    pa_list = []
    for p in per_account:
        p_email = str(p.get("email") or "")
        if bool(p.get("is_active")) and not active_account:
            active_account = p_email
        pa_list.append({
            "email":   p_email,
            "total":   int(p.get("total") or 0),
            "unread":  int(p.get("unread") or 0),
            "spam":    int(p.get("spam") or 0),
            "archive": int(p.get("archive") or 0),
        })
    if not active_account and pa_list:
        active_account = pa_list[0]["email"]

    return {"response": {
        "active_account": str(active_account),
        "unread_total":   int(unread_total),
        "today_total":    int(today_total),
        "total_all":      int(total_all),
        "per_account":    pa_list,
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
