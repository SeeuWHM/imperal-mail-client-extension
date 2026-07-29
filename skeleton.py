"""Mail Client · Skeleton tools.

The skeleton does:
1. Surface a 5-field classifier envelope of READ-query counts (docs recipe
   ``recipes/skeleton-data-surface`` — counts + per-item array ≤5):
   ``active_account``, ``unread_total``, ``today_total``, ``total_all``,
   ``per_account`` [≤5 {email, total, unread, spam, archive}].
   Counts come from ``provider.get_counts`` / ``provider.get_today_count``
   (normalized across Google / Microsoft / IMAP) — NOT from search, so the
   brain answers "how many total / unread / spam / archive / today" directly.
2. Diff against a MONOTONIC seen-id set to fire ``ctx.notify()`` for new mail
   exactly once per message, ever (fixed 2026-07-19 — see "Seen-id watermark"
   below; was a wholesale-replace of the page-1 window, which silently
   re-announced any message that fell off that window).
3. Write first page of INBOX to ctx.cache so the panel opens instantly (0 extra API calls).

Seen-id watermark (monotonic, not a snapshot)
----------------------------------------------
Old behaviour: ``last_message_ids`` was REPLACED every refresh with just the
current INBOX page-1 window (``INBOX_FETCH_SIZE`` = 25 ids). Any message that
left that 25-id window — a page reordered by a read/star/label change, a
burst of >25 new arrivals in one tick, or (worst case) a silently swallowed
``ctx.store.update`` failure — got re-classified "new" the next time it
resurfaced in page 1, and ``ctx.notify`` re-fired the IDENTICAL text. Live
evidence (2026-07-19 ticket): the same subject re-announced up to 16x over
28h, gaps as tight as 482s — a periodic producer re-fire, not consumer
redelivery.

Fix: the seen-set is now a UNION, never a replace. ``curr_ids`` (this tick's
page-1 window) is folded INTO the stored set instead of overwriting it, so
an id ever seen is never forgotten and never re-announced — genuinely
monotonic. Bounded to the most recent ``_SEEN_ID_CAP`` (500) ids by
``last_seen`` timestamp so the stored document doesn't grow unbounded; a
message would need to be one of the 500 most-recently-seen ids to still be
suppressed, comfortably above the 25-id page window this account will ever
diff against in one tick.

The persisted shape changed from ``list[str]`` (bare ids) to
``list[{"id": str, "last_seen": int}]`` so eviction can be LRU rather than
arbitrary-order truncation; old bare-string documents are transparently
migrated (treated as seen at last_fetched, or now if absent) the first time
this runs after the upgrade — no backfill script needed.

Failure handling (ticket requirement #2): the OLD code wrapped
``ctx.store.update`` in a bare ``except: pass`` — a failed write silently
left the watermark stale, and the NEXT tick would then treat still-seen
messages as new again (the ticket's "silently failed store write" case).
Now: if the store write fails, we log it and SKIP ``ctx.notify`` for this
account this tick — a stale watermark must never be allowed to fire
notifications, only to (at worst) delay a legitimate one by one tick.

Date watermark (ticket requirement #3, extra belt-and-suspenders): in
addition to the id-set, we track ``last_notified_date`` (the newest
Date/receivedDateTime header of a message we've ever notified about) and
additionally require a candidate "new" message's own date to be AFTER that
watermark before notifying. This guards against any future regression in
the id-set logic re-introducing duplicate notifications for genuinely old
mail — belt-and-suspenders, not a replacement for the id-set fix.
"""
from __future__ import annotations

import asyncio
import logging
import time as _time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

from app import ext

from cache_model_defs import InboxMessages
from mail_providers import get_provider
from mail_providers.helpers import (
    _all_accounts, _inbox_messages_key, _refresh_token_if_needed,
    COLLECTION, INBOX_FETCH_SIZE, encode_cursor,
)

log = logging.getLogger("mail")

# Most-recent seen-ids kept per account — comfortably above INBOX_FETCH_SIZE
# (25) so ordinary page jitter / bursts never evict an id we still need to
# suppress, while keeping the persisted store document small.
_SEEN_ID_CAP = 500


