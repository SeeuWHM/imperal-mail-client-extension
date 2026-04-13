"""Mail Client · Skeleton tools."""
from __future__ import annotations

import logging
import time as _time

from app import ext

from providers import get_provider
from providers.helpers import _all_accounts, _refresh_token_if_needed, COLLECTION, SKELETON_INBOX, INBOX_FETCH_SIZE

log = logging.getLogger("mail")


# ─── Skeleton ─────────────────────────────────────────────────────────── #

@ext.tool("skeleton_refresh_mail", description="Background inbox cache refresh for all accounts.")
async def skeleton_refresh_mail(ctx, **kwargs) -> dict:
    accounts = await _all_accounts(ctx)
    if not accounts:
        return {"response": {}}
    try:
        raw = await ctx.skeleton.get(SKELETON_INBOX) or {}
        prev_cache = {k: v for k, v in raw.items() if isinstance(v, dict) and "messages" in v}
    except Exception:
        prev_cache = {}

    full_cache: dict = {}
    for acc in accounts:
        email = acc.get("email", "")
        try:
            acc = await _refresh_token_if_needed(ctx, acc)
            result = await get_provider(acc).fetch_inbox(ctx, acc, INBOX_FETCH_SIZE)
            messages = result.get("messages", [])
            unread = result.get("unread_count", 0)
            prev_ids = {m["id"] for m in prev_cache.get(email, {}).get("messages", [])}
            curr_ids = {m["id"] for m in messages}
            truly_new = len(curr_ids - prev_ids)
            full_cache[email] = {"messages": messages, "unread_count": unread, "last_fetched": int(_time.time())}
            try:
                await ctx.store.update(COLLECTION, acc["doc_id"], {
                    **{k: v for k, v in acc.items() if k != "doc_id"},
                    "last_fetched": int(_time.time()), "unread_count": unread, "last_message_ids": list(curr_ids),
                })
            except Exception:
                pass
            if truly_new > 0:
                try:
                    new_msgs = [m for m in messages if m["id"] in (curr_ids - prev_ids)]
                    await ctx.notify(
                        title=f"New mail — {email}",
                        body=f"{truly_new} new: " + ", ".join(f'"{m.get("subject", "(no subject)")}"' for m in new_msgs[:2]),
                    )
                except Exception:
                    pass
        except Exception as e:
            log.error(f"Mail refresh error {email}: {e}")
            if email in prev_cache:
                full_cache[email] = prev_cache[email]
            else:
                try:
                    live = await ctx.skeleton.get(SKELETON_INBOX)
                    if live and email in live:
                        full_cache[email] = live[email]
                except Exception:
                    pass

    await ctx.skeleton.update(SKELETON_INBOX, full_cache)

    return {"response": full_cache}


@ext.tool("skeleton_alert_mail", description="Alert check for new unread emails.")
async def skeleton_alert_mail(ctx, **kwargs) -> dict:
    return {"response": {}}


# ─── Legacy Aliases ───────────────────────────────────────────────────── #

@ext.tool("skeleton_refresh_gmail", description="Legacy alias → skeleton_refresh_mail.")
async def skeleton_refresh_gmail_alias(ctx, **kwargs) -> dict:
    return await skeleton_refresh_mail(ctx, **kwargs)


@ext.tool("skeleton_alert_gmail", description="Legacy alias → skeleton_alert_mail.")
async def skeleton_alert_gmail_alias(ctx, **kwargs) -> dict:
    return await skeleton_alert_mail(ctx, **kwargs)
