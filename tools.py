"""
Mail Client — Tool class (SDK v2.0.0 / Webbee Single Voice).

Every ``@sdk_ext.tool`` method is a thin delegator into ``handlers_*.py``
— business logic stays where it lives. The Pydantic ``output_schema`` on
each tool is what Webbee Narrator grounds user-facing prose against.

File-size exception (CLAUDE.md rule 6): this file exceeds the 300-line
ceiling. Reason — SDK v2.0.0 requires every tool method to live on the
concrete Extension subclass (``__init_subclass__`` walks ``cls.__dict__``
only, not the MRO, and explicitly rejects mixin inheritance with
"mixing tool definitions across MRO is out-of-scope for v2"). With 35
tools inherent to the mail domain (connect × 4 providers, inbox/folder
read/search, send/reply/forward, 7 single-ops, 4 bulk ops, contacts
CRUD + sync, 5 panel tools), there is no structural way to shrink this
file without discarding tools or cross-MRO registration, neither of
which the kernel supports. Each tool is kept to its minimum delegator
shape; all business logic is in ``handlers_*.py``.
"""
from __future__ import annotations

from imperal_sdk import Extension
from imperal_sdk import ext as sdk_ext

import handlers_connect as _hc
import handlers_inbox as _hi
import handlers_manage as _hm
import handlers_contacts as _hct
import handlers_panel_actions as _hp
import handlers_panel_compose as _hpc

from schemas import (
    AccountDisconnected, AccountSwitched, AccountsStatus,
    BulkOperationResult, ComposeSendResult, ConnectImapResult,
    ConnectOAuthResult, ContactAdded, ContactDeleted, ContactsList,
    ContactsSyncResult, EmailBody, FolderCountsResult, InboxPageResult,
    MailActionResult, OAuthUrlResult, OperationResult,
    SearchResult, SendResult, ThreadView,
)


