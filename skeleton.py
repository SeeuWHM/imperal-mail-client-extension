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

from imperal_sdk.chat.action_result import ActionResult

from app import ext

from cache_model_defs import InboxMessages
from providers import get_provider
from providers.helpers import (
    _all_accounts, _inbox_messages_key, _refresh_token_if_needed,
    COLLECTION, INBOX_FETCH_SIZE, encode_cursor,
)
from schemas import InboxSummary, PerAccountUnread

log = logging.getLogger("mail")


# ─── Skeleton ─────────────────────────────────────────────────────────── #

@ext.skeleton("mail_inbox_summary", ttl=60, alert=True,
              description="Per-account unread summary for classifier envelope + new-mail alerts.")
async def skeleton_refresh_mail_inbox_summary(ctx) -> ActionResult:
    accounts = await _all_accounts(ctx)
    if not accounts:
        return ActionResult.success(
            data=InboxSummary(accounts_connected=0, unread_total=0, per_account=[]).model_dump(),
            summary="0 unread, 0 accounts connected",
        )

    per_account: list[dict] = []
    unread_total = 0
    # Preview fields only — no body, no html. LLM sees these via classifier envelope.
    _PREVIEW_KEYS = {"message_id", "subject", "from", "date", "snippet", "unread", "starred"}
    recent_messages: list[dict] = []

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
            per_account.append({
                "email": email,
                "unread_count": unread,
                "message_count": len(messages),
            })

            # Collect previews from the first account that succeeds.
            # One page worth (INBOX_FETCH_SIZE) — subject/from/date/snippet only.
            if not recent_messages and messages:
                recent_messages = [
                    {k: m.get(k) for k in _PREVIEW_KEYS if m.get(k) is not None}
                    for m in messages
                ]

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
                "unread_count": int(acc.get("unread_count", 0)),
                "message_count": 0,
                "error": str(e)[:120],
            })
            unread_total += int(acc.get("unread_count", 0))

    return ActionResult.success(
        data=InboxSummary(
            accounts_connected=len(accounts),
            unread_total=unread_total,
            per_account=per_account,
            recent_messages=recent_messages,
        ).model_dump(),
        summary=f"{unread_total} unread across {len(accounts)} account(s)",
    )


@ext.tool("skeleton_alert_mail_inbox_summary",
          description="Alert check for new unread emails.")
async def skeleton_alert_mail_inbox_summary(ctx) -> ActionResult:
    """Lightweight alert check — reads last-known unread counts from store (no API calls).
    The kernel uses the returned unread_total for badge display and push-notification gating."""
    try:
        accounts = await _all_accounts(ctx)
        unread_total = sum(int(a.get("unread_count", 0)) for a in accounts)
        per_account  = [
            {"email": a.get("email", ""), "unread_count": int(a.get("unread_count", 0))}
            for a in accounts
        ]
        summary = f"{unread_total} unread" if unread_total else "0 unread"
        return ActionResult.success(
            data={"unread_total": unread_total, "per_account": per_account},
            summary=summary,
        )
    except Exception as e:
        log.debug("skeleton_alert failed: %s", e)
        return ActionResult.success(data={"unread_total": 0, "per_account": []}, summary="")
