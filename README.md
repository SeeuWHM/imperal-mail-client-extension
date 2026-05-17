# imperal-mail-client-extension

[![Imperal SDK](https://img.shields.io/badge/imperal--sdk-5.0.0-blue)](https://pypi.org/project/imperal-sdk/)
[![Version](https://img.shields.io/badge/version-5.3.5-green)](https://github.com/SeeuWHM/imperal-mail-client-extension/releases)
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

### Tools (37 total: 35 @chat.function + 2 skeleton)

**Account management:** `connect`, `connect_microsoft`, `connect_yahoo`, `connect_imap`, `disconnect`, `status`, `switch_account`

**Read:** `inbox`, `read_email`, `search`, `folder`, `get_thread`

**Write:** `send`, `reply`, `forward`

**Manage:** `archive`, `delete`, `mark_read`, `mark_unread`, `star`, `move`, `purge`

**Bulk:** `bulk_archive`, `bulk_delete`, `bulk_mark_read`, `bulk_mark_unread`

**Contacts:** `contacts`, `add_contact`, `sync_contacts`, `delete_contact`

**Panel:** `mail_action`, `folder_counts`, `get_oauth_url`, `add_imap`, `compose_send`

**Skeleton:** `skeleton_refresh_mail_inbox_summary`, `skeleton_alert_mail_inbox_summary`

### Panel (5 `@ext.panel` handlers + 1 SDK-auto `secrets`)

| Panel | Slot | Purpose |
|-------|------|---------|
| `inbox` | left (permanent) | Email list with infinite scroll, bulk select, folder tabs |
| `email_viewer` | overlay (center_overlay=True) | Full email with HTML rendering, attachments, action bar |
| `accounts` | right (permanent) | Connected accounts list with active indicator |
| `compose` | overlay (center_overlay=True) | Reply / forward / new email form |
| `add_account` | overlay (center_overlay=True) | 3-step wizard: OAuth / password / advanced IMAP settings |
| `secrets` | overlay | SDK auto-registered; moved from right → overlay |

---

## Architecture (v5.3.5 / SDK v5.0.0)

```
imperal-mail-client-extension/
├── main.py                   # Entry point — sys.modules cleanup + imports
├── app.py                    # Extension instance (SDK v5.0.0) + ChatExtension + lifecycle
├── schemas.py                # Pydantic response schemas for all tools
├── schemas_params.py         # Pydantic input param models for @chat.function handlers
├── ctx_helpers.py            # _user_id / _get_acc / _oauth_state (break import cycle)
├── cache_model_defs.py       # Pure Pydantic cache models (InboxMessages, UnreadSummary, AccountList)
├── cache_models.py           # ctx.cache model registrations
├── skeleton.py               # @ext.skeleton: inbox summary (TTL 60s, alert=True) + alert tool
├── handlers_connect.py       # connect / connect_microsoft / connect_yahoo / connect_imap
│                             # status / switch_account / disconnect
├── handlers_inbox.py         # inbox / read_email / search / folder / get_thread
│                             # send / reply / forward
├── handlers_manage.py        # archive / delete / mark_read / mark_unread / star
│                             # move / purge / bulk_archive / bulk_delete / bulk_mark_*
├── handlers_contacts.py      # contacts / add_contact / sync_contacts / delete_contact
├── handlers_panel_actions.py # mail_action / folder_counts / get_oauth_url / add_imap
├── handlers_panel_compose.py # compose_send
├── handlers_ui.py            # Inline chat UI builders: _inbox_ui / _email_ui / _search_ui
├── panels.py                 # @ext.panel registrations + inbox_panel handler
├── panels_inbox.py           # FOLDERS / _execute_panel_action / _build_folder_tabs / _build_email_list
├── panels_email_viewer.py    # build_email_viewer() — HTML sandbox, prev/next nav, action bar
├── panels_accounts.py        # build_accounts_panel()
├── panels_add_account.py     # build_add_account_panel() — 3-step wizard
├── panels_compose.py         # build_compose_panel() — reply/forward/new + TagInput autocomplete
├── panels_schedule.py        # Retired schedule stub (inbox_warmup removed)
├── imperal.json              # Extension manifest (schema v3, sdk_version 5.0.0)
└── providers/
    ├── __init__.py           # Provider factory (get_provider)
    ├── base.py               # BaseMailProvider abstract interface (16 methods)
    ├── google.py             # Gmail: class skeleton + normalizer
    ├── google_read.py        # Gmail read: inbox, fetch_page, stats, read_email, search
    ├── google_write.py       # Gmail write: send, reply, forward, archive, delete, mark, star, move, purge
    ├── microsoft.py          # Microsoft Graph API: read + write
    ├── microsoft_write.py    # Microsoft write helpers
    ├── imap.py               # IMAP/SMTP provider (password + XOAUTH2)
    ├── imap_connection.py    # IMAP/SMTP connect + auth helpers
    ├── imap_read.py          # IMAP read: inbox, fetch_page, stats, search, folder
    ├── imap_read_message.py  # IMAP single-message fetch + \Seen flag
    ├── imap_write.py         # IMAP write: send, move, flag, purge, save_to_sent
    ├── helpers.py            # Constants, account helpers, IMAP detection, cache key helpers
    ├── token_refresh.py      # OAuth token refresh + HTTP wrappers (Google/MS/Yahoo)
    └── text_utils.py         # Header decode, body extract, MIME builder, Fernet crypto
```

---

## Store Collections

| Collection | Contents |
|------------|----------|
| `gmail_accounts` | Connected accounts — OAuth tokens, IMAP credentials (Fernet-encrypted passwords), `unread_count`, `last_message_ids`, `last_fetched` |
| `mail_contacts` | Email contacts — name, email, source, last_seen |
| `mail_last_read` | Last read message metadata — message_id, subject, sender, thread_id, **account** (for reply account restoration) |

> **Note:** Collection is named `gmail_accounts` for legacy backwards compatibility. It stores all provider types (Google, Microsoft, IMAP, Yahoo).

---

## Skeleton (SDK v5.0.0)

`skeleton_refresh_mail_inbox_summary` runs every 60s (TTL=60, alert=True):

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

`skeleton_alert_mail_inbox_summary` is a lightweight check — reads last-known `unread_count` from store (no API calls) and returns `{unread_total, per_account}` for kernel badge display and push-notification gating.

Panel inbox rendering uses `ctx.cache` (`InboxMessages` model, TTL=90s), not the skeleton.

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

- [imperal-sdk](https://github.com/imperalcloud/imperal-sdk) 5.0.0
- [Imperal Cloud](https://panel.imperal.io)