class MailExtension(Extension):
    """Mail Client — Google / Microsoft / Yahoo / IMAP email tool provider.

    All tools return Pydantic ``output_schema`` payloads so Webbee Narrator
    can ground prose deterministically.
    """

    app_id = "mail"

    # ── Accounts ─────────────────────────────────────────────────────────────

    @sdk_ext.tool(description="Connect a Google / Gmail account via OAuth. Returns the authorisation URL or confirms an existing connection.", output_schema=ConnectOAuthResult)
    async def connect(self, ctx) -> ConnectOAuthResult:
        return await _hc.impl_connect(ctx)

    @sdk_ext.tool(description="Connect a Microsoft Outlook / Office 365 account via OAuth. Returns the authorisation URL or confirms an existing connection.", output_schema=ConnectOAuthResult)
    async def connect_microsoft(self, ctx) -> ConnectOAuthResult:
        return await _hc.impl_connect_microsoft(ctx)

    @sdk_ext.tool(description="Connect a Yahoo / AOL account via OAuth. Returns the authorisation URL or confirms an existing connection.", output_schema=ConnectOAuthResult)
    async def connect_yahoo(self, ctx) -> ConnectOAuthResult:
        return await _hc.impl_connect_yahoo(ctx)

    @sdk_ext.tool(description="Connect any email account via IMAP/SMTP — iCloud, Zoho, custom domains. Auto-detects server settings when possible.", output_schema=ConnectImapResult)
    async def connect_imap(self, ctx, email_addr: str, password: str, imap_host: str = "", smtp_host: str = "", imap_port: int = 0, smtp_port: int = 0) -> ConnectImapResult:
        return await _hc.impl_connect_imap(ctx, email_addr=email_addr, password=password, imap_host=imap_host, smtp_host=smtp_host, imap_port=imap_port, smtp_port=smtp_port)

    @sdk_ext.tool(description="Show all connected email accounts with provider type, active flag, and unread count for each.", output_schema=AccountsStatus)
    async def status(self, ctx) -> AccountsStatus:
        return await _hc.impl_status(ctx)

    @sdk_ext.tool(description="Switch the active email account used by subsequent inbox / read / send operations.", output_schema=AccountSwitched)
    async def switch_account(self, ctx, account: str) -> AccountSwitched:
        return await _hc.impl_switch_account(ctx, account=account)

    @sdk_ext.tool(description="Remove a connected email account. Purges stored credentials and cached inbox pages.", output_schema=AccountDisconnected)
    async def disconnect(self, ctx, account: str) -> AccountDisconnected:
        return await _hc.impl_disconnect(ctx, account=account)

    # ── Inbox / Read / Search ────────────────────────────────────────────────

    @sdk_ext.tool(description="Show inbox messages with cursor-based pagination. Supports folder keys inbox / sent / spam / trash / drafts / starred.", output_schema=InboxPageResult)
    async def inbox(self, ctx, folder: str = "inbox", cursor: str = "", limit: int = 20, account: str = "") -> InboxPageResult:
        return await _hi.impl_inbox(ctx, folder=folder, cursor=cursor, limit=limit, account=account)

    @sdk_ext.tool(description="Read the full content of an email message by its ID — subject, sender, body (text + html), attachments.", output_schema=EmailBody)
    async def read_email(self, ctx, message_id: str, account: str = "") -> EmailBody:
        return await _hi.impl_read_email(ctx, message_id=message_id, account=account)

    @sdk_ext.tool(description="Search emails by sender, subject, keywords, or any provider-supported query — Gmail search syntax is honoured.", output_schema=SearchResult)
    async def search(self, ctx, query: str, max_results: int = 10, account: str = "") -> SearchResult:
        return await _hi.impl_search(ctx, query=query, max_results=max_results, account=account)

    @sdk_ext.tool(description="Browse a mail folder with cursor-based pagination — sent, spam, trash, starred, drafts, all, archive, unread.", output_schema=InboxPageResult)
    async def folder(self, ctx, folder: str, cursor: str = "", limit: int = 20, account: str = "") -> InboxPageResult:
        return await _hi.impl_folder(ctx, folder=folder, cursor=cursor, limit=limit, account=account)

    @sdk_ext.tool(description="View a full email thread / conversation by thread ID — returns all messages in reply chronology.", output_schema=ThreadView)
    async def get_thread(self, ctx, thread_id: str, account: str = "") -> ThreadView:
        return await _hi.impl_get_thread(ctx, thread_id=thread_id, account=account)

    # ── Send / Reply / Forward ───────────────────────────────────────────────

    @sdk_ext.tool(description="Send a new email. Requires to, subject, and body; cc / bcc optional. Uses the active account unless specified.", output_schema=SendResult)
    async def send(self, ctx, to: str, subject: str, body: str, cc: str = "", bcc: str = "", account: str = "") -> SendResult:
        return await _hi.impl_send(ctx, to=to, subject=subject, body=body, cc=cc, bcc=bcc, account=account)

    @sdk_ext.tool(description="Reply to an email. Uses the message_id you read last if not specified; body required. Adds In-Reply-To headers.", output_schema=SendResult)
    async def reply(self, ctx, body: str, message_id: str = "", to: str = "", cc: str = "", bcc: str = "", account: str = "") -> SendResult:
        return await _hi.impl_reply(ctx, body=body, message_id=message_id, to=to, cc=cc, bcc=bcc, account=account)

    @sdk_ext.tool(description="Forward an email to a new recipient with an optional comment prepended to the forwarded message body.", output_schema=SendResult)
    async def forward(self, ctx, message_id: str, to: str, comment: str = "", account: str = "") -> SendResult:
        return await _hi.impl_forward(ctx, message_id=message_id, to=to, comment=comment, account=account)

    # ── Single-message management ────────────────────────────────────────────

    @sdk_ext.tool(description="Archive an email — moves it out of the inbox without deleting.", output_schema=OperationResult)
    async def archive(self, ctx, message_id: str, account: str = "") -> OperationResult:
        return await _hm.impl_archive(ctx, message_id=message_id, account=account)

    @sdk_ext.tool(description="Move an email to Trash. Recoverable until trash is purged.", output_schema=OperationResult)
    async def delete(self, ctx, message_id: str, account: str = "") -> OperationResult:
        return await _hm.impl_delete(ctx, message_id=message_id, account=account)

    @sdk_ext.tool(description="Mark an email as read — clears the unread flag.", output_schema=OperationResult)
    async def mark_read(self, ctx, message_id: str, account: str = "") -> OperationResult:
        return await _hm.impl_mark_read(ctx, message_id=message_id, account=account)

    @sdk_ext.tool(description="Mark an email as unread — restores the unread flag.", output_schema=OperationResult)
    async def mark_unread(self, ctx, message_id: str, account: str = "") -> OperationResult:
        return await _hm.impl_mark_unread(ctx, message_id=message_id, account=account)

    @sdk_ext.tool(description="Star or unstar an email — toggles the starred / important flag.", output_schema=OperationResult)
    async def star(self, ctx, message_id: str, starred: bool = True, account: str = "") -> OperationResult:
        return await _hm.impl_star(ctx, message_id=message_id, starred=starred, account=account)

    @sdk_ext.tool(description="Move an email between folders — INBOX, Junk, Trash, Archive, or any provider-supported label/folder name.", output_schema=OperationResult)
    async def move(self, ctx, message_id: str, from_folder: str, to_folder: str, account: str = "") -> OperationResult:
        return await _hm.impl_move(ctx, message_id=message_id, from_folder=from_folder, to_folder=to_folder, account=account)

    @sdk_ext.tool(description="Permanently delete an email — bypasses Trash, cannot be recovered by the provider.", output_schema=OperationResult)
    async def purge(self, ctx, message_id: str, from_folder: str = "Trash", account: str = "") -> OperationResult:
        return await _hm.impl_purge(ctx, message_id=message_id, from_folder=from_folder, account=account)

    # ── Bulk operations ──────────────────────────────────────────────────────

    @sdk_ext.tool(description="Archive multiple emails at once. Expects a comma-separated list of message IDs.", output_schema=BulkOperationResult)
    async def bulk_archive(self, ctx, message_ids: str, account: str = "") -> BulkOperationResult:
        return await _hm.impl_bulk_archive(ctx, message_ids=message_ids, account=account)

    @sdk_ext.tool(description="Delete (move to Trash) multiple emails at once. Expects a comma-separated list of message IDs.", output_schema=BulkOperationResult)
    async def bulk_delete(self, ctx, message_ids: str, account: str = "") -> BulkOperationResult:
        return await _hm.impl_bulk_delete(ctx, message_ids=message_ids, account=account)

    @sdk_ext.tool(description="Mark multiple emails as read in one batch. Expects a comma-separated list of message IDs.", output_schema=BulkOperationResult)
    async def bulk_mark_read(self, ctx, message_ids: str, account: str = "") -> BulkOperationResult:
        return await _hm.impl_bulk_mark_read(ctx, message_ids=message_ids, account=account)

    @sdk_ext.tool(description="Mark multiple emails as unread in one batch. Expects a comma-separated list of message IDs.", output_schema=BulkOperationResult)
    async def bulk_mark_unread(self, ctx, message_ids: str, account: str = "") -> BulkOperationResult:
        return await _hm.impl_bulk_mark_unread(ctx, message_ids=message_ids, account=account)

    # ── Contacts ─────────────────────────────────────────────────────────────

    @sdk_ext.tool(description="Show email contacts — search-filterable, sorted by name.", output_schema=ContactsList)
    async def contacts(self, ctx, search: str = "", limit: int = 50) -> ContactsList:
        return await _hct.impl_contacts(ctx, search=search, limit=limit)

    @sdk_ext.tool(description="Add a contact manually by email address, optionally with a display name.", output_schema=ContactAdded)
    async def add_contact(self, ctx, email: str, name: str = "") -> ContactAdded:
        return await _hct.impl_add_contact(ctx, email=email, name=name)

    @sdk_ext.tool(description="Import contacts from a connected email — Google People API, Outlook address book, or recent email header harvest.", output_schema=ContactsSyncResult)
    async def sync_contacts(self, ctx, account: str = "") -> ContactsSyncResult:
        return await _hct.impl_sync_contacts(ctx, account=account)

    @sdk_ext.tool(description="Remove a contact from the address book by email address.", output_schema=ContactDeleted)
    async def delete_contact(self, ctx, email: str) -> ContactDeleted:
        return await _hct.impl_delete_contact(ctx, email=email)

    # ── Panel-facing tools (UI Call dispatch) ────────────────────────────────

    @sdk_ext.tool(description="Direct mail action from the UI panel — archive, delete, spam, mark_read, mark_unread, star. Accepts one or many IDs.", output_schema=MailActionResult)
    async def mail_action(self, ctx, action: str, message_id: str = "", message_ids: list[str] | None = None, account: str = "") -> MailActionResult:
        return await _hp.impl_mail_action(ctx, action=action, message_id=message_id, message_ids=list(message_ids or []), account=account)

    @sdk_ext.tool(description="Get unread counts per folder — INBOX, sent, drafts, spam, trash, starred — for UI sidebar badge rendering.", output_schema=FolderCountsResult)
    async def folder_counts(self, ctx, account: str = "") -> FolderCountsResult:
        return await _hp.impl_folder_counts(ctx, account=account)

    @sdk_ext.tool(description="Get an OAuth authorisation URL for the given provider (google or microsoft) — used by the add-account panel.", output_schema=OAuthUrlResult)
    async def get_oauth_url(self, ctx, provider: str) -> OAuthUrlResult:
        return await _hp.impl_get_oauth_url(ctx, provider=provider)

    @sdk_ext.tool(description="Connect an IMAP email account from the add-account panel wizard — tests credentials, persists encrypted password.", output_schema=ConnectImapResult)
    async def add_imap(self, ctx, email: str, password: str, imap_host: str = "", smtp_host: str = "", imap_port: int = 993, smtp_port: int = 587) -> ConnectImapResult:
        return await _hp.impl_add_imap(ctx, email=email, password=password, imap_host=imap_host, smtp_host=smtp_host, imap_port=imap_port, smtp_port=smtp_port)

    @sdk_ext.tool(description="Send an email from the compose panel — supports reply, forward, and new-message modes.", output_schema=ComposeSendResult)
    async def compose_send(self, ctx, mode: str = "new", message_id: str = "", to: str = "", subject: str = "", body: str = "", cc: str = "", bcc: str = "", account: str = "", attachments: list | None = None) -> ComposeSendResult:
        return await _hpc.impl_compose_send(ctx, mode=mode, message_id=message_id, to=to, subject=subject, body=body, cc=cc, bcc=bcc, account=account, attachments=list(attachments or []))