def _parse_msg_date(raw: str | None) -> datetime | None:
    """Parse an RFC2822 (most providers) or ISO8601 (Graph) date header.
    Returns a tz-aware datetime, or None if unparseable/absent — a message
    with no parseable date never blocks its own notification (falls back to
    id-set-only gating), it just can't be used to ADVANCE the date watermark.
    """
    if not raw:
        return None
    try:
        dt = parsedate_to_datetime(raw)
    except Exception:
        try:
            dt = datetime.fromisoformat(raw)
        except Exception:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _load_seen_ids(acc: dict) -> dict[str, int]:
    """Returns {id: last_seen_epoch}. Migrates the old bare list[str] shape
    (pre-2026-07-19) transparently — those ids are treated as seen at
    last_fetched (or now, if that's also absent) so they stay suppressed."""
    raw = acc.get("seen_message_ids")
    if raw is None:
        # Migrate the old field name/shape — every previously-seen id in the
        # page-1 window must stay suppressed, never re-announced by the fix.
        legacy = acc.get("last_message_ids") or []
        fallback_ts = int(acc.get("last_fetched") or _time.time())
        return {str(mid): fallback_ts for mid in legacy if mid}
    if isinstance(raw, dict):
        return {str(k): int(v) for k, v in raw.items()}
    if isinstance(raw, list):
        # Could be the new [{"id","last_seen"}] shape or (defensively) a bare
        # list of ids from a partial migration — handle both.
        out: dict[str, int] = {}
        fallback_ts = int(acc.get("last_fetched") or _time.time())
        for item in raw:
            if isinstance(item, dict) and item.get("id"):
                out[str(item["id"])] = int(item.get("last_seen") or fallback_ts)
            elif isinstance(item, str) and item:
                out[item] = fallback_ts
        return out
    return {}


def _merge_seen_ids(prev: dict[str, int], curr_ids: set[str], now: int) -> dict[str, int]:
    """Monotonic union — curr_ids are folded IN, never replace prev. Bounded
    to the _SEEN_ID_CAP most-recently-seen ids (LRU by last_seen)."""
    merged = dict(prev)
    for mid in curr_ids:
        merged[mid] = now
    if len(merged) > _SEEN_ID_CAP:
        # Keep the most recently seen — oldest ids age out first.
        keep = sorted(merged.items(), key=lambda kv: kv[1], reverse=True)[:_SEEN_ID_CAP]
        merged = dict(keep)
    return merged


def _seen_ids_for_store(seen: dict[str, int]) -> list[dict]:
    return [{"id": mid, "last_seen": ts} for mid, ts in seen.items()]


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
        prev_seen = _load_seen_ids(acc)
        prev_ids = set(prev_seen.keys())
        last_notified_date = _parse_msg_date(acc.get("last_notified_date") or "")

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
            # MONOTONIC — an id ever seen must never be re-announced. Ids that
            # left the page-1 window (jitter/bursts) stay suppressed via
            # prev_ids; only a genuinely fresh id counts as "new" here.
            truly_new = curr_ids - prev_ids

            # Belt-and-suspenders (ticket #3): also require the candidate's own
            # date to be newer than the last message we actually notified
            # about, so a future id-set regression can't resurrect old mail.
            if truly_new and last_notified_date is not None:
                gated: set[str] = set()
                for mid in truly_new:
                    msg = next(
                        (m for m in messages if m.get("id") == mid or m.get("message_id") == mid),
                        None,
                    )
                    msg_date = _parse_msg_date((msg or {}).get("date")) if msg else None
                    if msg_date is None or msg_date > last_notified_date:
                        gated.add(mid)
                truly_new = gated

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

            now_ts = int(_time.time())
            merged_seen = _merge_seen_ids(prev_seen, curr_ids, now_ts)

            # Ticket #2 — a failed persist must SKIP the notify for this tick,
            # never fire on a watermark we know didn't make it to storage.
            store_write_ok = True
            try:
                await ctx.store.update(COLLECTION, acc["doc_id"], {
                    **{k: v for k, v in acc.items()
                       if k not in ("doc_id", "is_active", "last_message_ids")},
                    "last_fetched": now_ts,
                    "unread_count": unread,
                    "seen_message_ids": _seen_ids_for_store(merged_seen),
                })
            except Exception as e:
                store_write_ok = False
                log.error(f"Mail skeleton store.update failed for {email}: {e} — "
                          f"skipping notify this tick (stale watermark must not fire)")

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

            if truly_new and store_write_ok:
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
                    # Advance the date watermark past the newest notified message —
                    # only after notify actually ran, so a notify-path exception
                    # doesn't silently advance it past mail nobody was told about.
                    newest_dates = [
                        d for d in (_parse_msg_date(m.get("date")) for m in new_msgs) if d
                    ]
                    if newest_dates:
                        newest = max(newest_dates)
                        if last_notified_date is None or newest > last_notified_date:
                            try:
                                await ctx.store.update(COLLECTION, acc["doc_id"], {
                                    "last_notified_date": newest.isoformat(),
                                })
                            except Exception as e:
                                log.debug("date watermark persist failed %s: %s", email, e)
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
        "per_account":    pa_list[:5],
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
