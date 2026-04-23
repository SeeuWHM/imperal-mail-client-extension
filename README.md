# imperal-mail-client-extension

[![Imperal SDK](https://img.shields.io/badge/imperal--sdk-1.5.0-blue)](https://pypi.org/project/imperal-sdk/)
[![Version](https://img.shields.io/badge/version-4.3.6-green)](https://github.com/SeeuWHM/imperal-mail-client-extension/releases)
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
"show my starred emails"
```

Or use the panel — click emails to open them, archive/delete with one click, multi-select for bulk actions, switch folders with tab buttons.

---

## Providers

| Provider | Auth | API |
|----------|------|-----|
| Google Gmail | OAuth2 | Gmail REST API |
| Microsoft Outlook / O365 | OAuth2 | Microsoft Graph API |
| Yahoo / AOL | App Password (full OAuth pending approval) | IMAP + SMTP |
| iCloud / me.com | App-Specific Password | IMAP + SMTP |
| Any IMAP server | Password (Fernet-encrypted) | IMAP + SMTP |

**IMAP auto-detect:** 19 domains pre-mapped (Gmail, Outlook, Yahoo, iCloud, Zoho, Yandex, Mail.ru, webhostmost.com, etc.)

---

## Capabilities

### Chat Functions (35)

**Account management (7):** `connect` `connect_microsoft` `connect_yahoo` `connect_imap` `disconnect` `status` `switch_account`

**Read (5):** `inbox` `read_email` `search` `folder` `get_thread`

**Write (3):** `send` `reply` `forward`

**Manage (7):** `archive` `delete` `mark_read` `mark_unread` `star` `move` `purge`

**Bulk (4):** `bulk_archive` `bulk_delete` `bulk_mark_read` `bulk_mark_unread`

**Contacts (4):** `contacts` `add_contact` `sync_contacts` `delete_contact`

**Panel direct (5):** `mail_action` `folder_counts` `get_oauth_url` `add_imap` `compose_send`

### Panel (5 `@ext.panel` handlers)

| Panel | Slot | Purpose |
|-------|------|---------|
| `inbox` | left | Email list with folder tab buttons, bulk select, account indicator |
| `email_viewer` | center | Full email with HTML rendering, attachment metadata, action bar |
| `accounts` | right | Connected accounts list — click to switch active account |
| `compose` | center | Reply / forward / new email form |
| `add_account` | right | 3-step wizard: OAuth buttons / password / advanced IMAP settings |

---

## File Structure

```
imperal-mail-client-extension/
├── main.py                   # Entry point — sys.modules cleanup + import order
├── app.py                    # Extension + ChatExtension (Haiku) + health check
├── handlers_connect.py       # connect / disconnect / status / switch_account
├── handlers_inbox.py         # inbox / read_email / search / folder / get_thread
│                             # send / reply / forward
├── handlers_manage.py        # archive / delete / mark_read / mark_unread / star
│                             # move / purge / bulk_* operations
├── handlers_contacts.py      # contacts CRUD + Google People / Graph sync
├── handlers_panel_actions.py # mail_action / folder_counts / get_oauth_url / add_imap
├── handlers_panel_compose.py # compose_send (reply/forward/new from compose panel)
├── skeleton.py               # skeleton_refresh_mail + skeleton_alert_mail + legacy aliases
├── panels.py                 # @ext.panel: inbox + email_viewer + accounts + compose + add_account
│                             # _execute_panel_action / _switch_active_account / _build_folder_tabs
├── panels_email_viewer.py    # Email viewer builder (HTML render, attachment metadata)
├── panels_accounts.py        # Accounts panel builder (click → do_switch_account)
├── panels_add_account.py     # Add account wizard builder (providers → password → advanced)
├── panels_compose.py         # Compose panel builder (reply/forward/new)
├── system_prompt.txt         # LLM routing instructions (module-description style)
├── imperal.json              # Extension manifest
└── providers/
    ├── __init__.py           # get_provider(acc) factory — fresh instance per call
    ├── base.py               # BaseMailProvider ABC — 15 abstract methods
    ├── google.py             # GoogleMailProvider class skeleton + _normalize_msg()
    ├── google_read.py        # GoogleReadMixin — fetch_inbox/page/unread/read/search/folder/thread
    ├── google_write.py       # GoogleWriteMixin — send/reply/forward/archive/delete/mark/star/move/purge
    ├── microsoft.py          # MicrosoftMailProvider — Graph API (all methods, starred/unread filters)
    ├── imap.py               # ImapMailProvider — IMAP/SMTP + Yahoo XOAUTH2 dispatcher
    ├── imap_connection.py    # _imap_connect_auth / _sync_imap_test / _sync_smtp_test
    ├── imap_read.py          # _sync_imap_inbox / _sync_imap_fetch_page (seq# opt for 16k+)
    │                         # _sync_imap_unread_count / _sync_imap_read (multi-folder)
    ├── imap_write.py         # _sync_smtp_send / _sync_smtp_xoauth2_send / _sync_imap_move
    │                         # _sync_imap_flag_op / _sync_imap_purge / _save_to_imap_sent
    │                         # _sync_imap_search / _sync_imap_folder
    ├── helpers.py            # Constants, _all_accounts, _active_account
    │                         # _detect_imap_settings, encode/decode_cursor, re-exports
    ├── cache.py              # Redis inbox page cache (30s TTL, tenant+user scoped)
    │                         # _remove_from_cache / _update_read_in_cache / _save_last_read
    ├── token_refresh.py      # _api_get/post, _graph_get/post/patch, _refresh_*_token
    └── text_utils.py         # Fernet crypto, MIME/header decode, HTML strip, _build_message
```

---

## Store Collections

| Collection | Contents |
|------------|----------|
| `gmail_accounts` | Connected accounts: email, provider, OAuth tokens, IMAP creds, is_active |
| `mail_contacts` | Contacts: name, email, source (google/outlook/extracted/manual), last_seen |
| `mail_last_read` id=`latest` | Last-read watermark: message_id, subject, sender, **user_id** |

> **`gmail_accounts` is a legacy name** preserved for backwards compatibility with existing stored data. It holds all provider types: Google, Microsoft, IMAP, Yahoo.

---

## Skeleton

`skeleton_refresh_mail` runs every ~60s (platform TTL) and caches inbox for ALL connected accounts into the AI context skeleton:

```
Skeleton key: imperal:skeleton:mail:{userId}:inbox_cache
```

```python
{
    "user@gmail.com": {
        "messages": [{"id": "...", "subject": "...", "from": "...", "date": "...", "unread": True}],
        "unread_count": 5,
        "last_fetched": 1745000000
    },
    "user@outlook.com": { ... }
}
```

**Redis inbox page cache** (30s TTL, per-user scoped) — used by the panel, separate from skeleton:

```
mail:inbox:{tenant_id}:{user_id}:{email}:{folder}:{cursor_hash}
```

---

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `GMAIL_CLIENT_ID` | OAuth2 | Google OAuth2 client ID |
| `GMAIL_CLIENT_SECRET` | OAuth2 | Google OAuth2 client secret |
| `GMAIL_REDIRECT_URI` | OAuth2 | Google callback: `https://auth.imperal.io/v1/oauth/gmail/callback` |
| `MICROSOFT_CLIENT_ID` | OAuth2 | Microsoft Azure app client ID |
| `MICROSOFT_CLIENT_SECRET` | OAuth2 | Microsoft Azure app client secret |
| `MICROSOFT_REDIRECT_URI` | OAuth2 | Microsoft callback: `https://auth.imperal.io/v1/oauth/microsoft/callback` |
| `YAHOO_CLIENT_ID` | OAuth2 | Yahoo OAuth2 client ID (pending Yahoo approval) |
| `YAHOO_CLIENT_SECRET` | OAuth2 | Yahoo OAuth2 client secret |
| `IMAP_ENCRYPTION_KEY` | IMAP | Fernet key for IMAP password encryption at rest |
| `REDIS_URL` | Cache | Redis URL for inbox page cache (30s TTL, tenant+user scoped) |

---

## Known Limitations

- **Attachments:** metadata shown (filename, size); download not yet possible (platform SDK gap)
- **Yahoo OAuth:** App Password only; full OAuth waiting for Yahoo developer approval
- **IMAP thread view:** not implemented (IMAP has no native thread concept)
- **IMAP search:** searches INBOX only; multi-folder search would require multiple IMAP connections
- **Bulk action panel refresh:** may lag after bulk archive/delete (events not published from FastRPC path)

---

## Built with

- [imperal-sdk](https://github.com/imperalcloud/imperal-sdk) 1.5.0
- [Imperal Cloud](https://panel.imperal.io)
