"""Mail Client · Skeleton tools (SDK v3.x).

Per I-SKELETON-LLM-ONLY: the skeleton carries scalar fields for the classifier
envelope only — no message lists, no full inbox blobs. Panel rendering reads
from ``ctx.cache`` via ``inbox_page`` / ``unread_summary`` models.

The refresh tool continues to fetch the latest inbox so it can:
1. Surface ``unread_total`` + per-account ``unread_count`` for the classifier.
2. Diff against ``last_message_ids`` stored per-account (ctx.store) to fire
   ``ctx.notify(...)`` for genuinely new messages.
3. Cache page 1 + InboxManifest for true pagination in the inbox panel.

It does NOT call ``ctx.skeleton.update(...)`` — the kernel persists the
returned dict via the ``skeleton_save_section`` activity.
"""
from __future__ import annotations

import logging
import time as _time
from datetime import datetime, timezone

from imperal_sdk.chat.action_result import ActionResult

from app import ext

from providers import get_provider
from providers.helpers import (
    _all_accounts, _refresh_token_if_needed, COLLECTION, INBOX_FETCH_SIZE,
    _inbox_page_key, _inbox_manifest_key, _inbox_messages_key, encode_cursor,
)
from cache_model_defs import InboxManifest, InboxMessages, InboxPage
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

    for acc in accounts:
        email = acc.get("email", "")
        prev_ids = set(acc.get("last_message_ids", []) or [])

        try:
            acc = await _refresh_token_if_needed(ctx, acc)
            provider = get_provider(acc)

            # Get folder stats (total + unread) via dedicated API endpoint
            try:
                stats = await provider.get_folder_stats(ctx, acc, "INBOX")
                total = stats.get("total", 0)
                unread = int(stats.get("unread", 0))
            except Exception:
                total = 0
                unread = 0

            # Fetch page 1 via fetch_page (gives us next_cursor for manifest)
            messages, next_cursor_data, has_more = await provider.fetch_page(
                ctx, acc, "INBOX", INBOX_FETCH_SIZE, None)
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

            # Normalise message_id field
            norm = []
            for m in messages:
                if "id" in m and "message_id" not in m:
                    m = {**m, "message_id": m["id"]}
                norm.append(m)

            # Build page 1 cache entry
            provider_key = acc.get("provider", "oauth")
            next_cur = encode_cursor(provider_key, next_cursor_data) or ""
            page1 = InboxPage(
                account_id=email, folder="INBOX", cursor="",
                messages=norm, next_cursor=next_cur,
                has_more=bool(has_more),
                fetched_at=datetime.now(timezone.utc),
            )
            try:
                await ctx.cache.set(_inbox_page_key(email, "INBOX", ""), page1, ttl_seconds=120)
            except Exception as e:
                log.debug("skeleton: cache page1 failed for %s: %s", email, e)

            # Build and cache manifest
            cursors = [""]  # page 1 always has cursor ""
            if next_cur and has_more:
                cursors.append(next_cur)  # cursor for page 2 is known
            manifest = InboxManifest(
                account_id=email, folder="INBOX",
                total=total, unread=unread,
                page_size=INBOX_FETCH_SIZE,
                cursors=cursors,
                preloaded=1,
                fetched_at=datetime.now(timezone.utc),
            )
            try:
                await ctx.cache.set(
                    _inbox_manifest_key(email, "INBOX"), manifest, ttl_seconds=120)
            except Exception as e:
                log.debug("skeleton: cache manifest failed for %s: %s", email, e)

            # Pre-warm InboxMessages (flat list for ui.List native pagination).
            # Fetch up to 150 items (6 pages at 25 each). Page 1 is already in
            # `norm`; fetch up to 5 more pages sequentially.
            all_msgs = list(norm)
            cursor_data_pw = next_cursor_data
            for _ in range(11):  # up to 300 messages (200 initial + 11 × 25)
                if not cursor_data_pw or len(all_msgs) >= 300:
                    break
                try:
                    more, next_pw, has_pw = await get_provider(acc).fetch_page(
                        ctx, acc, "INBOX", 25, cursor_data_pw)
                    for m in more:
                        if "id" in m and "message_id" not in m:
                            m = {**m, "message_id": m["id"]}
                    all_msgs.extend(more)
                    if not has_pw or not next_pw:
                        break
                    cursor_data_pw = next_pw
                except Exception:
                    break
            try:
                # Store next_cursor so the panel can "load more" beyond 150
                final_cursor = encode_cursor(acc.get("provider", "oauth"), cursor_data_pw) if cursor_data_pw else ""
                inbox_msgs = InboxMessages(
                    account_id=email, folder="INBOX",
                    messages=all_msgs[:300],
                    total_in_folder=total,
                    unread_in_folder=unread,
                    next_cursor=final_cursor,
                    fetched_at=datetime.now(timezone.utc),
                )
                await ctx.cache.set(_inbox_messages_key(email, "INBOX"),
                                    inbox_msgs, ttl_seconds=120)
            except Exception as e:
                log.debug("skeleton: InboxMessages cache failed for %s: %s", email, e)

            try:
                await ctx.store.update(COLLECTION, acc["doc_id"], {
                    **{k: v for k, v in acc.items() if k != "doc_id"},
                    "last_fetched": int(_time.time()),
                    "unread_count": unread,
                    "last_message_ids": list(curr_ids),
                })
            except Exception:
                pass

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
        except Exception as e:
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
        ).model_dump(),
        summary=f"{unread_total} unread across {len(accounts)} account(s)",
    )


@ext.tool("skeleton_alert_mail_inbox_summary",
          description="Alert check for new unread emails.")
async def skeleton_alert_mail_inbox_summary(ctx) -> ActionResult:
    return ActionResult.success(data={}, summary="")
