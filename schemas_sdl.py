"""Mail Client — SDL entity classes (imperal-sdk 5.2.0).

All @chat.function data_model= types live here.  Parser helpers are also here
so schemas_sdl_builders can import them alongside the entity classes.
"""
from __future__ import annotations

import re
from datetime import datetime

from pydantic import Field
from imperal_sdk import sdl
from imperal_sdk.sdl import field as sdl_field

# ── HTML stripping ───────────────────────────────────────────────────────────

_HTML_TAGS_RE = re.compile(r'<[^>]+>')
_HTML_ENTITIES = {"&amp;": "&", "&lt;": "<", "&gt;": ">", "&quot;": '"', "&#39;": "'", "&nbsp;": " "}
_WHITESPACE_RE = re.compile(r'\s+')

def _strip_html(html: str) -> str:
    """Strip HTML tags and decode common entities → plain text for LLM readability."""
    text = _HTML_TAGS_RE.sub(' ', html)
    for entity, char in _HTML_ENTITIES.items():
        text = text.replace(entity, char)
    return _WHITESPACE_RE.sub(' ', text).strip()

# ── Address / date parse helpers ──────────────────────────────────────────────

_ADDR_RE = re.compile(r'\s*(.+?)\s*<([^>]+)>\s*')

def _cref(raw: str | None) -> sdl.Ref | None:
    """Parse "Name <email>" or bare email → sdl.Ref(kind="contact")."""
    if not raw:
        return None
    raw = raw.strip()
    m = _ADDR_RE.match(raw)
    if m:
        name = m.group(1).strip().strip("\"'")
        email = m.group(2).strip().lower()
        return sdl.Ref(id=email, kind="contact", title=name or email)
    if "@" in raw:
        e = raw.lower()
        return sdl.Ref(id=e, kind="contact", title=e)
    return None

def _crefs(raw: str | None) -> list[sdl.Ref] | None:
    """Parse comma-separated address string → list[sdl.Ref]."""
    if not raw:
        return None
    refs = [_cref(p.strip()) for p in raw.split(",") if p.strip()]
    return [r for r in refs if r] or None

def _pdate(s: str | None) -> datetime | None:
    """Parse RFC2822 or ISO8601 date string → datetime. Silent on failure."""
    if not s:
        return None
    try:
        from email.utils import parsedate_to_datetime
        return parsedate_to_datetime(s)
    except Exception:
        pass
    try:
        return datetime.fromisoformat(s)
    except Exception:
        return None

_BODY_FMT_MAP = {
    "html": "html", "text": "plain", "plain": "plain",
    "md": "md", "markdown": "md", "rich": "rich",
}

def _bfmt(raw: str | None) -> str | None:
    """Map provider body_type string → SDL body_format literal."""
    return _BODY_FMT_MAP.get((raw or "").lower())

def _arefs(raw: list | None) -> list[sdl.Ref] | None:
    """Convert list of attachment dicts → list[sdl.Ref(kind='attachment')]."""
    if not raw:
        return None
    refs = []
    for a in raw:
        if isinstance(a, dict):
            name = a.get("filename") or a.get("name") or "attachment"
            aid = a.get("attachment_id") or a.get("id") or name
            refs.append(sdl.Ref(id=str(aid), kind="attachment", title=name))
    return refs or None

# ── Email entities ─────────────────────────────────────────────────────────────

class EmailPreview(
    sdl.Entity,
    sdl.Correspondents,
    sdl.MessageState,
    sdl.Excerptable,
    sdl.Lifecycle,
):
    """Email preview row — item in inbox/folder/search list results."""

    kind: str = "email"
    thread_id: str | None = sdl_field(role="mail.thread_id")
    folder: str | None = sdl_field(role="mail.folder")
    account: str | None = sdl_field(role="mail.account")

class EmailMessage(
    sdl.Entity,
    sdl.Correspondents,
    sdl.Bodied,
    sdl.MessageState,
    sdl.Threaded,
    sdl.Attached,
    sdl.Categorized,
    sdl.Lifecycle,
    sdl.Excerptable,
):
    """Full email message — returned by read_email()."""

    kind: str = "email"
    thread_id: str | None = sdl_field(role="mail.thread_id")
    folder: str | None = sdl_field(role="mail.folder")
    replied: bool | None = sdl_field(role="mail.replied")
    account: str | None = sdl_field(role="mail.account")
    # Reuses AttachmentEntity's role — same meaning ("content was cut short"),
    # now on the message body too (IMAP read_email truncates at 4000 chars).
    truncated: bool | None = sdl_field(role="mail.truncated")

class InboxPage(sdl.EntityList[EmailPreview]):
    """Paginated inbox/folder result — returned by inbox() and folder()."""

    cursor: str | None = None
    unread_count: int = 0
    folder: str = ""

class SearchPage(sdl.EntityList[EmailPreview]):
    """Email search results — returned by search()."""

    query: str = ""

class EmailThread(sdl.Entity, sdl.Threaded):
    """Full email conversation — returned by get_thread()."""

    kind: str = "thread"
    messages: list[EmailPreview] = Field(default_factory=list)

# ── Write / send entities ──────────────────────────────────────────────────────

class SentEmailResult(sdl.Entity, sdl.Correspondents):
    """Sent/replied/forwarded confirmation — returned by send/reply/forward."""

    kind: str = "sent_email"
    sent: bool = True
    mail_subject: str | None = sdl_field(role="mail.subject")

