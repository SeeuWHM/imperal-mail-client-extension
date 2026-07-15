"""Pydantic input parameter models for @chat.function registration."""
from __future__ import annotations

from pydantic import BaseModel, Field, AliasChoices, field_validator


class EmptyParams(BaseModel):
    """No parameters required — satisfies V17 for parameterless @chat.function handlers."""


class AccountParam(BaseModel):
    """Single optional account selector."""
    account: str = Field(default="", description="Account email or ID (omit for active account)")


class CountParams(BaseModel):
    """count_emails — exact email count by folder/state or by query."""
    folder: str = Field(default="", description="Folder/state to count: all | unread | spam | archive | inbox | today | sent | trash. Leave empty if using query.")
    query: str = Field(default="", description="Gmail-style query for a date/sender count, e.g. 'newer_than:1d', 'after:2026/06/05 before:2026/06/06', 'from:reddit'. Leave empty if using folder.")
    account: str = Field(default="", description="Account email or ID. Omit to count across ALL connected accounts.")


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
    query: str = Field(description="Search query. Gmail syntax: from:x@y.com, subject:keyword, after:2024/01/01, before:2025/01/01, label:name. Free-text for Outlook/IMAP.")
    max_results: int = Field(default=50, description="Max results to fetch (1-200). Use 200 when counting all emails from a sender or doing bulk operations. Default 50 is enough for showing recent results.")
    oldest_first: bool = Field(default=False, description="Sort oldest first — use to find the first/earliest email matching the query.")
    folder: str = Field(default="", description="IMAP only: folder to search. Gmail/Microsoft always search all folders.")
    account: str = Field(default="", description="Account email or ID")


class ThreadParams(BaseModel):
    thread_id: str = Field(description="Thread ID")
    account: str = Field(default="", description="Account email or ID")


class SendParams(BaseModel):
    to: str = Field(description="Recipient email address")
    subject: str = Field(default="", description="Email subject (auto-generated from body if omitted)")
    body: str = Field(
        default="",
        validation_alias=AliasChoices("body", "content", "message", "text"),
        description="Email body — plain text by default, or HTML if is_html=true",
    )
    is_html: bool = Field(
        default=False,
        description="Set true when body contains HTML markup (e.g. <h2>, <strong>, <ul>) so it "
                     "renders as rich formatting instead of showing raw tags as plain text.",
    )
    cc: str = Field(default="", description="CC recipients (comma-separated)")
    bcc: str = Field(default="", description="BCC recipients (comma-separated)")
    account: str = Field(default="", description="Account email or ID")


class ReplyParams(BaseModel):
    body: str = Field(
        default="",
        validation_alias=AliasChoices("body", "content", "message", "text"),
        description="Reply body text — plain text by default, or HTML if is_html=true",
    )
    is_html: bool = Field(
        default=False,
        description="Set true when body contains HTML markup so it renders as rich formatting.",
    )
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


def _coerce_ids(v) -> str:
    """Coerce list[str] or single str to comma-separated string of message IDs.

    LLM often passes a list from a previous search/inbox result instead of
    the raw CSV string. Both formats are accepted and normalised here.
    """
    if isinstance(v, list):
        return ",".join(str(x).strip() for x in v if x)
    return str(v or "")


class BulkParams(BaseModel):
    message_ids: str = Field(description="Comma-separated message IDs (or list from previous search/inbox result)")
    account: str = Field(default="", description="Account email or ID")

    @field_validator("message_ids", mode="before")
    @classmethod
    def _coerce(cls, v): return _coerce_ids(v)


class BulkMoveParams(BaseModel):
    message_ids: str = Field(description="Comma-separated message IDs (or list from previous search/inbox result)")
    from_folder: str = Field(description="Source folder (e.g. INBOX, spam, trash)")
    to_folder: str = Field(description="Destination folder (e.g. spam, INBOX, archive)")
    account: str = Field(default="", description="Account email or ID")

    @field_validator("message_ids", mode="before")
    @classmethod
    def _coerce(cls, v): return _coerce_ids(v)


class BulkStarParams(BaseModel):
    message_ids: str = Field(description="Comma-separated message IDs (or list from previous search/inbox result)")
    starred: bool = Field(default=True, description="True to star, False to unstar")
    account: str = Field(default="", description="Account email or ID")

    @field_validator("message_ids", mode="before")
    @classmethod
    def _coerce(cls, v): return _coerce_ids(v)


