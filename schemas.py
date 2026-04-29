"""Pydantic schemas for mail extension — response models + @chat.function params."""
from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


# ── Accounts ──────────────────────────────────────────────────────────────────


class MailAccount(BaseModel):
    """One connected email account summary row for the status panel."""

    email: str = ""
    provider: str = ""
    is_active: bool = False
    unread_count: int = 0


class AccountsStatus(BaseModel):
    """status — all connected email accounts with provider + unread counts."""

    connected: bool = False
    accounts: list[MailAccount] = Field(default_factory=list)
    total: int = 0


class ConnectOAuthResult(BaseModel):
    """connect / connect_microsoft / connect_yahoo — OAuth authorisation result.

    Either ``auth_url`` is set (user needs to click) or ``already_connected``
    is true (idempotent — existing account reused).
    """

    auth_url: Optional[str] = None
    instruction: Optional[str] = None
    already_connected: bool = False
    email: Optional[str] = None
    total: Optional[int] = None


class ConnectImapResult(BaseModel):
    """connect_imap / add_imap — direct IMAP/SMTP connection confirmation."""

    connected: bool = True
    email: str
    imap_server: str = ""


class AccountSwitched(BaseModel):
    """switch_account — confirmation the active account moved."""

    switched: bool = True
    active_account: str


class AccountDisconnected(BaseModel):
    """disconnect — removal confirmation."""

    disconnected: bool = True
    email: str
    remaining: int = 0


class OAuthUrlResult(BaseModel):
    """get_oauth_url — OAuth URL for panel wizard redirect."""

    auth_url: str
    provider: str


# ── Inbox / Folder / Read ─────────────────────────────────────────────────────


class MessagePreview(BaseModel):
    """One message row shown in the inbox/folder list.

    Provider-normalised shape — Gmail / Graph / IMAP all map into this. All
    fields are optional because different providers surface different headers.
    """

    message_id: Optional[str] = None
    thread_id: Optional[str] = None
    subject: Optional[str] = None
    from_: Optional[str] = Field(default=None, alias="from")
    to: Optional[str] = None
    cc: Optional[str] = None
    snippet: Optional[str] = None
    date: Optional[str] = None
    unread: Optional[bool] = None
    starred: Optional[bool] = None
    folder: Optional[str] = None
    labels: Optional[list[str]] = None

    model_config = {"populate_by_name": True}


class InboxPageResult(BaseModel):
    """inbox / folder — paginated list of messages for the given folder."""

    messages: list[dict[str, Any]] = Field(default_factory=list)
    cursor: Optional[str] = None
    has_more: bool = False
    unread_count: int = 0


class EmailBody(BaseModel):
    """read_email — full message body + headers.

    Kept as permissive dict-backed ``Any`` fields because Gmail / Graph /
    IMAP return different body + attachment shapes; Narrator renders the
    subject + sender from ActionResult.summary legacy path.
    """

    message_id: Optional[str] = None
    thread_id: Optional[str] = None
    subject: Optional[str] = None
    from_: Optional[str] = Field(default=None, alias="from")
    to: Optional[str] = None
    cc: Optional[str] = None
    date: Optional[str] = None
    body_text: Optional[str] = None
    body_html: Optional[str] = None
    attachments: list[dict[str, Any]] = Field(default_factory=list)
    unread: Optional[bool] = None
    starred: Optional[bool] = None
    folder: Optional[str] = None

    model_config = {"populate_by_name": True}


class ThreadView(BaseModel):
    """get_thread — full conversation view for a message thread."""

    thread_id: Optional[str] = None
    subject: Optional[str] = None
    total: int = 0
    messages: list[dict[str, Any]] = Field(default_factory=list)


class SearchResult(BaseModel):
    """search — Gmail/Graph/IMAP query hits, heterogeneous rows allowed."""

    query: Optional[str] = None
    results: list[dict[str, Any]] = Field(default_factory=list)
    total: int = 0


# ── Write / Manage ────────────────────────────────────────────────────────────


class SendResult(BaseModel):
    """send / reply / forward — confirmation a message was dispatched."""

    sent: bool = True
    to: Optional[str] = None
    subject: Optional[str] = None
    message_id: Optional[str] = None


