"""Mail Client · Inbox & compose @chat.function handlers."""
from __future__ import annotations

from app import chat
from imperal_sdk.chat.action_result import ActionResult
from handlers_ui import _email_ui, _inbox_ui, _search_ui
from handlers_inbox_impl import (
    impl_inbox, impl_read_email, impl_search, impl_folder,
    impl_get_thread, impl_send, impl_reply, impl_forward,
)
from schemas import (
    InboxParams, MessageIdParams, SearchParams, ThreadParams,
    SendParams, ReplyParams, ForwardParams,
    InboxPageResult, EmailBody, SearchResult, ThreadView, SendResult,
)


@chat.function("inbox", action_type="read",
               data_model=InboxPageResult,
               description="PRIMARY function to list emails. Use this when user asks for recent/latest/new emails, wants to see their inbox, or check mail. Use folder= for non-inbox folders (sent/spam/trash/drafts/starred/archive). Returns message previews with IDs, subjects, senders, dates, read state. Do NOT use search() for listing recent emails — use inbox().")
async def fn_inbox(ctx, params: InboxParams) -> ActionResult:
    try:
        r = await impl_inbox(ctx, folder=params.folder, cursor=params.cursor,
                             limit=params.limit, account=params.account)
        return ActionResult.success(
            data=r.model_dump(),
            summary=f"{len(r.messages)} message(s) in {params.folder}.",
            ui=_inbox_ui(r.messages, params.folder),
        )
    except Exception as e:
        return ActionResult.error(str(e), retryable=True)


@chat.function("read_email", action_type="read",
               data_model=EmailBody,
               id_projection="message_id",
               description="Open a specific email by message_id — returns full body (HTML + plain text), sender, all recipients, date, and attachment list. Also marks the message as read.")
async def fn_read_email(ctx, params: MessageIdParams) -> ActionResult:
    try:
        r = await impl_read_email(ctx, message_id=params.message_id, account=params.account)
        subj = r.subject or "(no subject)"
        return ActionResult.success(
            data=r.model_dump(),
            summary=f"Email: {subj}",
            ui=_email_ui(r),
        )
    except Exception as e:
        return ActionResult.error(str(e), retryable=True)


@chat.function("search", action_type="read",
               data_model=SearchResult,
               description="Find specific emails by content, sender, or subject. Use free-text or provider syntax (Gmail: from:sender, subject:topic, label:name; Outlook/IMAP: free-text). Only use when searching for something specific. For listing recent/latest emails use inbox() instead.")
async def fn_search(ctx, params: SearchParams) -> ActionResult:
    try:
        r = await impl_search(ctx, query=params.query, max_results=params.max_results,
                              account=params.account)
        return ActionResult.success(
            data=r.model_dump(),
            summary=f"{r.total} result(s) for '{params.query}'.",
            ui=_search_ui(r.results, params.query),
        )
    except Exception as e:
        return ActionResult.error(str(e), retryable=True)


@chat.function("folder", action_type="read",
               data_model=InboxPageResult,
               description="Fetch a page from a specific non-INBOX folder (sent, drafts, spam, trash, starred, archive). Functionally identical to inbox() with folder= — prefer inbox() unless explicit folder routing is needed.")
async def fn_folder(ctx, params: InboxParams) -> ActionResult:
    try:
        r = await impl_folder(ctx, folder=params.folder, cursor=params.cursor,
                              limit=params.limit, account=params.account)
        return ActionResult.success(data=r.model_dump(),
                                    summary=f"{len(r.messages)} message(s) in {params.folder}.")
    except Exception as e:
        return ActionResult.error(str(e), retryable=True)


@chat.function("get_thread", action_type="read",
               data_model=ThreadView,
               id_projection="thread_id",
               description="Load a complete email conversation by thread_id — all messages in chronological order. Works on Google and Microsoft; IMAP returns a single-message fallback.")
async def fn_get_thread(ctx, params: ThreadParams) -> ActionResult:
    try:
        r = await impl_get_thread(ctx, thread_id=params.thread_id, account=params.account)
        return ActionResult.success(data=r.model_dump(),
                                    summary=f"Thread '{r.subject}' — {r.total} message(s).")
    except Exception as e:
        return ActionResult.error(str(e), retryable=True)


@chat.function("send", action_type="write", event="sent",
               effects=["create:email"],
               data_model=SendResult,
               description="Send a brand-new email. Requires to and body; subject is auto-generated from the first line of body if omitted. Use reply() or forward() when responding to an existing message.")
async def fn_send(ctx, params: SendParams) -> ActionResult:
    try:
        r = await impl_send(ctx, to=params.to, subject=params.subject, body=params.body,
                            cc=params.cc, bcc=params.bcc, account=params.account)
        return ActionResult.success(data=r.model_dump(),
                                    summary=f"Email sent to {params.to}.",
                                    refresh_panels=["inbox"])
    except Exception as e:
        return ActionResult.error(str(e), retryable=False)


@chat.function("reply", action_type="write", event="sent",
               effects=["create:email"],
               data_model=SendResult,
               id_projection="message_id",
               description="Reply to an email by message_id. In a multi-step chain always call inbox() or search() first to get the message_id, then pass it here. Omit message_id only if the email was already opened with read_email() in this session. Use send() for new emails.")
async def fn_reply(ctx, params: ReplyParams) -> ActionResult:
    try:
        r = await impl_reply(ctx, body=params.body, message_id=params.message_id,
                             to=params.to, cc=params.cc, bcc=params.bcc, account=params.account)
        return ActionResult.success(data=r.model_dump(),
                                    summary=f"Reply sent to {r.to}.",
                                    refresh_panels=["inbox"])
    except Exception as e:
        return ActionResult.error(str(e), retryable=False)


@chat.function("forward", action_type="write", event="sent",
               effects=["create:email"],
               data_model=SendResult,
               id_projection="message_id",
               description="Forward an existing email by message_id to a new address. In a multi-step chain call inbox() or search() first to get the message_id. Requires message_id and to address.")
async def fn_forward(ctx, params: ForwardParams) -> ActionResult:
    try:
        r = await impl_forward(ctx, message_id=params.message_id, to=params.to,
                               comment=params.comment, account=params.account)
        return ActionResult.success(data=r.model_dump(),
                                    summary=f"Forwarded to {params.to}.",
                                    refresh_panels=["inbox"])
    except Exception as e:
        return ActionResult.error(str(e), retryable=False)