class BulkPurgeParams(BaseModel):
    message_ids: str = Field(description="Comma-separated message IDs (or list from previous search/inbox result)")
    from_folder: str = Field(default="Trash", description="Folder to purge from (default: Trash)")
    account: str = Field(default="", description="Account email or ID")

    @field_validator("message_ids", mode="before")
    @classmethod
    def _coerce(cls, v): return _coerce_ids(v)


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
    to: str = Field(default="", description="Recipient email address(es)")
    subject: str = Field(default="", description="Subject (required for new emails)")
    body: str = Field(default="", description="Email body (plain text or HTML)")
    mode: str = Field(default="new", description="Mode: new, reply, forward")
    message_id: str = Field(default="", description="Original message ID (for reply/forward)")
    cc: str = Field(default="", description="CC recipients")
    bcc: str = Field(default="", description="BCC recipients")
    account: str = Field(default="", description="Account email or ID")

    @field_validator("to", "cc", "bcc", mode="before")
    @classmethod
    def _coerce_tags_to_csv(cls, v):
        """TagInput submits a list — coerce to comma-separated string."""
        if isinstance(v, list):
            return ", ".join(str(x) for x in v if x)
        return str(v or "")


# ── Smart filters ─────────────────────────────────────────────────────────────

class CreateFilterParams(BaseModel):
    """Create a smart mailbox filter (virtual folder based on search criteria)."""
    name: str = Field(description="Filter name shown as smart folder label")
    from_contains: str = Field(default="", description="Match emails where sender contains this string or domain (e.g. 'linkedin.com')")
    from_emails: list[str] = Field(default_factory=list, description="List of specific sender email addresses (e.g. ['alice@example.com', 'bob@example.com'])")
    subject_contains: str = Field(default="", description="Match emails where subject contains this string")
    folder: str = Field(default="", description="Restrict to this folder (default: search all)")
    color: str = Field(default="blue", description="Badge color: blue/green/red/yellow/purple/orange")
    account: str = Field(default="", description="Email account this filter belongs to (default: current active account)")


class UpdateFilterParams(BaseModel):
    """Update an existing smart filter."""
    filter_id: str = Field(description="Filter ID from list_filters()")
    name: str = Field(default="", description="New name (empty = keep current)")
    from_contains: str = Field(default="__keep__", description="New from filter (omit = keep current)")
    subject_contains: str = Field(default="__keep__", description="New subject filter (omit = keep current)")
    color: str = Field(default="", description="New color (empty = keep current)")


class FilterIdParam(BaseModel):
    """Single filter ID selector."""
    filter_id: str = Field(description="Filter ID from list_filters()")
    max_results: int = Field(default=100, description="Max emails to return when applying filter (1-200)")


# ── Folder preferences ────────────────────────────────────────────────────────

_FOLDER_CANONICAL = {
    "inbox": "INBOX", "INBOX": "INBOX",
    "sent": "sent",   "drafts": "drafts",
    "spam": "spam",   "trash": "trash",
    "starred": "starred", "archive": "archive",
    # Russian aliases
    "входящие": "INBOX", "отправленные": "sent", "черновики": "drafts",
    "спам": "spam", "корзина": "trash", "помеченные": "starred", "архив": "archive",
}


class SetFolderPrefsParams(BaseModel):
    """Set which mail folders are visible in the inbox panel."""
    visible_folders: list[str] = Field(
        default_factory=list,
        description="Ordered list of folders to show. Use: INBOX, sent, drafts, spam, trash, starred, archive. Empty list = show all."
    )

    @field_validator("visible_folders", mode="before")
    @classmethod
    def _normalize(cls, v):
        """Accept comma-separated string OR list, normalize to canonical folder keys."""
        if isinstance(v, str):
            v = [x.strip() for x in v.replace(",", " ").split() if x.strip()]
        if not isinstance(v, list):
            return []
        return [_FOLDER_CANONICAL.get(x.strip().lower(), x.strip()) for x in v if x.strip()]


# ── Unified action params (single / bulk / all-matching) ─────────────────────
# Each function accepts message_ids OR query — never both.
# message_ids: comma-separated IDs (1 or many).
# query:       search expression → acts on ALL matching until none remain.

class ArchiveParams(BaseModel):
    message_ids: str = Field(
        default="",
        description="ID(s) to archive — single or comma-separated list from inbox()/search(). "
                    "Provide this OR query, not both.",
    )
    query: str = Field(
        default="",
        description="Archive ALL emails matching this query until none remain. "
                    "Gmail: 'from:linkedin', 'category:promotions', 'older_than:30d'. "
                    "Provide this OR message_ids.",
    )
    account: str = Field(default="", description="Account email or ID (omit for active account)")

    @field_validator("message_ids", mode="before")
    @classmethod
    def _coerce(cls, v): return _coerce_ids(v)


class DeleteParams(BaseModel):
    message_ids: str = Field(
        default="",
        description="ID(s) to move to Trash — single or comma-separated. "
                    "Recoverable (Gmail 30 days, Outlook until emptied). "
                    "Provide this OR query.",
    )
    query: str = Field(
        default="",
        description="Move ALL emails matching this query to Trash. "
                    "Recoverable. Provide this OR message_ids.",
    )
    account: str = Field(default="", description="Account email or ID (omit for active account)")

    @field_validator("message_ids", mode="before")
    @classmethod
    def _coerce(cls, v): return _coerce_ids(v)


