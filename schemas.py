"""Pydantic schemas for mail extension — response models."""
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
    body: Optional[str] = None
    body_type: Optional[str] = None
    attachments: list[dict[str, Any]] = Field(default_factory=list)
    unread: Optional[bool] = None
    starred: Optional[bool] = None
    replied: Optional[bool] = None
    folder: Optional[str] = None
    truncated: Optional[bool] = None
    # Set by the IMAP provider when a body over 4000 chars was cut short
    # (see mail_providers/imap.py read_email). Was previously silently
    # dropped here since this field didn't exist on the model — read_email()
    # chat callers had no way to know the body they got back was incomplete.

    model_config = {"populate_by_name": True}

class AttachmentContent(BaseModel):
    """read_attachment — the extracted TEXT of one email attachment.

    status mirrors the doc-extractor engine's own states so a caller can
    tell "still indexing, try again shortly" apart from a real failure.
    """

    filename: str = ""
    mime_type: str = ""
    size_bytes: int = 0
    status: str = "ready"        # ready | processing | unsupported | error
    text: Optional[str] = None
    truncated: bool = False
    extraction_method: Optional[str] = None
    error: Optional[str] = None

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
    starred: Optional[int] = None
    unstarred: Optional[int] = None
    moved: Optional[int] = None
    purged: Optional[int] = None
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
    """Compact per-account entry for classifier envelope.

    Docs rule: skeleton lists ≤5 items expand inline — each field visible to LLM.
    Most users have ≤3 accounts so per_account is always fully expanded.
    """

    email: str = ""
    unread_count: int = 0
    is_active: bool = False

class InboxSummary(BaseModel):
    """skeleton_refresh_mail_inbox_summary — 6-field classifier envelope for mail.

    Reference shape ONLY. skeleton.py returns a raw ``{"response": {...}}`` dict
    (no Pydantic in the response path). Shape follows the docs recipe
    ``recipes/skeleton-data-surface`` (counts + a recent-item array ≤5). All
    list items are plain dicts — no nested Pydantic validation.
    """

    active_account: str = ""
    unread_total: int = 0
    today_total: int = 0
    total_all: int = 0
    per_account: list[dict] = Field(default_factory=list)  # {email, total, unread, spam, archive}

class SkeletonAlertMessage(BaseModel):
    """skeleton_alert_mail_inbox_summary — lightweight unread count from store (no API calls)."""

    unread_total: int = 0
    per_account: list[dict] = Field(default_factory=list)

# Re-export param models so handler imports (from schemas import FooParams) keep working.
from schemas_params import *  # noqa: F401, F403
