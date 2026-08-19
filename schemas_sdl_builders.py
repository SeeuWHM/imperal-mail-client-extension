"""Mail Client — SDL builder helpers (imperal-sdk 5.2.0).

Each function converts an impl-layer Pydantic result (or raw dict) into the
corresponding SDL entity so @chat.function handlers can pass it as ActionResult.data.

Handlers import ONLY from this module — it re-exports all SDL entity classes too.
"""
from __future__ import annotations

from imperal_sdk import sdl

from schemas import (
    EmailBody, InboxPageResult, SearchResult, ThreadView as _ThreadView,
    SendResult, OperationResult, BulkOperationResult,
    ContactsList, ContactAdded, ContactDeleted, ContactsSyncResult,
    AccountsStatus, ConnectOAuthResult, ConnectImapResult,
    AccountSwitched, AccountDisconnected, MailActionResult,
    FolderCountsResult, OAuthUrlResult, ComposeSendResult,
    AttachmentContent,
)
from schemas_sdl import (
    _strip_html, _cref, _crefs, _pdate, _bfmt, _arefs,
    EmailPreview, EmailMessage, InboxPage, SearchPage,
    EmailThread, SentEmailResult, MailOpResult, BulkMailOpResult,
    AttachmentEntity,
    ContactEntity, ContactPage, ContactOpResult, ContactSyncResult,
    MailAccountEntity, AccountsPage,
    OAuthConnectResult, ImapConnectResult,
    AccountSwitchedResult, AccountDisconnectedResult,
    MailActionOpResult, FolderCountsEntity, MailOAuthUrlResult, ComposeSentResult,
)
# Re-export entity classes — handlers use a single import from this module.
__all__ = [
    "EmailPreview", "EmailMessage", "InboxPage", "SearchPage",
    "EmailThread", "SentEmailResult", "MailOpResult", "BulkMailOpResult",
    "ContactEntity", "ContactPage", "ContactOpResult", "ContactSyncResult",
    "MailAccountEntity", "AccountsPage",
    "OAuthConnectResult", "ImapConnectResult",
    "AccountSwitchedResult", "AccountDisconnectedResult",
    "MailActionOpResult", "FolderCountsEntity", "MailOAuthUrlResult", "ComposeSentResult",
    "build_email_message", "build_email_preview", "build_inbox_page", "build_search_page",
    "build_email_thread", "build_sent_result", "build_mail_op", "build_bulk_mail_op",
    "build_contact_page", "build_contact_added", "build_contact_deleted",
    "build_contact_sync", "build_accounts_page",
    "build_oauth_connect", "build_imap_connect",
    "build_account_switched", "build_account_disconnected",
    "build_mail_action_op", "build_folder_counts", "build_oauth_url", "build_compose_sent",
]


def build_email_message(body: EmailBody, account: str = "") -> EmailMessage:
    """Convert EmailBody (from impl_read_email) → full EmailMessage SDL entity."""
    raw = body.model_dump(by_alias=True)
    raw_from = raw.get("from") or raw.get("from_")
    thread_id = body.thread_id
    raw_attachments = raw.get("attachments") or []
    labels = raw.get("labels")
    tags = labels if isinstance(labels, list) else None
    subject = body.subject or "(no subject)"
    # Provide plain-text version and excerpt so LLM reads content cleanly
    # (ActionResult.data is passed verbatim to chain steps — body IS visible to LLM)
    fmt = _bfmt(body.body_type)
    raw_text: str | None = None
    if body.body:
        raw_text = _strip_html(body.body) if fmt == "html" else body.body
    excerpt = (raw_text[:800] + "…") if raw_text and len(raw_text) > 800 else raw_text

    return EmailMessage(
        id=body.message_id or "",
        title=subject,
        kind="email",
        sender=_cref(raw_from),
        recipients_to=_crefs(body.to),
        recipients_cc=_crefs(body.cc),
        body=body.body,
        body_format=fmt,
        raw_body=raw_text,
        excerpt=excerpt,
        is_read=not bool(body.unread),
        sent_at=_pdate(body.date),
        thread_ref=sdl.Ref(id=thread_id, kind="thread", title=subject) if thread_id else None,
        attachments=_arefs(raw_attachments),
        has_attachments=bool(raw_attachments),
        attachment_count=len(raw_attachments),
        tags=tags,
        is_favorite=bool(body.starred),
        thread_id=thread_id,
        folder=body.folder,
        replied=body.replied,
        truncated=body.truncated,
        account=account,
    )


