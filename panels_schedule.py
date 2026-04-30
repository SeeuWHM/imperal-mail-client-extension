"""Mail Client · Inbox page pre-warmer — fetches page 2 into cache every 3 minutes."""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from app import ext
from cache_model_defs import InboxManifest, InboxPage
from providers import get_provider
from providers.helpers import (
    COLLECTION, INBOX_FETCH_SIZE,
    _inbox_page_key, _inbox_manifest_key,
    encode_cursor, decode_cursor,
    _refresh_token_if_needed,
)

log = logging.getLogger("mail")


@ext.schedule("inbox_warmup", cron="*/3 * * * *")
async def inbox_warmup(ctx):
    """Pre-warm inbox page 2 for all users every 3 minutes.

    Reads the InboxManifest from cache. If cursors has at least 2 entries
    (i.e. page 2 cursor is known), fetches page 2 and caches it.
    Also discovers the page 3 cursor and appends it to the manifest.
    """
    async for user_ctx in ctx.store.list_users(COLLECTION):
        try:
            docs = await user_ctx.store.query(COLLECTION)
            accounts = [{"doc_id": d.id, **d.data} for d in docs]
            for acc in accounts:
                if not acc.get("is_active"):
                    continue
                email = acc.get("email", "")
                try:
                    manifest = await user_ctx.cache.get(
                        _inbox_manifest_key(email, "INBOX"), InboxManifest)
                    if not manifest or len(manifest.cursors) < 2:
                        continue  # page 2 cursor not known yet — skip

                    acc = await _refresh_token_if_needed(user_ctx, acc)
                    provider = get_provider(acc)

                    # Fetch and cache page 2
                    cursor_2 = manifest.cursors[1]
                    cursor_data_2 = decode_cursor(cursor_2) if cursor_2 else None
                    messages2, next_cursor_data_2, has_more_2 = await provider.fetch_page(
                        user_ctx, acc, "INBOX", INBOX_FETCH_SIZE, cursor_data_2)

                    norm2 = []
                    for m in messages2:
                        if "id" in m and "message_id" not in m:
                            m = {**m, "message_id": m["id"]}
                        norm2.append(m)

                    provider_key = acc.get("provider", "oauth")
                    next_cur_2 = encode_cursor(provider_key, next_cursor_data_2) or ""
                    page2 = InboxPage(
                        account_id=email, folder="INBOX", cursor=cursor_2,
                        messages=norm2, next_cursor=next_cur_2,
                        has_more=bool(has_more_2),
                        fetched_at=datetime.now(timezone.utc),
                    )
                    await user_ctx.cache.set(
                        _inbox_page_key(email, "INBOX", cursor_2), page2, ttl_seconds=120)

                    # Update manifest with page 3 cursor if available
                    cursors = manifest.cursors[:]
                    if next_cur_2 and has_more_2 and len(cursors) < 3:
                        cursors.append(next_cur_2)
                    updated_manifest = InboxManifest(
                        account_id=email, folder="INBOX",
                        total=manifest.total, unread=manifest.unread,
                        page_size=INBOX_FETCH_SIZE,
                        cursors=cursors,
                        preloaded=min(2, len(cursors)),
                        fetched_at=datetime.now(timezone.utc),
                    )
                    await user_ctx.cache.set(
                        _inbox_manifest_key(email, "INBOX"), updated_manifest, ttl_seconds=120)

                except Exception as e:
                    log.debug("inbox_warmup for %s: %s", email, e)
        except Exception as e:
            log.debug("inbox_warmup user error: %s", e)
