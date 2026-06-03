"""Pydantic input parameter models for @chat.function registration."""
from __future__ import annotations

from pydantic import BaseModel, Field, AliasChoices, field_validator


class EmptyParams(BaseModel):
    """No parameters required — satisfies V17 for parameterless @chat.function handlers."""


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
    query: str = Field(description="Search query. Gmail syntax: from:x@y.com, subject:keyword, after:2024/01/01, before:2025/01/01, label:name. Free-text for Outlook/IMAP.")
    max_results: int = Field(default=20, description="Max results (1-200). For 'find first ever / oldest' use oldest_first=true + max_results=1.")
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
        description="Email body (plain text)",
    )
    cc: str = Field(default="", description="CC recipients (comma-separated)")
    bcc: str = Field(default="", description="BCC recipients (comma-separated)")
    account: str = Field(default="", description="Account email or ID")


class ReplyParams(BaseModel):
    body: str = Field(
        default="",
        validation_alias=AliasChoices("body", "content", "message", "text"),
        description="Reply body text",
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
    from_contains: str = Field(default="", description="Match emails where sender contains this string or domain (e.g. 'linkedin.com', 'migrations@webhostmost.org')")
    from_emails: list[str] = Field(default_factory=list, description="List of specific sender email addresses — all emails from these addresses match. E.g. ['alice@example.com', 'bob@example.com']")
    subject_contains: str = Field(default="", description="Match emails where subject contains this string")
    folder: str = Field(default="", description="Restrict to this folder (default: search all)")
    color: str = Field(default="blue", description="Badge color: blue/green/red/yellow/purple/orange")


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
    max_results: int = Field(default=20, description="Max emails to return when applying filter")


# ── Automation rules ──────────────────────────────────────────────────────────

class CreateForwardRuleParams(BaseModel):
    """Create a forwarding rule — auto-forward matching emails to an address."""
    name: str = Field(description="Rule name")
    to_address: str = Field(description="Forward destination email address")
    from_contains: str = Field(default="", description="Only forward emails from senders matching this (empty = all)")
    subject_contains: str = Field(default="", description="Only forward emails with subject matching this (empty = all)")
    comment: str = Field(default="", description="Prepended note on the forwarded email")


class CreateAutoreplyParams(BaseModel):
    """Create an auto-reply rule — send automated responses to incoming emails."""
    name: str = Field(description="Rule name (e.g. 'Out of office')")
    template: str = Field(description="Auto-reply message body")
    subject_prefix: str = Field(default="Auto: ", description="Prefix added to reply subject")
    schedule_type: str = Field(default="time_window",
                               description="'always' = reply to all, 'time_window' = only outside business hours")
    days: list[int] = Field(default=[0, 1, 2, 3, 4],
                            description="Business days (0=Mon..6=Sun). Auto-reply fires OUTSIDE these days when type=time_window")
    start_time: str = Field(default="09:00",
                            description="Business hours start HH:MM — auto-reply fires OUTSIDE this window")
    end_time: str = Field(default="18:00",
                          description="Business hours end HH:MM")
    timezone: str = Field(default="UTC", description="Timezone for schedule (e.g. 'Europe/Chisinau', 'UTC')")
    from_contains: str = Field(default="", description="Only reply to emails from senders matching this (empty = all)")


class RuleIdParam(BaseModel):
    """Single rule ID selector."""
    rule_id: str = Field(description="Rule ID from list_rules()")


class ToggleRuleParams(BaseModel):
    """Enable or disable a rule."""
    rule_id: str = Field(description="Rule ID from list_rules()")
    enabled: bool = Field(description="True to enable, False to disable")


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