def build_email_preview(d: dict, account: str = "") -> EmailPreview:
    """Convert provider raw message dict → EmailPreview SDL entity (list item)."""
    msg_id = d.get("message_id") or d.get("id") or ""
    subject = d.get("subject") or "(no subject)"
    raw_from = d.get("from") or d.get("from_")
    return EmailPreview(
        id=msg_id,
        title=subject,
        kind="email",
        sender=_cref(raw_from),
        is_read=not bool(d.get("unread", False)),
        sent_at=_pdate(d.get("date")),
        excerpt=d.get("snippet"),
        is_favorite=bool(d.get("starred", False)),
        thread_id=d.get("thread_id"),
        folder=d.get("folder"),
        account=account,
    )


def build_inbox_page(r: InboxPageResult, folder: str = "inbox") -> InboxPage:
    """Convert InboxPageResult → InboxPage SDL entity list."""
    items = [build_email_preview(m) for m in (r.messages or [])]
    # total is intentionally None: this is a capped display PAGE, not a folder total —
    # the real count is unknown here without a separate count query. Per SDL,
    # EntityList.total is `int | None` ("total across all pages, if known"). Pagination
    # awareness comes from has_more + unread_count; to COUNT emails use count_emails().
    return InboxPage(
        items=items,
        total=None,
        has_more=r.has_more,
        cursor=r.cursor,
        unread_count=r.unread_count,
        folder=folder,
    )


def build_search_page(r: SearchResult) -> SearchPage:
    """Convert SearchResult → SearchPage SDL entity list."""
    items = [build_email_preview(m) for m in (r.results or [])]
    # has_more=True when total > fetched count (provider estimate says there are more)
    has_more = r.total > len(items)
    return SearchPage(items=items, total=r.total, has_more=has_more, query=r.query or "")


def build_email_thread(r: "_ThreadView") -> EmailThread:
    """Convert ThreadView → EmailThread SDL entity."""
    msgs = [build_email_preview(m) for m in (r.messages or [])]
    thread_id = r.thread_id or ""
    subject = r.subject or "(no subject)"
    return EmailThread(
        id=thread_id,
        title=subject,
        kind="thread",
        thread_ref=sdl.Ref(id=thread_id, kind="thread", title=subject) if thread_id else None,
        messages=msgs,
    )


def build_sent_result(r: SendResult) -> SentEmailResult:
    """Convert SendResult → SentEmailResult SDL entity."""
    return SentEmailResult(
        id=r.message_id or r.to or "sent",
        title=r.subject or f"Sent to {r.to}",
        kind="sent_email",
        sent=r.sent,
        recipients_to=_crefs(r.to) if r.to else None,
        mail_subject=r.subject,
    )


def build_mail_op(r: OperationResult) -> MailOpResult:
    """Convert OperationResult → MailOpResult SDL entity."""
    return MailOpResult(
        id=r.message_id or "op",
        title=r.operation or "operation",
        kind="mail_op",
        op_ok=r.ok,
        operation=r.operation,
        detail=r.detail,
    )


def build_bulk_mail_op(r: BulkOperationResult) -> BulkMailOpResult:
    """Convert BulkOperationResult → BulkMailOpResult SDL entity."""
    return BulkMailOpResult(
        id=r.operation or "bulk_op",
        title=f"Bulk {r.operation}: {r.succeeded} succeeded",
        kind="bulk_mail_op",
        operation=r.operation,
        succeeded=r.succeeded,
        failed_count=r.failed,
        total=r.total,
        errors=r.errors or None,
    )


def build_contact_page(r: ContactsList) -> ContactPage:
    """Convert ContactsList → ContactPage SDL entity list."""
    items = [
        ContactEntity(
            id=c.email, title=c.name or c.email, kind="contact",
            emails=[c.email] if c.email else None, source=c.source,
        )
        for c in r.contacts
    ]
    return ContactPage(items=items, total=r.total)


def build_contact_added(r: ContactAdded) -> ContactOpResult:
    """Convert ContactAdded → ContactOpResult SDL entity."""
    return ContactOpResult(
        id=r.email, title=r.name or r.email, kind="contact_op",
        contact_email=r.email, contact_name=r.name or None,
    )


def build_contact_deleted(r: ContactDeleted) -> ContactOpResult:
    """Convert ContactDeleted → ContactOpResult SDL entity."""
    return ContactOpResult(
        id=r.email, title=r.email, kind="contact_op",
        contact_email=r.email,
    )


