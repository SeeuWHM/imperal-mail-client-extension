"""Mail Client · Skeleton tools (SDK v3.x).

Per I-SKELETON-LLM-ONLY: the skeleton carries scalar fields for the classifier
envelope only — no message lists, no full inbox blobs. Panel rendering reads
from ``ctx.cache`` via ``inbox_page`` / ``unread_summary`` models.

The refresh tool continues to fetch the latest inbox so it can:
1. Surface ``unread_total`` + per-account ``unread_count`` for the classifier.
2. Diff against ``last_message_ids`` stored per-account (ctx.store) to fire
   ``ctx.notify(...)`` for genuinely new messages.

It does NOT call ``ctx.skeleton.update(...)`` — the kernel persists the
returned dict via the ``skeleton_save_section`` activity.
"""
from __future__ import annotations

import logging
import time as _time

from imperal_sdk.chat.action_result import ActionResult

from app import ext

from providers import get_provider
from providers.helpers import _all_accounts, _refresh_token_if_needed, COLLECTION, INBOX_FETCH_SIZE

log = logging.getLogger("mail")


# ─── Skeleton ─────────────────────────────────────────────────────────── #

@ext.skeleton("mail_inbox_summary", ttl=60, alert=True,
              description="Per-account unread summary for classifier envelope + new-mail alerts.")
async def skeleton_refresh_mail_inbox_summary(ctx, **kwargs) -> ActionResult:
    accounts = await _all_accounts(ctx)
    if not accounts:
        return ActionResult.success(data={
            "accounts_connected": 0,
            "unread_total": 0,
            "per_account": [],
        })

    per_account: list[dict] = []
    unread_total = 0

    for acc in accounts:
        email = acc.get("email", "")
        prev_ids = set(acc.get("last_message_ids", []) or [])

        try:
            acc = await _refresh_token_if_needed(ctx, acc)
            result = await get_provider(acc).fetch_inbox(ctx, acc, INBOX_FETCH_SIZE)
            messages = result.get("messages", [])
            unread = int(result.get("unread_count", 0))
            curr_ids = {m["id"] for m in messages if m.get("id")}
            truly_new = curr_ids - prev_ids

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
                    new_msgs = [m for m in messages if m.get("id") in truly_new]
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

    return ActionResult.success(data={
        "accounts_connected": len(accounts),
        "unread_total": unread_total,
        "per_account": per_account,
    })


@ext.tool("skeleton_alert_mail_inbox_summary", action_type="read",
          description="Alert check for new unread emails.")
async def skeleton_alert_mail_inbox_summary(ctx, **kwargs) -> ActionResult:
    return ActionResult.success(data={})
