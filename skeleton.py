"""Mail Client · Skeleton tools.

Per I-SKELETON-LLM-ONLY: the skeleton carries ONLY scalar fields for the
classifier envelope — no message lists, no blobs. Panel rendering fetches
directly from API on demand (one page, 25 messages) and caches the result
in ``ctx.cache`` for 90 s.

The skeleton does:
1. Surface ``unread_total`` + per-account ``unread_count`` for the classifier.
2. Diff against ``last_message_ids`` to fire ``ctx.notify()`` for new mail.

It does NOT pre-warm message lists and does NOT call ``ctx.skeleton.update()``.
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
    _invalidate_first_page,
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
                    await _invalidate_first_page(ctx, email, "INBOX")
                except Exception:
                    pass
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
    try:
        accounts = await _all_accounts(ctx)
        if not accounts:
            return ActionResult.success(data={}, summary="")
        total_unread = sum(int(a.get("unread_count", 0) or 0) for a in accounts)
        if total_unread == 0:
            return ActionResult.success(data={}, summary="")
        n_acc = len(accounts)
        pl_email = "s" if total_unread != 1 else ""
        if n_acc == 1:
            email = accounts[0].get("email", "")
            summary = f"{total_unread} unread email{pl_email} in {email}."
        else:
            pl_acc = "s" if n_acc != 1 else ""
            summary = f"{total_unread} unread email{pl_email} across {n_acc} account{pl_acc}."
        return ActionResult.success(
            data={"unread_total": total_unread, "accounts": n_acc},
            summary=summary,
        )
    except Exception:
        return ActionResult.success(data={}, summary="")