def build_contact_sync(r: ContactsSyncResult) -> ContactSyncResult:
    """Convert ContactsSyncResult → ContactSyncResult SDL entity."""
    return ContactSyncResult(
        id="sync", title=f"Synced {r.added} new contacts", kind="contact_sync",
        found=r.found, added=r.added, total_contacts=r.total,
        notes=r.notes or None,
    )


def build_accounts_page(r: AccountsStatus) -> AccountsPage:
    """Convert AccountsStatus → AccountsPage SDL entity list."""
    items = [
        MailAccountEntity(
            id=a.email, title=a.email, kind="mail_account",
            provider=a.provider, is_active=a.is_active, unread_count=a.unread_count,
        )
        for a in r.accounts
    ]
    return AccountsPage(items=items, total=r.total, connected=r.connected)


def build_oauth_connect(r: ConnectOAuthResult) -> OAuthConnectResult:
    """Convert ConnectOAuthResult → OAuthConnectResult SDL entity."""
    return OAuthConnectResult(
        id=r.email or "oauth",
        title="Already connected" if r.already_connected else "OAuth authorization URL ready",
        kind="oauth_connect",
        auth_url=r.auth_url, instruction=r.instruction,
        already_connected=r.already_connected,
    )


def build_imap_connect(r: ConnectImapResult) -> ImapConnectResult:
    """Convert ConnectImapResult → ImapConnectResult SDL entity."""
    return ImapConnectResult(
        id=r.email, title=r.email, kind="imap_connect",
        imap_server=r.imap_server, connected=r.connected,
    )


def build_account_switched(r: AccountSwitched) -> AccountSwitchedResult:
    """Convert AccountSwitched → AccountSwitchedResult SDL entity."""
    return AccountSwitchedResult(
        id=r.active_account, title=r.active_account, kind="account_switched",
        switched=r.switched, active_account=r.active_account,
    )


def build_account_disconnected(r: AccountDisconnected) -> AccountDisconnectedResult:
    """Convert AccountDisconnected → AccountDisconnectedResult SDL entity."""
    return AccountDisconnectedResult(
        id=r.email, title=r.email, kind="account_disconnected",
        disconnected=r.disconnected, account_email=r.email, remaining=r.remaining,
    )


def build_mail_action_op(r: MailActionResult) -> MailActionOpResult:
    """Convert MailActionResult → MailActionOpResult SDL entity."""
    return MailActionOpResult(
        id=r.action, title=f"{r.action}: {r.count} message(s)",
        kind="mail_action_op", action=r.action, count=r.count,
    )


def build_folder_counts(r: FolderCountsResult) -> FolderCountsEntity:
    """Convert FolderCountsResult → FolderCountsEntity SDL entity."""
    inbox_unread = r.counts.get("INBOX", 0)
    return FolderCountsEntity(
        id="folder_counts", title=f"INBOX: {inbox_unread} unread",
        kind="folder_counts", counts=r.counts,
    )


def build_oauth_url(r: OAuthUrlResult) -> MailOAuthUrlResult:
    """Convert OAuthUrlResult → MailOAuthUrlResult SDL entity."""
    return MailOAuthUrlResult(
        id=r.provider, title=f"OAuth URL: {r.provider}",
        kind="oauth_url", auth_url=r.auth_url, provider=r.provider,
    )


def build_compose_sent(r: ComposeSendResult, to: str = "") -> ComposeSentResult:
    """Convert ComposeSendResult → ComposeSentResult SDL entity."""
    return ComposeSentResult(
        id=r.to or to or "sent", title=f"Sent to {r.to or to}",
        kind="compose_sent", sent=r.sent, mode=r.mode, recipient=r.to or to,
    )


def build_attachment_entity(r: AttachmentContent, attachment_id: str = "") -> AttachmentEntity:
    """Convert AttachmentContent (from impl_read_attachment) → AttachmentEntity SDL entity."""
    return AttachmentEntity(
        id=attachment_id or r.filename or "attachment",
        title=r.filename or "Attachment",
        kind="attachment",
        body=r.text,
        body_format="plain",
        mime_type=r.mime_type,
        size_bytes=r.size_bytes,
        extraction_status=r.status,
        truncated=r.truncated,
        extraction_method=r.extraction_method,
        status=r.status,
        description=r.error,
    )
