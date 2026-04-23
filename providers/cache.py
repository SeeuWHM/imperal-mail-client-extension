"""Mail · Cache utilities for skeleton context + inbox page caching."""
from __future__ import annotations

import hashlib
import json
import logging
import os

log = logging.getLogger(__name__)


# ── Context scope helper ──────────────────────────────────────────────────── #

def _ctx_scope(ctx) -> tuple[str, str]:
    """Return (tenant_id, user_id) from ctx with safe fallbacks."""
    tenant_id = "default"
    user_id   = "anon"
    if ctx and hasattr(ctx, "user") and ctx.user:
        if hasattr(ctx.user, "tenant_id") and ctx.user.tenant_id:
            tenant_id = str(ctx.user.tenant_id)
        if hasattr(ctx.user, "id") and ctx.user.id:
            user_id = str(ctx.user.id)
    return tenant_id, user_id


# ── Store-backed helpers (B3: now delegate to Redis invalidation) ──────────── #

async def _remove_from_cache(ctx, email: str, message_id: str) -> None:
    """Invalidate the Redis page cache after a single-message remove operation."""
    try:
        await invalidate_inbox(ctx, email)
    except Exception as e:
        log.debug("_remove_from_cache: %s", e)


async def _remove_multiple_from_cache(ctx, email: str, message_ids: list[str]) -> None:
    """Invalidate the Redis page cache after a bulk remove operation."""
    if not message_ids:
        return
    try:
        await invalidate_inbox(ctx, email)
    except Exception as e:
        log.debug("_remove_multiple_from_cache: %s", e)


async def _update_read_in_cache(ctx, email: str, message_id: str, is_read: bool = True) -> None:
    """Invalidate the Redis page cache after a read-state change.

    Surgical per-message Redis patching is impractical without tracking which
    cursor page contains the message. Full invalidation causes one extra live
    fetch on next panel load — acceptable trade-off for correctness.
    """
    try:
        await invalidate_inbox(ctx, email)
    except Exception as e:
        log.debug("_update_read_in_cache: %s", e)


async def _save_last_read(ctx, message_id: str, subject: str, sender: str,
                          message_id_header: str = "", thread_id: str = "") -> None:
    """Persist the last-read watermark, stamped with user_id for defence-in-depth."""
    try:
        _, user_id = _ctx_scope(ctx)
        await ctx.store.set("mail_last_read", "latest", {
            "message_id":        message_id,
            "subject":           subject,
            "sender":            sender,
            "message_id_header": message_id_header,
            "thread_id":         thread_id,
            "user_id":           user_id,
        })
    except Exception as e:
        log.debug("_save_last_read failed: %s", e)


# ── Redis inbox page cache (B1: keys scoped to tenant+user+email) ─────────── #

REDIS_URL  = os.getenv("REDIS_URL", "")
_INBOX_TTL = 120
_PREFIX    = "mail:inbox:"
_redis_client = None


async def _get_redis():
    global _redis_client
    if _redis_client is None:
        import redis.asyncio as aioredis
        _redis_client = aioredis.from_url(REDIS_URL, decode_responses=True)
    return _redis_client


def _inbox_key(ctx, email: str, folder: str, cursor: str) -> str:
    """Build a Redis key scoped to tenant + user + email + folder + cursor page."""
    tenant_id, user_id = _ctx_scope(ctx)
    ch = hashlib.md5(cursor.encode()).hexdigest()[:8] if cursor else "first"
    return f"{_PREFIX}{tenant_id}:{user_id}:{email}:{folder}:{ch}"


async def get_cached_inbox(ctx, email: str, folder: str, cursor: str = "") -> tuple | None:
    try:
        r   = await _get_redis()
        raw = await r.get(_inbox_key(ctx, email, folder, cursor))
        if not raw:
            return None
        data = json.loads(raw)
        return data["messages"], data["next_cursor"], data["has_more"]
    except Exception:
        return None


async def set_cached_inbox(ctx, email: str, folder: str, cursor: str,
                           messages: list, next_cursor, has_more: bool) -> None:
    try:
        r = await _get_redis()
        await r.setex(
            _inbox_key(ctx, email, folder, cursor),
            _INBOX_TTL,
            json.dumps(
                {"messages": messages, "next_cursor": next_cursor, "has_more": has_more},
                default=str,
            ),
        )
    except Exception:
        pass


async def invalidate_inbox(ctx, email: str, folder: str = "") -> None:
    """Delete all cached pages for this user+email (or a specific folder)."""
    try:
        r = await _get_redis()
        tenant_id, user_id = _ctx_scope(ctx)
        base    = f"{_PREFIX}{tenant_id}:{user_id}:{email}"
        pattern = f"{base}:{folder}:*" if folder else f"{base}:*"
        keys = [k async for k in r.scan_iter(match=pattern, count=100)]
        if keys:
            await r.delete(*keys)
    except Exception:
        pass
