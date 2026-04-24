# imperal-mail-client-extension

[![Imperal SDK](https://img.shields.io/badge/imperal--sdk-2.0.0-blue)](https://pypi.org/project/imperal-sdk/)
[![Version](https://img.shields.io/badge/version-5.0.0-green)](https://github.com/SeeuWHM/imperal-mail-client-extension/releases)
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

### Tools (35)

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
| `inbox` | left | Email list with infinite scroll, bulk select, folder tabs |
| `email_viewer` | center | Full email with HTML rendering, attachments, action bar |
| `accounts` | right | Connected accounts list with active indicator |
| `compose` | center | Reply / forward / new email form |
| `add_account` | right | 3-step wizard: OAuth / password / advanced IMAP settings |

---

## Architecture (v5.0.0 / SDK v2.0.0)

```
imperal-mail-client-extension/
├── main.py                   # Entry point — sys.modules cleanup + imports
├── app.py                    # MailExtension instance (v2 Extension) + lifecycle
├── tools.py                  # Tool class with @sdk_ext.tool methods (35 tools)
├── schemas.py                # Pydantic output schemas for all tools
├── ctx_helpers.py            # _user_id / _get_acc (shared by handlers + panels)
├── cache_model_defs.py       # Pure Pydantic cache models (InboxPage, UnreadSummary)
├── cache_models.py           # ctx.cache model registrations
├── skeleton.py               # Skeleton: inbox summary + alert (LLM-Only, SDK v1.6.0)
├── handlers_connect.py       # impl_connect / impl_status / impl_switch / impl_disconnect
├── handlers_inbox.py         # impl_inbox / impl_read_email / impl_search / impl_send / impl_reply
├── handlers_manage.py        # impl_archive / impl_delete / impl_star / impl_move / impl_bulk_*
├── handlers_contacts.py      # impl_contacts / impl_add_contact / impl_sync / impl_delete_contact
├── handlers_panel_actions.py # impl_mail_action / impl_folder_counts / impl_get_oauth_url / impl_add_imap
├── handlers_panel_compose.py # impl_compose_send
├── panels.py                 # @ext.panel: inbox + email_viewer + accounts + compose + add_account
├── panels_email_viewer.py    # Email viewer builder (HTML + attachments)
├── panels_accounts.py        # Accounts panel builder
├── panels_add_account.py     # Add account wizard builder
├── panels_compose.py         # Compose panel builder
├── imperal.json              # Extension manifest (v5.0.0, sdk_version 2.0.0)
└── providers/
    ├── __init__.py           # Provider factory (get_provider)
    ├── base.py               # BaseMailProvider abstract interface
    ├── google.py             # Gmail REST API (class skeleton + normalizer)
    ├── google_read.py        # Gmail read: inbox, fetch_page, unread_count, read, search
    ├── google_write.py       # Gmail write: send, reply, forward, archive, delete, mark, star, move, purge
    ├── microsoft.py          # Microsoft Graph API implementation
    ├── imap.py               # IMAP/SMTP provider (password + XOAUTH2)
    ├── imap_connection.py    # IMAP/SMTP connect + auth helpers
    ├── imap_read.py          # IMAP read: inbox, fetch_page, unread_count, read, search, folder
    ├── imap_write.py         # IMAP write: send, move, flag, purge, save_to_sent
    ├── helpers.py            # Constants, account helpers, IMAP detection, ctx.cache key helpers
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

## Skeleton (SDK v1.6.0)

`skeleton_refresh_mail_inbox_summary` runs every 60s and returns a compact scalar envelope per I-SKELETON-LLM-ONLY:

```json
{
  "accounts_connected": 2,
  "unread_total": 7,
  "per_account": [
    {"email": "user@gmail.com", "unread_count": 5, "message_count": 20},
    {"email": "work@outlook.com", "unread_count": 2, "message_count": 15}
  ]
}
```

Panel inbox rendering uses `ctx.cache` (InboxPage / UnreadSummary models), not the skeleton.

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

---

## Built with

- [imperal-sdk](https://github.com/imperalcloud/imperal-sdk) 2.0.0
- [Imperal Cloud](https://panel.imperal.io)
