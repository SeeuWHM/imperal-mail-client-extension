"""Mail Client · Inbox & compose handlers."""
from __future__ import annotations

import logging

from app import chat
from imperal_sdk.chat.action_result import ActionResult
from ctx_helpers import _get_acc

from providers import get_provider
from providers.helpers import encode_cursor, decode_cursor

from schemas import (
    EmailBody, InboxPageResult, SearchResult, SendResult, ThreadView,
    InboxParams, MessageIdParams, SearchParams, ThreadParams,
    SendParams, ReplyParams, ForwardParams,
)

log = logging.getLogger(__name__)


# ─── impl_* business logic ────────────────────────────────────────────── #


async def impl_inbox(ctx, folder: str = "inbox", cursor: str = "",
                     limit: int = 20, account: str = "") -> InboxPageResult:
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
    return EmailBody.model_validate(data)


async def impl_search(ctx, query: str, max_results: int = 10, account: str = "") -> SearchResult:
    acc, provider = await _get_acc(ctx, account)
    if not acc:
        raise RuntimeError("No email account connected. Connect one first.")
    result = await provider.search(ctx, acc, query=query, max_results=max_results)
    if result.get("RESULT") == "ERROR":
        raise RuntimeError(result.get("error", "Unknown provider error"))
    results = result.get("results", []) or []
    return SearchResult(query=query, results=results, total=int(result.get("total", len(results)) or 0))


async def impl_folder(ctx, folder: str, cursor: str = "",
                      limit: int = 20, account: str = "") -> InboxPageResult:
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
    return ThreadView(
        thread_id=result.get("thread_id") or thread_id,
        subject=result.get("subject"),
        total=int(result.get("total", len(messages)) or 0),
        messages=messages,
    )


async def impl_send(ctx, to: str, subject: str = "", body: str = "",
                    cc: str = "", bcc: str = "", account: str = "") -> SendResult:
    if not to:
        raise RuntimeError("Recipient (to) is required.")
    if not body:
        raise RuntimeError("Email body is required.")
    if not subject:
        first_line = (body.strip().split('\n')[0] or body.strip())[:60]
        subject = first_line or "(no subject)"
    acc, provider = await _get_acc(ctx, account)
    if not acc:
        raise RuntimeError("No email account connected. Connect one first.")
    result = await provider.send(ctx, acc, to=to, subject=subject, body=body, cc=cc, bcc=bcc)
    if result.get("RESULT") == "ERROR":
        raise RuntimeError(result.get("error", "Send failed"))
    return SendResult(sent=True, to=to, subject=subject,
                      message_id=result.get("message_id") or result.get("id"))


async def impl_reply(ctx, body: str, message_id: str = "", to: str = "",
                     cc: str = "", bcc: str = "", account: str = "") -> SendResult:
    if not ctx.user or not ctx.user.imperal_id or ctx.user.imperal_id == "__system__":
        raise RuntimeError("No authenticated user context.")
    if not body:
        raise RuntimeError("Reply body is required.")
    mid = message_id
    if not mid:
        uid = str(ctx.user.imperal_id)
        lr_page = await ctx.store.query("mail_last_read", where={"user_id": uid}, limit=1)
        doc = lr_page.data[0] if lr_page.data else None
        if doc:
            mid = doc.get("message_id", "")
    if not mid:
        raise RuntimeError("No message_id and no recently read email.")
    acc, provider = await _get_acc(ctx, account)
    if not acc:
        raise RuntimeError("No email account connected. Connect one first.")
    result = await provider.reply(ctx, acc, message_id=mid, body=body, to=to, cc=cc, bcc=bcc)
    if result.get("RESULT") == "ERROR":
        raise RuntimeError(result.get("error", "Reply failed"))
    return SendResult(sent=True, to=result.get("to") or to,
                      message_id=result.get("message_id") or result.get("id"))


async def impl_forward(ctx, message_id: str, to: str,
                       comment: str = "", account: str = "") -> SendResult:
    acc, provider = await _get_acc(ctx, account)
    if not acc:
        raise RuntimeError("No email account connected. Connect one first.")
    result = await provider.forward(ctx, acc, message_id=message_id, to=to, comment=comment)
    if result.get("RESULT") == "ERROR":
        raise RuntimeError(result.get("error", "Forward failed"))
    return SendResult(sent=True, to=to,
                      message_id=result.get("message_id") or result.get("id"))


