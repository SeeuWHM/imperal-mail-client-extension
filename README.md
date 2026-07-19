# imperal-mail-client-extension

[![Imperal SDK](https://img.shields.io/badge/imperal--sdk-5.9.11-blue)](https://pypi.org/project/imperal-sdk/)
[![Version](https://img.shields.io/badge/version-6.4.0-green)](https://github.com/SeeuWHM/imperal-mail-client-extension/releases)
[![License](https://img.shields.io/badge/license-LGPL--2.1-orange)](LICENSE)
[![Platform](https://img.shields.io/badge/platform-Imperal%20Cloud-purple)](https://panel.imperal.io)

**Enterprise AI email client extension for [Imperal Cloud](https://panel.imperal.io).**

Connect Google, Microsoft Outlook, Yahoo, AOL, iCloud, or any IMAP/SMTP server. Manage email through natural language or the panel UI — read, send, reply, archive, search, bulk operations, and now read the actual TEXT content of attachments you received.

---

## What It Does

Talk to it naturally:

```
"show my inbox"
"read the latest email from John"
"what does the PDF attached to that invoice email say?"
"reply saying I'll be there at 3pm"
"archive all emails from newsletter@example.com"
"search for invoices from last month"
"show my unread emails in spam"
```

Or use the panel — click emails to open them, reply/forward with one click, multi-select for bulk actions.

---

## Providers

| Provider | Auth | API |
|----------|------|-----|
| Google Gmail | OAuth2 | Gmail REST API |
| Microsoft Outlook / O365 | OAuth2 | Microsoft Graph API |
| Yahoo / AOL | App Password (OAuth pending approval) | IMAP + SMTP |
| iCloud / me.com | App-Specific Password | IMAP + SMTP |
| Any IMAP server | Password | IMAP + SMTP |

**IMAP auto-detect:** 19 domains mapped automatically (Gmail, Outlook, Yahoo, iCloud, Zoho, Yandex, Mail.ru, etc.)

---

## Capabilities

### Tools (47 total: 45 @chat.function + 2 skeleton)

**Account management (7):** `connect`, `connect_microsoft`, `connect_yahoo`, `connect_imap`, `status`, `switch_account`, `disconnect`

**Read (6):** `inbox`, `read_email`, `read_attachment`, `search`, `folder`, `get_thread`

**Write (within Read group):** `send`, `reply`, `forward`

**Analytics:** `inbox_analytics`, `count_emails`

**Manage (7):** `archive`, `delete`, `mark_read`, `star`, `move`, `apply_actions`, `purge`

**Bulk cleanup:** `inbox_cleanup`

**Contacts (4):** `contacts`, `add_contact`, `sync_contacts`, `delete_contact`

**Panel-only:** `compose_send`, `mail_action`, `get_oauth_url`, `add_imap`

**Folder counts:** `folder_counts`

**Smart filters / virtual folders (5):** `create_filter`, `list_filters`, `apply_filter`, `update_filter`, `delete_filter`

**Folder prefs & custom folders (5):** `set_folder_prefs`, `get_folder_prefs`, `list_mail_folders`, `create_mail_folder`, `delete_mail_folder`

### `read_attachment` — reading what you received

`read_email()` has always reported an attachment's filename/size/mime — it never opened it.
`read_attachment(message_id, attachment_id)` now downloads the real bytes from the
provider (Gmail attachments API / Microsoft Graph fileAttachment / IMAP MIME walk)
and extracts the TEXT via the same shared doc-extractor engine File Reader uses
(PDF, DOCX, XLSX, PPTX, images via OCR/vision, plain text, CSV, …) — under its own
storage partition, so a read attachment's text never mixes with File Reader's own
uploaded documents. Call `read_email()` first to get a valid `attachment_id` from
its `attachments[]` list.

### `file_sink` — the other direction

`send` also accepts a file upload as the message body (`text/*`, `text/html`) —
drop a document onto compose and its text becomes the email body.

---

## Architecture (v6.4.0 / SDK 5.9.11 — 35 top-level modules + 17 provider modules)

```
imperal-mail-client-extension/
├── main.py                   # Entry point — sys.modules cleanup + imports
├── app.py                    # Extension instance (SDK v5.x) + ChatExtension + lifecycle
├── schemas.py                # Pydantic response schemas + re-export of schemas_params
├── schemas_params.py         # Pydantic input param models for @chat.function handlers
├── schemas_sdl.py            # SDL entity classes (mail.* roles) incl. AttachmentEntity
├── schemas_sdl_builders.py   # impl_result → SDL entity builders
├── schemas_sdl_rules.py       # SDL entities for filters / folder prefs
├── schemas_sdl_builders_rules.py # builders for filter/folder-pref SDL entities
├── ctx_helpers.py            # _user_id / _get_acc / _oauth_state (break import cycle)
├── cache_model_defs.py       # Pure Pydantic cache models (InboxMessages, UnreadSummary, AccountList)
├── cache_models.py           # ctx.cache model registrations
├── skeleton.py               # @ext.skeleton: inbox summary (TTL 60s, alert=True) + alert tool
├── handlers_connect.py       # connect / connect_microsoft / connect_yahoo / connect_imap
│                             # status / switch_account / disconnect
├── handlers_inbox_impl.py    # impl_* business logic incl. impl_read_attachment
├── handlers_inbox.py         # inbox / read_email / read_attachment / search / folder
│                             # get_thread / send / reply / forward / inbox_analytics
├── handlers_manage_impl.py   # impl_* business logic for manage ops
├── handlers_manage.py        # archive / delete / mark_read / star / move
│                             # apply_actions / inbox_cleanup / purge
├── handlers_cleanup_impl.py  # impl_inbox_analytics, inbox_cleanup helpers
├── handlers_contacts.py      # contacts / add_contact / sync_contacts / delete_contact
├── handlers_panel_actions.py # mail_action / folder_counts / get_oauth_url / add_imap / count_emails
├── handlers_panel_compose.py # compose_send
├── handlers_filters.py       # create/list/apply/update/delete_filter
├── handlers_folders.py       # set/get_folder_prefs / list/create/delete_mail_folder
├── handlers_oauth_callback.py # OAuth redirect handling
├── handlers_ui.py            # shared UI-building helpers for ActionResult previews
├── panels.py, panels_*.py    # Panel UI (inbox list, email viewer, compose, accounts, filters)
└── providers/
    ├── base.py                # BaseMailProvider ABC — ok()/err() + download_attachment() default
    ├── google.py               # GoogleMailProvider (Read + Write mixins)
    ├── google_read.py          # Gmail read ops + download_attachment (attachments.get, base64url)
    ├── google_write.py         # Gmail send/reply/forward/archive/delete/etc.
    ├── microsoft.py            # MicrosoftMailProvider + download_attachment (Graph fileAttachment, base64)
    ├── microsoft_write.py       # Graph send/reply/forward/etc.
    ├── imap.py                 # ImapMailProvider + download_attachment (MIME walk by part index)
    ├── imap_read.py             # Re-exports message-level IMAP ops
    ├── imap_read_message.py     # _walk_imap_attachments, _sync_imap_download_attachment
    ├── imap_connection.py       # IMAP connect/auth
    ├── imap_bulk.py             # Bulk IMAP ops
    ├── attachments.py           # doc-extractor engine client for read_attachment (source="mail_attachment")
    ├── helpers.py, token_refresh.py, text_utils.py  # shared provider utilities
    └── ...
```

---

## Environment Variables

| Variable | Description |
|----------|-------------|
| `GMAIL_CLIENT_ID` | Google OAuth2 client ID |
| `GMAIL_CLIENT_SECRET` | Google OAuth2 client secret |
| `GMAIL_REDIRECT_URI` | Google OAuth callback URL |
| `MICROSOFT_CLIENT_ID` | Microsoft Azure app client ID |
| `MICROSOFT_CLIENT_SECRET` | Microsoft Azure app client secret |
| `MICROSOFT_REDIRECT_URI` | Microsoft OAuth callback URL |
| `YAHOO_CLIENT_ID` | Yahoo OAuth2 client ID (pending approval) |
| `YAHOO_CLIENT_SECRET` | Yahoo OAuth2 client secret |

IMAP passwords and OAuth tokens are stored via the platform's EXT-SECRETS-V1
(`ctx.secrets`, HashiCorp Vault transit engine) — no manual encryption key to
configure; this replaces an older Fernet-based `IMAP_ENCRYPTION_KEY` scheme
that is no longer used by this extension.

`read_attachment` uses the shared doc-extractor engine already deployed for
File Reader (`https://api.webhostmost.com/doc-extractor`) — no separate
credential needed; it authenticates the same way File Reader's own engine
client does.

---

## Tests

```
.venv/bin/python3 -m pytest tests/ -v
```

27 tests covering the doc-extractor engine client (ingest/read/overview/retry/poll),
all three providers' `download_attachment` (Gmail base64url decode, Microsoft Graph
base64 decode + non-file-attachment rejection, IMAP MIME-part walk), and the
`impl_read_attachment` orchestration (happy path, unknown attachment id, still-processing,
unsupported/failed extraction). No live credentials required — `ctx.http` is mocked.

---

## Built with

- [imperal-sdk](https://github.com/imperalcloud/imperal-sdk) 5.9.11
- [Imperal Cloud](https://panel.imperal.io)
