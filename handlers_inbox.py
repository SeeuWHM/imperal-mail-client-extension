"""Mail Client · Inbox & compose handlers (SDK v2.0.0)."""
from __future__ import annotations

import logging

from ctx_helpers import _get_acc

from providers import get_provider
from providers.helpers import encode_cursor, decode_cursor

from schemas import (
    EmailBody, InboxPageResult, SearchResult, SendResult, ThreadView,
)

log = logging.getLogger(__name__)


# ─── Read Handlers ────────────────────────────────────────────────────── #


async def impl_inbox(
    ctx, folder: str = "inbox", cursor: str = "",
    limit: int = 20, account: str = "",
) -> InboxPageResult:
    acc, _ = await _get_acc(ctx, account)
    if not acc:
        raise RuntimeError("No email account connected. Connect one first.")

    provider = get_provider(acc)
    cursor_data = decode_cursor(cursor) if cursor else None
    clamped_limit = max(1, min(limit, 100))

    try:
        messages, next_cursor_data, has_more = await provider.fetch_page(
            ctx, acc, folder, clamped_limit, cursor_data,
        )
    except Exception as e:
        log.warning("fetch_page failed folder=%s: %s", folder, e)
        raise RuntimeError(f"Failed to fetch {folder}: {e}")

    unread = 0
    try:
        unread = await provider.get_unread_count(ctx, acc, folder)
    except Exception:
        pass

    for msg in messages:
        if "id" in msg and "message_id" not in msg:
            msg["message_id"] = msg.pop("id")

    provider_key = acc.get("provider", "oauth")
    return InboxPageResult(
        messages=messages,
        cursor=encode_cursor(provider_key, next_cursor_data) or None,
        has_more=bool(has_more),
        unread_count=int(unread),
    )


async def impl_read_email(ctx, message_id: str, account: str = "") -> EmailBody:
    acc, provider = await _get_acc(ctx, account)
    if not acc:
        raise RuntimeError("No email account connected. Connect one first.")
    result = await provider.read_email(ctx, acc, message_id)
    if result.get("RESULT") == "ERROR":
        raise RuntimeError(result.get("error", "Unknown provider error"))
    data = {k: v for k, v in result.items() if k != "RESULT"}
    # EmailBody uses alias="from" for the sender field — pydantic accepts
    # both "from" (alias) and "from_" (attr name) via populate_by_name.
    return EmailBody.model_validate(data)


async def impl_search(
    ctx, query: str, max_results: int = 10, account: str = "",
) -> SearchResult:
    acc, provider = await _get_acc(ctx, account)
    if not acc:
        raise RuntimeError("No email account connected. Connect one first.")
    result = await provider.search(ctx, acc, query=query, max_results=max_results)
    if result.get("RESULT") == "ERROR":
        raise RuntimeError(result.get("error", "Unknown provider error"))
    results = result.get("results", []) or []
    total = int(result.get("total", len(results)) or 0)
    return SearchResult(query=query, results=results, total=total)


async def impl_folder(
    ctx, folder: str, cursor: str = "",
    limit: int = 20, account: str = "",
) -> InboxPageResult:
    acc, _ = await _get_acc(ctx, account)
    if not acc:
        raise RuntimeError("No email account connected. Connect one first.")

    provider = get_provider(acc)
    cursor_data = decode_cursor(cursor) if cursor else None
    clamped_limit = max(1, min(limit, 100))

    try:
        messages, next_cursor_data, has_more = await provider.fetch_page(
            ctx, acc, folder, clamped_limit, cursor_data,
        )
    except Exception as e:
        log.warning("fetch_page failed folder=%s: %s", folder, e)
        raise RuntimeError(f"Failed to fetch folder '{folder}': {e}")

    unread = 0
    try:
        unread = await provider.get_unread_count(ctx, acc, folder)
    except Exception:
        pass

    for msg in messages:
        if "id" in msg and "message_id" not in msg:
            msg["message_id"] = msg.pop("id")

    provider_key = acc.get("provider", "oauth")
    return InboxPageResult(
        messages=messages,
        cursor=encode_cursor(provider_key, next_cursor_data) or None,
        has_more=bool(has_more),
        unread_count=int(unread),
    )


async def impl_get_thread(ctx, thread_id: str, account: str = "") -> ThreadView:
    acc, provider = await _get_acc(ctx, account)
    if not acc:
        raise RuntimeError("No email account connected. Connect one first.")
    result = await provider.get_thread(ctx, acc, thread_id)
    if result.get("RESULT") == "ERROR":
        raise RuntimeError(result.get("error", "Unknown provider error"))
    messages = result.get("messages", []) or []
    total = int(result.get("total", len(messages)) or 0)
    return ThreadView(
        thread_id=result.get("thread_id") or thread_id,
        subject=result.get("subject"),
        total=total,
        messages=messages,
    )


# ─── Write Handlers ───────────────────────────────────────────────────── #


async def impl_send(
    ctx, to: str, subject: str, body: str,
    cc: str = "", bcc: str = "", account: str = "",
) -> SendResult:
    if not to or not subject or not body:
        raise RuntimeError("to, subject, and body are required.")
    acc, provider = await _get_acc(ctx, account)
    if not acc:
        raise RuntimeError("No email account connected. Connect one first.")
    result = await provider.send(
        ctx, acc, to=to, subject=subject, body=body, cc=cc, bcc=bcc,
    )
    if result.get("RESULT") == "ERROR":
        raise RuntimeError(result.get("error", "Send failed"))
    return SendResult(
        sent=True,
        to=to,
        subject=subject,
        message_id=result.get("message_id") or result.get("id"),
    )


async def impl_reply(
    ctx, body: str, message_id: str = "", to: str = "",
    cc: str = "", bcc: str = "", account: str = "",
) -> SendResult:
    # Auth guard — fail at the front door rather than reaching the store.
    if not ctx.user or not ctx.user.id or ctx.user.id == "__system__":
        raise RuntimeError("No authenticated user context.")
    if not body:
        raise RuntimeError("Reply body is required.")
    mid = message_id
    if not mid:
        # Use ctx.store.get with the fixed-ID "latest" document, not query (unordered).
        doc = await ctx.store.get("mail_last_read", "latest")
        if doc:
            stored_uid = doc.get("user_id", "")
            if stored_uid and stored_uid != ctx.user.id:
                raise RuntimeError("auth_mismatch")
            mid = doc.get("message_id", "")
    if not mid:
        raise RuntimeError("No message_id and no recently read email.")
    acc, provider = await _get_acc(ctx, account)
    if not acc:
        raise RuntimeError("No email account connected. Connect one first.")
    result = await provider.reply(
        ctx, acc, message_id=mid, body=body, to=to, cc=cc, bcc=bcc,
    )
    if result.get("RESULT") == "ERROR":
        raise RuntimeError(result.get("error", "Reply failed"))
    return SendResult(
        sent=True,
        to=result.get("to") or to,
        message_id=result.get("message_id") or result.get("id"),
    )


async def impl_forward(
    ctx, message_id: str, to: str, comment: str = "", account: str = "",
) -> SendResult:
    acc, provider = await _get_acc(ctx, account)
    if not acc:
        raise RuntimeError("No email account connected. Connect one first.")
    result = await provider.forward(
        ctx, acc, message_id=message_id, to=to, comment=comment,
    )
    if result.get("RESULT") == "ERROR":
        raise RuntimeError(result.get("error", "Forward failed"))
    return SendResult(
        sent=True,
        to=to,
        message_id=result.get("message_id") or result.get("id"),
    )
