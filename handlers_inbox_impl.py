"""Mail Client · Inbox business logic — impl_* functions."""
from __future__ import annotations

import datetime as _dt
import logging

from ctx_helpers import _get_acc
from handlers_ui import _email_ui, _inbox_ui, _search_ui
from providers import get_provider
from providers.helpers import encode_cursor, decode_cursor, _all_accounts
from schemas import (
    EmailBody, InboxPageResult, SearchResult, SendResult, ThreadView,
)

log = logging.getLogger(__name__)


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
    if account:
        acc, provider = await _get_acc(ctx, account)
        if not acc:
            raise RuntimeError("Account not found.")
        result = await provider.read_email(ctx, acc, message_id)
        if result.get("RESULT") == "ERROR":
            raise RuntimeError(result.get("error") or "Unknown provider error")
        data = {k: v for k, v in result.items() if k != "RESULT"}
        return EmailBody.model_validate(data)

    # No account specified — try all connected accounts, return first hit.
    accounts = await _all_accounts(ctx)
    if not accounts:
        raise RuntimeError("No email account connected. Connect one first.")
    last_err = "Email not found in any connected account."
    for acc in accounts:
        try:
            provider = get_provider(acc)
            result = await provider.read_email(ctx, acc, message_id)
            if result.get("RESULT") == "ERROR":
                last_err = result.get("error") or last_err
                continue
            data = {k: v for k, v in result.items() if k != "RESULT"}
            return EmailBody.model_validate(data)
        except Exception as e:
            log.warning("read_email failed for %s: %s", acc.get("email", "?"), e)
    raise RuntimeError(last_err)


async def impl_search(ctx, query: str, max_results: int = 50,
                      folder: str = "", account: str = "",
                      oldest_first: bool = False) -> SearchResult:
    """Search FULL mailbox. Gmail/Microsoft search all mail; IMAP uses folder param.
    oldest_first=True reverses result order for finding earliest/first-ever emails."""
    clamped = max(1, min(max_results, 200))
    if account:
        acc, provider = await _get_acc(ctx, account)
        if not acc:
            raise RuntimeError("Account not found.")
        kw = {"query": query, "max_results": clamped}
        if folder and acc.get("provider") == "imap":
            kw["folder"] = folder
        result = await provider.search(ctx, acc, **kw)
        if result.get("RESULT") == "ERROR":
            raise RuntimeError(result.get("error") or "Unknown provider error")
        results = result.get("results", []) or []
        return SearchResult(query=query, results=results,
                            total=int(result.get("total", len(results)) or 0))

    # No specific account → search ALL connected accounts and merge
    accounts = await _all_accounts(ctx)
    if not accounts:
        raise RuntimeError("No email account connected. Connect one first.")

    all_results: list[dict] = []
    seen_ids: set[str] = set()
    total_across_providers = 0  # sum of provider-reported totals (includes resultSizeEstimate for Gmail)
    for acc in accounts:
        try:
            provider = get_provider(acc)
            kw = {"query": query, "max_results": clamped}
            if folder and acc.get("provider") == "imap":
                kw["folder"] = folder
            result = await provider.search(ctx, acc, **kw)
            # Accumulate provider-reported total (Gmail: resultSizeEstimate, IMAP: real count)
            total_across_providers += int(result.get("total", 0) or 0)
            for msg in result.get("results", []) or []:
                mid = msg.get("message_id") or msg.get("id") or ""
                key = f"{acc.get('email','')}/{mid}" if mid else ""
                if key and key in seen_ids:
                    continue
                if key:
                    seen_ids.add(key)
                if "message_id" not in msg and mid:
                    msg = {**msg, "message_id": mid}
                msg["_account"] = acc.get("email", "")
                all_results.append(msg)
        except Exception as e:
            log.warning("search failed for %s: %s", acc.get("email", "?"), e)

    # Sort by date for oldest_first support (parse dates, sort ascending)
    if oldest_first and all_results:
        _UTC = _dt.timezone.utc
        _EPOCH = _dt.datetime.min.replace(tzinfo=_UTC)

        def _sort_key(m):
            from email.utils import parsedate_to_datetime
            d = m.get("date") or ""
            try:
                return parsedate_to_datetime(d)
            except Exception:
                try:
                    return _dt.datetime.fromisoformat(d.replace("Z", "+00:00"))
                except Exception:
                    return _EPOCH
        all_results.sort(key=_sort_key)

    # Use provider totals (incl. Gmail resultSizeEstimate) as authoritative count.
    # Fall back to len(all_results) only if providers returned 0.
    final_total = max(total_across_providers, len(all_results))
    return SearchResult(query=query, results=all_results[:clamped],
                        total=final_total)


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
        raise RuntimeError(result.get("error") or "Unknown provider error")
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
        raise RuntimeError(result.get("error") or "Send failed")
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
            if not account and doc.get("account"):
                account = doc.get("account", "")
    if not mid:
        raise RuntimeError("No message_id and no recently read email.")
    acc, provider = await _get_acc(ctx, account)
    if not acc:
        raise RuntimeError("No email account connected. Connect one first.")
    result = await provider.reply(ctx, acc, message_id=mid, body=body, to=to, cc=cc, bcc=bcc)
    if result.get("RESULT") == "ERROR":
        raise RuntimeError(result.get("error") or "Reply failed")
    return SendResult(sent=True, to=result.get("to") or to,
                      message_id=result.get("message_id") or result.get("id"))


async def impl_forward(ctx, message_id: str, to: str,
                       comment: str = "", account: str = "") -> SendResult:
    if account:
        acc, provider = await _get_acc(ctx, account)
        if not acc:
            raise RuntimeError("Account not found.")
        result = await provider.forward(ctx, acc, message_id=message_id, to=to, comment=comment)
        if result.get("RESULT") == "ERROR":
            raise RuntimeError(result.get("error") or "Forward failed")
        return SendResult(sent=True, to=to,
                          message_id=result.get("message_id") or result.get("id"))

    # No account specified — try all accounts until the message is found
    accounts = await _all_accounts(ctx)
    if not accounts:
        raise RuntimeError("No email account connected. Connect one first.")
    last_err = "Message not found in any connected account."
    for acc in accounts:
        try:
            provider = get_provider(acc)
            result = await provider.forward(ctx, acc, message_id=message_id, to=to, comment=comment)
            if result.get("RESULT") == "ERROR":
                last_err = result.get("error") or last_err
                continue
            return SendResult(sent=True, to=to,
                              message_id=result.get("message_id") or result.get("id"))
        except Exception as e:
            log.warning("forward failed for %s: %s", acc.get("email", "?"), e)
    raise RuntimeError(last_err)
