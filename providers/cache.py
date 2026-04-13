"""Mail · Cache utilities for skeleton context + inbox page caching."""
from __future__ import annotations

import hashlib
import json
import logging
import os

log = logging.getLogger(__name__)


# ── Skeleton context cache ────────────────────────────────────────────── #

async def _remove_from_cache(ctx, email: str, message_id: str) -> None:
    try:
        doc = await ctx.store.get("mail_inbox_cache", email)
        if doc and doc.data:
            messages = doc.data.get("messages", [])
            filtered = [m for m in messages if m.get("message_id") != message_id and m.get("id") != message_id]
            if len(filtered) != len(messages):
                await ctx.store.set("mail_inbox_cache", email, {**doc.data, "messages": filtered})
    except Exception as e:
        log.debug("_remove_from_cache failed: %s", e)


async def _remove_multiple_from_cache(ctx, email: str, message_ids: list[str]) -> None:
    if not message_ids:
        return
    try:
        doc = await ctx.store.get("mail_inbox_cache", email)
        if doc and doc.data:
            id_set = set(message_ids)
            messages = doc.data.get("messages", [])
            filtered = [m for m in messages if m.get("message_id") not in id_set and m.get("id") not in id_set]
            if len(filtered) != len(messages):
                await ctx.store.set("mail_inbox_cache", email, {**doc.data, "messages": filtered})
    except Exception as e:
        log.debug("_remove_multiple_from_cache failed: %s", e)


async def _update_read_in_cache(ctx, email: str, message_id: str, is_read: bool = True) -> None:
    try:
        doc = await ctx.store.get("mail_inbox_cache", email)
        if doc and doc.data:
            messages = doc.data.get("messages", [])
            for m in messages:
                if m.get("message_id") == message_id or m.get("id") == message_id:
                    m["unread"] = not is_read
                    break
            await ctx.store.set("mail_inbox_cache", email, {**doc.data, "messages": messages})
    except Exception as e:
        log.debug("_update_read_in_cache failed: %s", e)


async def _save_last_read(ctx, message_id: str, subject: str, sender: str,
                          message_id_header: str = "", thread_id: str = "") -> None:
    try:
        await ctx.store.set("mail_last_read", "latest", {
            "message_id": message_id, "subject": subject, "sender": sender,
            "message_id_header": message_id_header, "thread_id": thread_id,
        })
    except Exception as e:
        log.debug("_save_last_read failed: %s", e)


# ── Redis inbox page cache ─────────────────────────────────────────────── #

REDIS_URL = os.getenv("REDIS_URL", "")
_INBOX_TTL = 120
_PREFIX = "mail:inbox:"
_redis_client = None


async def _get_redis():
    global _redis_client
    if _redis_client is None:
        import redis.asyncio as aioredis
        _redis_client = aioredis.from_url(REDIS_URL, decode_responses=True)
    return _redis_client


def _inbox_key(email: str, folder: str, cursor: str) -> str:
    ch = hashlib.md5(cursor.encode()).hexdigest()[:8] if cursor else "first"
    return f"{_PREFIX}{email}:{folder}:{ch}"


async def get_cached_inbox(email: str, folder: str, cursor: str = "") -> tuple | None:
    try:
        r = await _get_redis()
        raw = await r.get(_inbox_key(email, folder, cursor))
        if not raw:
            return None
        data = json.loads(raw)
        return data["messages"], data["next_cursor"], data["has_more"]
    except Exception:
        return None


async def set_cached_inbox(email: str, folder: str, cursor: str,
                           messages: list, next_cursor, has_more: bool) -> None:
    try:
        r = await _get_redis()
        await r.setex(
            _inbox_key(email, folder, cursor), _INBOX_TTL,
            json.dumps({"messages": messages, "next_cursor": next_cursor, "has_more": has_more}, default=str),
        )
    except Exception:
        pass


async def invalidate_inbox(email: str, folder: str = "") -> None:
    try:
        r = await _get_redis()
        pattern = f"{_PREFIX}{email}:{folder}:*" if folder else f"{_PREFIX}{email}:*"
        keys = [k async for k in r.scan_iter(match=pattern, count=100)]
        if keys:
            await r.delete(*keys)
    except Exception:
        pass