class ComposeSendResult(BaseModel):
    """compose_send — panel-side send/reply/forward confirmation."""

    sent: bool = True
    to: str
    mode: str = "new"


class OperationResult(BaseModel):
    """archive / delete / mark_read / mark_unread / star / move / purge —
    simple acknowledgement of a single-message operation."""

    ok: bool = True
    message_id: Optional[str] = None
    operation: Optional[str] = None
    detail: Optional[str] = None


class BulkOperationResult(BaseModel):
    """bulk_archive / bulk_delete / bulk_mark_read / bulk_mark_unread —
    multi-message batch summary with success + failure counts.

    succeeded is the unified success count; per-operation count fields
    (archived / deleted / marked_read / marked_unread) mirror
    the legacy v1 shape so downstream audit logs keep their field names.
    """

    operation: Optional[str] = None
    succeeded: int = 0
    archived: Optional[int] = None
    deleted: Optional[int] = None
    marked_read: Optional[int] = None
    marked_unread: Optional[int] = None
    total: Optional[int] = None
    failed: Optional[int] = None
    errors: list[str] = Field(default_factory=list)


# ── Panel actions (batch from UI) ─────────────────────────────────────────────


class MailActionResult(BaseModel):
    """mail_action — UI-triggered per-row or batch action confirmation."""

    action: str
    count: int = 0


class FolderCountsResult(BaseModel):
    """folder_counts — unread counts keyed by folder name for sidebar badges."""

    counts: dict[str, int] = Field(default_factory=dict)


# ── Contacts ──────────────────────────────────────────────────────────────────


class ContactEntry(BaseModel):
    """One contact row."""

    email: str
    name: str = ""
    source: str = "manual"


class ContactsList(BaseModel):
    """contacts — filtered contact roster."""

    contacts: list[ContactEntry] = Field(default_factory=list)
    total: int = 0


class ContactAdded(BaseModel):
    """add_contact — single contact creation result."""

    added: bool = True
    email: str
    name: str = ""


class ContactDeleted(BaseModel):
    """delete_contact — single contact deletion result."""

    deleted: bool = True
    email: str


class ContactsSyncResult(BaseModel):
    """sync_contacts — counts + notes from Google People / Graph / header
    harvest import pass."""

    found: int = 0
    added: int = 0
    total: int = 0
    notes: list[str] = Field(default_factory=list)


# ── Skeleton ──────────────────────────────────────────────────────────────────


class PerAccountUnread(BaseModel):
    """Compact per-account unread entry for classifier envelope."""

    email: str = ""
    unread_count: int = 0
    message_count: int = 0
    error: Optional[str] = None


class InboxSummary(BaseModel):
    """skeleton_refresh_mail_inbox_summary — roster + per-account unread
    counts for the classifier envelope."""

    accounts_connected: int = 0
    unread_total: int = 0
    per_account: list[PerAccountUnread] = Field(default_factory=list)


class SkeletonAlertMessage(BaseModel):
    """skeleton_alert_mail_inbox_summary — proactive new-mail narration."""

    message: str = ""


# ── @chat.function parameter models ──────────────────────────────────────────

class AccountParam(BaseModel):
    """Single optional account selector."""
    account: str = Field(default="", description="Account email or ID (omit for active account)")


class ConnectImapParams(BaseModel):
    email_addr: str = Field(description="Email address")
    password: str = Field(description="IMAP password or app password")
    imap_host: str = Field(default="", description="IMAP host (auto-detected if empty)")
    smtp_host: str = Field(default="", description="SMTP host (auto-detected if empty)")
    imap_port: int = Field(default=0, description="IMAP port (auto-detected if 0)")
    smtp_port: int = Field(default=0, description="SMTP port (auto-detected if 0)")


class InboxParams(BaseModel):
    folder: str = Field(default="inbox", description="Folder: inbox/sent/spam/trash/drafts/starred")
    cursor: str = Field(default="", description="Pagination cursor from previous page")
    limit: int = Field(default=20, description="Messages per page (1-100)")
    account: str = Field(default="", description="Account email or ID")


