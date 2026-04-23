"""Mail Client · Inbox & compose handlers."""
from __future__ import annotations

import logging

from pydantic import BaseModel, Field

from app import chat, ActionResult, _get_acc, _no_account_error, _wrap_provider_result

from providers import get_provider
from providers.helpers import SKELETON_INBOX, encode_cursor, decode_cursor

log = logging.getLogger(__name__)


# ─── Models ───────────────────────────────────────────────────────────── #

class InboxParams(BaseModel):
    """Fetch inbox page with cursor-based pagination."""
    folder: str        = Field(default="inbox", description="Folder: inbox, sent, spam, trash, drafts, starred")
    cursor: str | None = Field(default=None, description="Pagination cursor from previous response")
    limit: int         = Field(default=20, description="Messages per page (max 100)")
    account: str       = Field(default="", description="Email account to use")


class MessageIdParams(BaseModel):
    """Target a specific email."""
    message_id: str = Field(description="Email message ID")
    account: str    = Field(default="", description="Email account")


class SearchParams(BaseModel):
    """Search emails."""
    query: str       = Field(description="Search query")
    max_results: int = Field(default=10, description="Max results")
    account: str     = Field(default="", description="Email account")


class FolderParams(BaseModel):
    """Browse a mail folder with cursor-based pagination."""
    folder: str        = Field(description="Folder: sent, spam, trash, starred, drafts, all, archive, unread")
    cursor: str | None = Field(default=None, description="Pagination cursor from previous response")
    limit: int         = Field(default=20, description="Messages per page (max 100)")
    account: str       = Field(default="", description="Email account")


class ThreadParams(BaseModel):
    """View an email thread."""
    thread_id: str = Field(description="Thread ID")
    account: str   = Field(default="", description="Email account")


class SendParams(BaseModel):
    """Send a new email."""
    to: str      = Field(description="Recipient email")
    subject: str = Field(description="Email subject")
    body: str    = Field(description="Email body")
    cc: str      = Field(default="", description="CC recipients")
    bcc: str     = Field(default="", description="BCC recipients")
    account: str = Field(default="", description="Send from this account")


class ReplyParams(BaseModel):
    """Reply to an email."""
    message_id: str = Field(default="", description="Message to reply to (uses last read if empty)")
    body: str       = Field(description="Reply body")
    to: str         = Field(default="", description="Override reply recipient(s)")
    cc: str         = Field(default="", description="CC")
    bcc: str        = Field(default="", description="BCC")
    account: str    = Field(default="", description="Email account")


class ForwardParams(BaseModel):
    """Forward an email."""
    message_id: str = Field(description="Message to forward")
    to: str         = Field(description="Forward recipient")
    comment: str    = Field(default="", description="Comment to add")
    account: str    = Field(default="", description="Email account")


# ─── Read Handlers ────────────────────────────────────────────────────── #

@chat.function("inbox", action_type="read", description="Show inbox messages with pagination.")
async def fn_inbox(ctx, params: InboxParams) -> ActionResult:
    acc, _ = await _get_acc(ctx, params.account)
    if not acc:
        return _no_account_error()

    provider = get_provider(acc)
    cursor_data = decode_cursor(params.cursor)
    clamped_limit = max(1, min(params.limit, 100))

    try:
        messages, next_cursor_data, has_more = await provider.fetch_page(
            ctx, acc, params.folder, clamped_limit, cursor_data,
        )
    except Exception as e:
        log.warning("fetch_page failed folder=%s: %s", params.folder, e)
        return ActionResult.error(f"Failed to fetch {params.folder}: {e}")

    unread = 0
    try:
        unread = await provider.get_unread_count(ctx, acc, params.folder)
    except Exception:
        pass

    for msg in messages:
        if "id" in msg and "message_id" not in msg:
            msg["message_id"] = msg.pop("id")

    provider_key = acc.get("provider", "oauth")
    return ActionResult.success(
        data={
            "messages": messages,
            "cursor": encode_cursor(provider_key, next_cursor_data),
            "has_more": has_more,
            "unread_count": unread,
        },
        summary=f"{params.folder}: {unread} unread, {len(messages)} shown",
    )


@chat.function("read_email", action_type="read", description="Read full email content by message ID.")
async def fn_read_email(ctx, params: MessageIdParams) -> ActionResult:
    acc, provider = await _get_acc(ctx, params.account)
    if not acc:
        return _no_account_error()
    result = await provider.read_email(ctx, acc, params.message_id)
    subj = result.get("subject", "") if result.get("RESULT") != "ERROR" else ""
    return _wrap_provider_result(result, f"Email: {subj}" if subj else "Read email")