class MarkReadParams(BaseModel):
    message_ids: str = Field(
        default="",
        description="ID(s) to mark — single or comma-separated. Provide this OR query.",
    )
    query: str = Field(
        default="",
        description="Act on ALL emails matching this query. Provide this OR message_ids.",
    )
    read: bool = Field(
        default=True,
        description="True = mark as read (clear unread badge). "
                    "False = mark as unread (restore unread badge).",
    )
    account: str = Field(default="", description="Account email or ID (omit for active account)")

    @field_validator("message_ids", mode="before")
    @classmethod
    def _coerce(cls, v): return _coerce_ids(v)


class StarUnifiedParams(BaseModel):
    message_ids: str = Field(
        default="",
        description="ID(s) to star/unstar — single or comma-separated. Provide this OR query.",
    )
    query: str = Field(
        default="",
        description="Star/unstar ALL emails matching this query. Provide this OR message_ids.",
    )
    starred: bool = Field(
        default=True,
        description="True = add star/flag. False = remove star/flag.",
    )
    account: str = Field(default="", description="Account email or ID (omit for active account)")

    @field_validator("message_ids", mode="before")
    @classmethod
    def _coerce(cls, v): return _coerce_ids(v)


class MoveUnifiedParams(BaseModel):
    message_ids: str = Field(
        default="",
        description="ID(s) to move — single or comma-separated. Provide this OR query.",
    )
    query: str = Field(
        default="",
        description="Move ALL emails matching this query. Provide this OR message_ids.",
    )
    to_folder: str = Field(
        description="Destination folder: 'spam', 'INBOX', 'Archive', 'trash', or custom label. "
                    "Gmail uses label names; Outlook maps common names automatically.",
    )
    from_folder: str = Field(
        default="INBOX",
        description="Source folder when using message_ids (default: INBOX).",
    )
    account: str = Field(default="", description="Account email or ID (omit for active account)")

    @field_validator("message_ids", mode="before")
    @classmethod
    def _coerce(cls, v): return _coerce_ids(v)


class PurgeUnifiedParams(BaseModel):
    message_ids: str = Field(
        default="",
        description="ID(s) to permanently delete — single or comma-separated. "
                    "IRREVERSIBLE — cannot be recovered. Provide this OR query.",
    )
    query: str = Field(
        default="",
        description="Permanently delete ALL emails matching this query. "
                    "IRREVERSIBLE. Provide this OR message_ids.",
    )
    from_folder: str = Field(
        default="Trash",
        description="Folder to purge from when using message_ids (default: Trash).",
    )
    account: str = Field(default="", description="Account email or ID (omit for active account)")

    @field_validator("message_ids", mode="before")
    @classmethod
    def _coerce(cls, v): return _coerce_ids(v)


class ApplyActionsParams(BaseModel):
    operations: list[str] = Field(
        description="One or more operations applied to the SAME emails in a single efficient call. "
                    "Allowed: 'archive', 'read', 'unread', 'star', 'unstar', 'delete'. "
                    "Example: ['read', 'archive'] = mark as read AND archive together. "
                    "Gmail: combined into ONE batchModify call. "
                    "Use this instead of calling archive + mark_read separately.",
    )
    message_ids: str = Field(
        default="",
        description="ID(s) — single or comma-separated. Provide this OR query.",
    )
    query: str = Field(
        default="",
        description="Apply to ALL emails matching this query. Provide this OR message_ids.",
    )
    account: str = Field(default="", description="Account email or ID (omit for active account)")

    @field_validator("message_ids", mode="before")
    @classmethod
    def _coerce(cls, v): return _coerce_ids(v)


class InboxCleanupParams(BaseModel):
    categories: list[str] = Field(
        default_factory=list,
        description="Email categories to clean up. Allowed: 'promotions', 'social', "
                    "'newsletters', 'outreach', 'updates', 'forums', 'spam'. "
                    "Gmail maps to native category: labels; Outlook/IMAP use pattern matching. "
                    "Combine with from_senders for more precision.",
    )
    from_senders: list[str] = Field(
        default_factory=list,
        description="Sender patterns to clean — e.g. ['linkedin', 'noreply@company.com']. "
                    "Works on all providers. Combined with categories via OR.",
    )
    older_than_days: int = Field(
        default=0,
        description="Restrict to emails older than N days (0 = no age filter).",
    )
    operation: str = Field(
        default="archive",
        description="What to do: 'archive' (recoverable, default), 'delete' (Trash), "
                    "'read' (mark as read), 'star' (flag for review).",
    )
    account: str = Field(default="", description="Account email or ID (omit for active account)")


class InboxAnalyticsParams(BaseModel):
    period_days: int = Field(
        default=90,
        description="Look-back period in days: 7, 30, 90 (default), 365.",
    )
    group_by: str = Field(
        default="sender",
        description="Grouping mode: 'sender' = top individual senders; "
                    "'domain' = top sending domains (useful for newsletter/outreach analysis).",
    )
    limit: int = Field(default=10, description="Rows to return (max 50).")
    account: str = Field(default="", description="Account email or ID (omit for active account)")