# ── Management operation entities ─────────────────────────────────────────────

class MailOpResult(sdl.Entity):
    """Single-message operation confirmation — archive/delete/mark/star/move/purge."""

    kind: str = "mail_op"
    op_ok: bool = sdl_field(role="mail.ok", default=True)
    operation: str | None = sdl_field(role="mail.operation")
    detail: str | None = sdl_field(role="mail.detail")

class BulkMailOpResult(sdl.Entity):
    """Bulk email operation summary — bulk_archive/delete/mark_read/mark_unread."""

    kind: str = "bulk_mail_op"
    operation: str | None = sdl_field(role="mail.operation")
    succeeded: int = sdl_field(role="mail.succeeded", default=0)
    failed_count: int | None = sdl_field(role="mail.failed_count")
    total: int | None = sdl_field(role="mail.total")
    errors: list[str] | None = sdl_field(role="mail.errors")

class AttachmentEntity(sdl.Entity, sdl.Bodied):
    """One attachment's extracted text — returned by read_attachment()."""

    kind: str = "attachment"
    mime_type: str | None = sdl_field(role="mail.attachment_mime")
    size_bytes: int | None = sdl_field(role="mail.attachment_size")
    extraction_status: str | None = sdl_field(role="mail.extraction_status")
    truncated: bool | None = sdl_field(role="mail.truncated")
    extraction_method: str | None = sdl_field(role="mail.extraction_method")

# ── Contact entities ───────────────────────────────────────────────────────────

class ContactEntity(sdl.Entity, sdl.ContactPoints):
    """Address book contact — item in contact lists and operation results."""

    kind: str = "contact"
    source: str | None = sdl_field(role="mail.source")
    account: str | None = sdl_field(role="mail.account")

class ContactPage(sdl.EntityList[ContactEntity]):
    """Paginated contact list — returned by contacts()."""

    pass

class ContactOpResult(sdl.Entity):
    """Contact add or delete confirmation — returned by add_contact/delete_contact."""

    kind: str = "contact_op"
    contact_email: str | None = sdl_field(role="mail.email")
    contact_name: str | None = sdl_field(role="mail.name")

class ContactSyncResult(sdl.Entity):
    """Contact sync summary — returned by sync_contacts()."""

    kind: str = "contact_sync"
    found: int = sdl_field(role="mail.found", default=0)
    added: int = sdl_field(role="mail.added", default=0)
    total_contacts: int | None = sdl_field(role="mail.total")
    notes: list[str] | None = sdl_field(role="mail.notes")

# ── Account entities ───────────────────────────────────────────────────────────

class MailAccountEntity(sdl.Entity):
    """Connected email account — item in AccountsPage."""

    kind: str = "mail_account"
    provider: str | None = sdl_field(role="mail.provider")
    is_active: bool | None = sdl_field(role="mail.is_active")
    unread_count: int | None = sdl_field(role="mail.unread_count")

class AccountsPage(sdl.EntityList[MailAccountEntity]):
    """All connected accounts — returned by status()."""

    connected: bool = True

class OAuthConnectResult(sdl.Entity):
    """OAuth authorisation result — returned by connect/connect_microsoft/connect_yahoo."""

    kind: str = "oauth_connect"
    auth_url: str | None = sdl_field(role="mail.auth_url")
    instruction: str | None = sdl_field(role="mail.instruction")
    already_connected: bool = sdl_field(role="mail.already_connected", default=False)

class ImapConnectResult(sdl.Entity):
    """IMAP/SMTP connection result — returned by connect_imap/add_imap."""

    kind: str = "imap_connect"
    imap_server: str | None = sdl_field(role="mail.imap_server")
    connected: bool = True

class AccountSwitchedResult(sdl.Entity):
    """Active account change confirmation — returned by switch_account()."""

    kind: str = "account_switched"
    switched: bool = True
    active_account: str | None = sdl_field(role="mail.active_account")

class AccountDisconnectedResult(sdl.Entity):
    """Account removal confirmation — returned by disconnect()."""

    kind: str = "account_disconnected"
    disconnected: bool = True
    account_email: str | None = sdl_field(role="mail.email")
    remaining: int | None = sdl_field(role="mail.remaining")

# ── Panel / UI entities ────────────────────────────────────────────────────────

class MailActionOpResult(sdl.Entity):
    """Panel row-action confirmation — returned by mail_action()."""

    kind: str = "mail_action_op"
    action: str = sdl_field(role="mail.action", default="")
    count: int = sdl_field(role="mail.count", default=0)

class FolderCountsEntity(sdl.Entity):
    """Unread counts for all 7 mail folders — returned by folder_counts()."""

    kind: str = "folder_counts"
    counts: dict[str, int] | None = sdl_field(role="mail.folder_counts")

class MailOAuthUrlResult(sdl.Entity):
    """OAuth URL for the add-account panel wizard — returned by get_oauth_url()."""

    kind: str = "oauth_url"
    auth_url: str = sdl_field(role="mail.auth_url", default="")
    provider: str | None = sdl_field(role="mail.provider")

class ComposeSentResult(sdl.Entity):
    """Panel compose-send confirmation — returned by compose_send()."""

    kind: str = "compose_sent"
    sent: bool = True
    mode: str | None = sdl_field(role="mail.mode")
    recipient: str | None = sdl_field(role="mail.recipient")
