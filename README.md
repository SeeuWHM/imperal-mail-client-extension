# imperal-mail-client-extension

[![Imperal SDK](https://img.shields.io/badge/imperal--sdk-1.5.0-blue)](https://pypi.org/project/imperal-sdk/)
[![Version](https://img.shields.io/badge/version-4.3.0-green)](https://github.com/SeeuWHM/imperal-mail-client-extension/releases)
[![License](https://img.shields.io/badge/license-LGPL--2.1-orange)](LICENSE)
[![Platform](https://img.shields.io/badge/platform-Imperal%20Cloud-purple)](https://panel.imperal.io)

**Enterprise AI email client extension for [Imperal Cloud](https://panel.imperal.io).**

Connect Google, Microsoft Outlook, Yahoo, AOL, iCloud, or any IMAP/SMTP server. Manage email through natural language or the panel UI — read, send, reply, archive, search, bulk operations.

---

## What It Does

Talk to it naturally:

```
"show my inbox"
"read the latest email from John"
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

### Chat Functions (36)

**Account management:** `connect`, `connect_microsoft`, `connect_yahoo`, `connect_imap`, `disconnect`, `status`, `switch_account`

**Read:** `inbox`, `read_email`, `search`, `folder`, `get_thread`

**Write:** `send`, `reply`, `forward`

**Manage:** `archive`, `delete`, `mark_read`, `mark_unread`, `star`, `move`, `purge`

**Bulk:** `bulk_archive`, `bulk_delete`, `bulk_mark_read`, `bulk_mark_unread`

**Contacts:** `contacts`, `add_contact`, `sync_contacts`, `delete_contact`

**Panel:** `mail_action`, `folder_counts`, `get_oauth_url`, `add_imap`, `compose_send`

### Panel (5 `@ext.panel` handlers)

| Panel | Slot | Purpose |
|-------|------|---------|
| `inbox` | left | Email list with infinite scroll, bulk select, folder selector |
| `email_viewer` | center | Full email with HTML rendering, attachments, action bar |
| `accounts` | right | Connected accounts list with active indicator |
| `compose` | center | Reply / forward / new email form with file upload |
| `add_account` | right | 3-step wizard: OAuth / password / advanced IMAP settings |

---

## File Structure

```
imperal-mail-client-extension/
├── main.py                   # Entry point — sys.modules cleanup
├── app.py                    # Extension + ChatExtension + health check
├── handlers_connect.py       # connect/disconnect/status/switch handlers
├── handlers_inbox.py         # inbox/read/search/folder/send/reply/forward
├── handlers_manage.py        # archive/delete/star/move/purge/bulk ops
├── handlers_contacts.py      # contacts CRUD + sync
├── handlers_panel_actions.py # mail_action/folder_counts/get_oauth_url/add_imap
├── handlers_panel_compose.py # compose_send
├── skeleton.py               # skeleton_refresh_mail (inbox cache, alerts)
├── panels.py                 # @ext.panel: inbox + email_viewer + accounts + compose + add_account
├── panels_email_viewer.py    # Email viewer builder (HTML + attachments)
├── panels_accounts.py        # Accounts panel builder
├── panels_add_account.py     # Add account wizard builder
├── panels_compose.py         # Compose panel builder
├── system_prompt.txt         # LLM routing instructions
├── imperal.json              # Extension manifest
└── providers/
    ├── __init__.py           # Provider factory (get_provider)
    ├── base.py               # BaseMailProvider abstract interface
    ├── google.py             # Gmail REST API implementation
    ├── microsoft.py          # Microsoft Graph API implementation
    ├── imap.py               # IMAP/SMTP implementation (password + XOAUTH2)
    ├── imap_connection.py    # IMAP/SMTP connect + auth helpers
    ├── imap_read.py          # IMAP read: inbox, fetch_page, unread_count, read, search
    ├── imap_write.py         # IMAP write: send, move, flag, purge, save_to_sent
    ├── helpers.py            # Constants, account helpers, IMAP detection, cursor codec
    ├── cache.py              # Redis inbox page cache + skeleton context cache
    ├── token_refresh.py      # OAuth token refresh + HTTP wrappers (Google/MS/Yahoo)
    └── text_utils.py         # Header decode, body extract, MIME builder, Fernet crypto
```

---

## Store Collections

| Collection | Contents |
|------------|----------|
| `gmail_accounts` | Connected accounts — OAuth tokens, IMAP credentials (Fernet-encrypted passwords) |
| `mail_contacts` | Email contacts — name, email, source, last_seen |
| `mail_last_read` | Last read message metadata — for reply continuity |

> **Note:** Collection is named `gmail_accounts` for legacy backwards compatibility. It stores all provider types (Google, Microsoft, IMAP, Yahoo).

---

## Skeleton

`skeleton_refresh_mail` runs every ~60s and caches inbox for all connected accounts:

```
Redis key: imperal:skeleton:gmail:{userId}:inbox_cache
```

```python
{
    "user@gmail.com": {
        "messages": [{id, subject, from, date, unread, thread_id, message_id_header}],
        "unread_count": 5,
        "last_fetched": 1713000000
    }
}
```

Redis inbox page cache (120s TTL) shared across Temporal workers:
`mail:inbox:{email}:{folder}:{cursor_hash}`

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
| `IMAP_ENCRYPTION_KEY` | Fernet key for IMAP password encryption |
| `REDIS_URL` | Redis URL for inbox page cache |

---

## Built with

- [imperal-sdk](https://github.com/imperalcloud/imperal-sdk) 1.5.0
- [Imperal Cloud](https://panel.imperal.io)