class MessageIdParams(BaseModel):
    message_id: str = Field(description="Email message ID")
    account: str = Field(default="", description="Account email or ID")


class SearchParams(BaseModel):
    query: str = Field(description="Search query — Gmail syntax supported")
    max_results: int = Field(default=10, description="Max results to return")
    account: str = Field(default="", description="Account email or ID")


class ThreadParams(BaseModel):
    thread_id: str = Field(description="Thread ID")
    account: str = Field(default="", description="Account email or ID")


class SendParams(BaseModel):
    to: str = Field(description="Recipient email address")
    subject: str = Field(description="Email subject")
    body: str = Field(description="Email body (plain text)")
    cc: str = Field(default="", description="CC recipients (comma-separated)")
    bcc: str = Field(default="", description="BCC recipients (comma-separated)")
    account: str = Field(default="", description="Account email or ID")


class ReplyParams(BaseModel):
    body: str = Field(description="Reply body text")
    message_id: str = Field(default="", description="Message ID to reply to (omit = last read)")
    to: str = Field(default="", description="Override reply-to address")
    cc: str = Field(default="", description="CC recipients")
    bcc: str = Field(default="", description="BCC recipients")
    account: str = Field(default="", description="Account email or ID")


class ForwardParams(BaseModel):
    message_id: str = Field(description="Message ID to forward")
    to: str = Field(description="Forward recipient email")
    comment: str = Field(default="", description="Optional comment prepended to the forwarded body")
    account: str = Field(default="", description="Account email or ID")


class StarParams(BaseModel):
    message_id: str = Field(description="Message ID")
    starred: bool = Field(default=True, description="True to star, False to unstar")
    account: str = Field(default="", description="Account email or ID")


class MoveParams(BaseModel):
    message_id: str = Field(description="Message ID to move")
    from_folder: str = Field(description="Source folder")
    to_folder: str = Field(description="Destination folder")
    account: str = Field(default="", description="Account email or ID")


class PurgeParams(BaseModel):
    message_id: str = Field(description="Message ID to permanently delete")
    from_folder: str = Field(default="Trash", description="Folder to purge from")
    account: str = Field(default="", description="Account email or ID")


class BulkParams(BaseModel):
    message_ids: str = Field(description="Comma-separated list of message IDs")
    account: str = Field(default="", description="Account email or ID")


class ContactsParams(BaseModel):
    search: str = Field(default="", description="Filter by name or email")
    limit: int = Field(default=50, description="Max contacts to return")


class AddContactParams(BaseModel):
    email: str = Field(description="Contact email address")
    name: str = Field(default="", description="Display name (optional)")


class DeleteContactParams(BaseModel):
    email: str = Field(description="Contact email address to remove")


class MailActionParams(BaseModel):
    action: str = Field(description="Action: archive, delete, spam, mark_read, mark_unread, star")
    message_id: str = Field(default="", description="Single message ID")
    message_ids: list[str] = Field(default_factory=list, description="Multiple message IDs")
    account: str = Field(default="", description="Account email or ID")


class OAuthParams(BaseModel):
    provider: str = Field(description="OAuth provider: google or microsoft")


class AddImapParams(BaseModel):
    email: str = Field(description="Email address")
    password: str = Field(description="IMAP password or app password")
    imap_host: str = Field(default="", description="IMAP host (auto-detected if empty)")
    smtp_host: str = Field(default="", description="SMTP host (auto-detected if empty)")
    imap_port: int = Field(default=993, description="IMAP port")
    smtp_port: int = Field(default=587, description="SMTP port")


class ComposeSendParams(BaseModel):
    to: str = Field(description="Recipient email address")
    subject: str = Field(default="", description="Subject (required for new emails)")
    body: str = Field(default="", description="Email body")
    mode: str = Field(default="new", description="Mode: new, reply, forward")
    message_id: str = Field(default="", description="Original message ID (for reply/forward)")
    cc: str = Field(default="", description="CC recipients")
    bcc: str = Field(default="", description="BCC recipients")
    account: str = Field(default="", description="Account email or ID")
