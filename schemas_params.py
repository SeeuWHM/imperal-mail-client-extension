"""Pydantic input parameter models for @chat.function registration."""
from __future__ import annotations

from pydantic import BaseModel, Field, AliasChoices


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
    query: str = Field(description="Search query — Gmail syntax supported")
    max_results: int = Field(default=10, description="Max results to return")
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