@chat.function("search", action_type="read", description="Search emails by sender, subject, keywords.")
async def fn_search(ctx, params: SearchParams) -> ActionResult:
    acc, provider = await _get_acc(ctx, params.account)
    if not acc:
        return _no_account_error()
    result = await provider.search(ctx, acc, query=params.query, max_results=params.max_results)
    total = result.get("total", len(result.get("results", []))) if result.get("RESULT") != "ERROR" else 0
    return _wrap_provider_result(result, f"Search '{params.query}': {total} results")


@chat.function("folder", action_type="read", description="Browse a mail folder with pagination.")
async def fn_folder(ctx, params: FolderParams) -> ActionResult:
    acc, _ = await _get_acc(ctx, params.account)
    if not acc:
        return _no_account_error()

    provider = get_provider(acc)
    cursor_data = decode_cursor(params.cursor)
    clamped_limit = max(1, min(params.limit, 100))

    try:
        messages, next_cursor_data, has_more = await provider.fetch_page(
            ctx, acc, params.folder, clamped_limit, cursor_data,
        )
    except Exception as e:
        log.warning("fetch_page failed folder=%s: %s", params.folder, e)
        return ActionResult.error(f"Failed to fetch folder '{params.folder}': {e}")

    unread = 0
    try:
        unread = await provider.get_unread_count(ctx, acc, params.folder)
    except Exception:
        pass

    for msg in messages:
        if "id" in msg and "message_id" not in msg:
            msg["message_id"] = msg.pop("id")

    provider_key = acc.get("provider", "oauth")
    return ActionResult.success(
        data={
            "messages": messages,
            "cursor": encode_cursor(provider_key, next_cursor_data),
            "has_more": has_more,
            "unread_count": unread,
        },
        summary=f"Folder '{params.folder}': {unread} unread, {len(messages)} shown",
    )


@chat.function("get_thread", action_type="read", description="View full email thread by thread ID.")
async def fn_get_thread(ctx, params: ThreadParams) -> ActionResult:
    acc, provider = await _get_acc(ctx, params.account)
    if not acc:
        return _no_account_error()
    result = await provider.get_thread(ctx, acc, params.thread_id)
    total = result.get("total", 0) if result.get("RESULT") != "ERROR" else 0
    return _wrap_provider_result(result, f"Thread: {total} messages")


# ─── Write Handlers ───────────────────────────────────────────────────── #

@chat.function("send", action_type="write", event="sent", description="Send a new email.")
async def fn_send(ctx, params: SendParams) -> ActionResult:
    if not params.to or not params.subject or not params.body:
        return ActionResult.error("to, subject, and body are required.")
    acc, provider = await _get_acc(ctx, params.account)
    if not acc:
        return _no_account_error()
    result = await provider.send(ctx, acc, to=params.to, subject=params.subject, body=params.body, cc=params.cc, bcc=params.bcc)
    return _wrap_provider_result(result, f"Email sent to {params.to}")


@chat.function("reply", action_type="write", event="replied", description="Reply to an email.")
async def fn_reply(ctx, params: ReplyParams) -> ActionResult:
    # Auth guard — fail at the front door rather than reaching the store.
    if not ctx.user or not ctx.user.id or ctx.user.id == "__system__":
        return ActionResult.error("No authenticated user context.")
    if not params.body:
        return ActionResult.error("Reply body is required.")
    mid = params.message_id
    if not mid:
        # Use ctx.store.get with the fixed-ID "latest" document, not query (unordered).
        doc = await ctx.store.get("mail_last_read", "latest")
        if doc:
            stored_uid = doc.get("user_id", "")
            if stored_uid and stored_uid != ctx.user.id:
                return ActionResult.error("auth_mismatch")
            mid = doc.get("message_id", "")
    if not mid:
        return ActionResult.error("No message_id and no recently read email.")
    acc, provider = await _get_acc(ctx, params.account)
    if not acc:
        return _no_account_error()
    result = await provider.reply(ctx, acc, message_id=mid, body=params.body, to=params.to, cc=params.cc, bcc=params.bcc)
    reply_to = result.get("to", "") if result.get("RESULT") != "ERROR" else ""
    return _wrap_provider_result(result, f"Reply sent to {reply_to}" if reply_to else "Reply sent")


@chat.function("forward", action_type="write", event="forwarded", description="Forward an email.")
async def fn_forward(ctx, params: ForwardParams) -> ActionResult:
    acc, provider = await _get_acc(ctx, params.account)
    if not acc:
        return _no_account_error()
    result = await provider.forward(ctx, acc, message_id=params.message_id, to=params.to, comment=params.comment)
    return _wrap_provider_result(result, f"Email forwarded to {params.to}")