# ─── @chat.function wrappers ──────────────────────────────────────────── #


@chat.function("inbox", action_type="read",
               description="Show inbox messages with cursor-based pagination. Supports folder keys: inbox/sent/spam/trash/drafts/starred.")
async def fn_inbox(ctx, params: InboxParams) -> ActionResult:
    try:
        r = await impl_inbox(ctx, folder=params.folder, cursor=params.cursor,
                             limit=params.limit, account=params.account)
        return ActionResult.success(data=r.model_dump(),
                                    summary=f"{len(r.messages)} message(s) in {params.folder}.")
    except RuntimeError as e:
        return ActionResult.error(str(e), retryable=True)


@chat.function("read_email", action_type="read",
               description="Read the full content of an email by message ID — subject, sender, body, attachments.")
async def fn_read_email(ctx, params: MessageIdParams) -> ActionResult:
    try:
        r = await impl_read_email(ctx, message_id=params.message_id, account=params.account)
        subj = r.subject or "(no subject)"
        return ActionResult.success(data=r.model_dump(), summary=f"Email: {subj}")
    except RuntimeError as e:
        return ActionResult.error(str(e), retryable=True)


@chat.function("search", action_type="read",
               description="Search emails by sender, subject, keywords, or Gmail search syntax.")
async def fn_search(ctx, params: SearchParams) -> ActionResult:
    try:
        r = await impl_search(ctx, query=params.query, max_results=params.max_results,
                              account=params.account)
        return ActionResult.success(data=r.model_dump(),
                                    summary=f"{r.total} result(s) for '{params.query}'.")
    except RuntimeError as e:
        return ActionResult.error(str(e), retryable=True)


@chat.function("folder", action_type="read",
               description="Browse a mail folder with cursor-based pagination — sent, spam, trash, starred, drafts, archive.")
async def fn_folder(ctx, params: InboxParams) -> ActionResult:
    try:
        r = await impl_folder(ctx, folder=params.folder, cursor=params.cursor,
                              limit=params.limit, account=params.account)
        return ActionResult.success(data=r.model_dump(),
                                    summary=f"{len(r.messages)} message(s) in {params.folder}.")
    except RuntimeError as e:
        return ActionResult.error(str(e), retryable=True)


@chat.function("get_thread", action_type="read",
               description="View a full email thread/conversation by thread ID.")
async def fn_get_thread(ctx, params: ThreadParams) -> ActionResult:
    try:
        r = await impl_get_thread(ctx, thread_id=params.thread_id, account=params.account)
        return ActionResult.success(data=r.model_dump(),
                                    summary=f"Thread '{r.subject}' — {r.total} message(s).")
    except RuntimeError as e:
        return ActionResult.error(str(e), retryable=True)


@chat.function("send", action_type="write", event="sent",
               effects=["create:email"],
               description="Send a new email. Requires to, subject, and body.")
async def fn_send(ctx, params: SendParams) -> ActionResult:
    try:
        r = await impl_send(ctx, to=params.to, subject=params.subject, body=params.body,
                            cc=params.cc, bcc=params.bcc, account=params.account)
        return ActionResult.success(data=r.model_dump(),
                                    summary=f"Email sent to {params.to}.")
    except RuntimeError as e:
        return ActionResult.error(str(e), retryable=False)


@chat.function("reply", action_type="write", event="sent",
               effects=["create:email"],
               description="Reply to an email. Uses last-read message if message_id is omitted.")
async def fn_reply(ctx, params: ReplyParams) -> ActionResult:
    try:
        r = await impl_reply(ctx, body=params.body, message_id=params.message_id,
                             to=params.to, cc=params.cc, bcc=params.bcc, account=params.account)
        return ActionResult.success(data=r.model_dump(),
                                    summary=f"Reply sent to {r.to}.")
    except RuntimeError as e:
        return ActionResult.error(str(e), retryable=False)


@chat.function("forward", action_type="write", event="sent",
               effects=["create:email"],
               description="Forward an email to a new recipient with an optional comment.")
async def fn_forward(ctx, params: ForwardParams) -> ActionResult:
    try:
        r = await impl_forward(ctx, message_id=params.message_id, to=params.to,
                               comment=params.comment, account=params.account)
        return ActionResult.success(data=r.model_dump(),
                                    summary=f"Forwarded to {params.to}.")
    except RuntimeError as e:
        return ActionResult.error(str(e), retryable=False)
