# imperal-mail-client-extension

[![Imperal SDK](https://img.shields.io/badge/imperal--sdk-5.9.9-blue)](https://pypi.org/project/imperal-sdk/)
[![Version](https://img.shields.io/badge/version-5.7.0-green)](https://github.com/SeeuWHM/imperal-mail-client-extension/releases)
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

### Tools (54 total: 52 @chat.function + 2 skeleton)

**Account management (7):** `connect`, `connect_microsoft`, `connect_yahoo`, `connect_imap`, `status`, `switch_account`, `disconnect`

**Read (8):** `inbox`, `read_email`, `search`, `folder`, `get_thread`

**Write (within Read group):** `send`, `reply`, `forward`

**Manage (14):** `archive`, `delete`, `mark_read`, `mark_unread`, `star`, `move`, `purge`, `bulk_archive`, `bulk_delete`, `bulk_mark_read`, `bulk_mark_unread`, `bulk_move`, `bulk_star`, `bulk_purge`

**Smart filters & folder prefs (8):** `create_filter`, `list_filters`, `apply_filter`, `update_filter`, `delete_filter`, `set_folder_prefs`, `get_folder_prefs`, `list_mail_folders`

**Automation rules (6):** `create_forward_rule`, `create_autoreply`, `list_rules`, `toggle_rule`, `delete_rule`, `trigger_rules_now`

**Contacts (4):** `contacts`, `add_contact`, `sync_contacts`, `delete_contact`

**Panel (5):** `mail_action`, `folder_counts`, `get_oauth_url`, `add_imap`, `compose_send`

**Skeleton (2):** `skeleton_refresh_mail_inbox_summary`, `skeleton_alert_mail_inbox_summary`

> Bulk ops need the message_ids loaded first (via `inbox`/`folder`/`search`) and `account=`
> matching the mailbox those ids came from.

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

## Architecture (v5.7.0 / SDK 5.x — 50 files)

```
imperal-mail-client-extension/
├── main.py                   # Entry point — sys.modules cleanup + imports
├── app.py                    # Extension instance (SDK v5.0.0) + ChatExtension + lifecycle
├── schemas.py                # Pydantic response schemas + re-export of schemas_params
├── schemas_params.py         # Pydantic input param models for @chat.function handlers
├── schemas_sdl.py            # 22 SDL entity classes (mail.* roles)
├── schemas_sdl_builders.py   # impl_result → SDL entity builders
├── schemas_sdl_rules.py      # SDL entities for filters / rules / prefs
├── schemas_sdl_builders_rules.py # builders for filter/rule/prefs SDL entities
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
├── handlers_filters.py       # create/list/apply/update/delete_filter + set/get_folder_prefs + list_mail_folders
├── handlers_rules.py         # create_forward_rule / create_autoreply / list/toggle/delete_rule / trigger_rules_now
├── handlers_rule_runner.py   # @ext.schedule rule runner (backup) + match/forward/autoreply helpers
├── handlers_rule_event.py    # process_event_email — primary real-time rule path (from on_email_received)
├── handlers_ui.py            # Inline chat UI builders: _inbox_ui / _email_ui / _search_ui
├── panels.py                 # @ext.panel registrations + inbox_panel handler
├── panels_filters_bar.py     # Smart-filters bar (per active account)
├── panels_filter_view.py     # render_filter_panel — filter results + client-side pagination
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
| `gmail_accounts` | Connected accounts — OAuth tokens, IMAP credentials (Fernet-encrypted passwords), `unread_count`, `last_message_ids`, `last_fetched`, `is_active` |
| `mail_contacts` | Email contacts — name, email, source, last_seen |
| `mail_last_read` | Last read message metadata — message_id, subject, sender, thread_id, **account** (for reply account restoration) |
| `mail_filters` | Smart filter definitions incl. `account_email`, criteria_from / from_emails / criteria_subject |
| `mail_rules` | Forward + auto-reply rules (criteria, forward_to / reply_template, schedule, last_run_at) |
| `mail_autoreply_sent` | Auto-reply dedup — message_id + rule_id (no double replies) |
| `mail_prefs` | Folder visibility preferences (visible_folders / hidden_folders) |

> **Note:** Collection is named `gmail_accounts` for legacy backwards compatibility. It stores all provider types (Google, Microsoft, IMAP, Yahoo).

---

## Skeleton

`skeleton_refresh_mail_inbox_summary` (TTL=60, alert=True) returns a **raw dict** —
no Pydantic in the response path — as a 5-field classifier envelope of **read-query
counts** (docs recipe [`recipes/skeleton-data-surface`](https://docs.imperal.io/en/recipes/skeleton-data-surface/) —
counts + per-item array ≤5). The brain answers "сколько всего / непрочитано / спам /
архив / сегодня" **directly from these counts**, with no search (so no search-count cap):

```json
{
  "response": {
    "active_account": "ignatstremb@gmail.com",
    "unread_total": 7012,
    "today_total": 24,
    "total_all": 25113,
    "per_account": [
      {"email": "ignatstremb@gmail.com", "total": 23000, "unread": 6900, "spam": 410, "archive": 0},
      {"email": "webhostmost@outlook.com", "total": 2100, "unread": 9,    "spam": 12,  "archive": 80}
    ]
  }
}
```

Counts come from `provider.get_counts → {total, inbox_total, unread, spam, archive}` and
`provider.get_today_count`, **normalized across all providers**:

| Count | Google | Microsoft | IMAP / Yahoo |
|---|---|---|---|
| `total` (whole mailbox) | `users.getProfile.messagesTotal` | `/me/messages $count` (ConsistencyLevel: eventual) | INBOX total (best-effort) |
| `unread` | INBOX label `messagesUnread` | mailFolders/inbox `unreadItemCount` | STATUS UNSEEN |
| `spam` | SPAM label total | JunkEmail folder total | Junk/Spam folder STATUS |
| `archive` | **0** (Gmail has no Archive folder) | Archive folder total | Archive folder STATUS |
| `today` | `after:YYYY/MM/DD` (id-pagination) | `$filter receivedDateTime ge` + `$count` | SEARCH SINCE |

`per_account` is the per-mailbox card; top-level fields are the across-all-accounts
aggregates. Dropped vs. older envelopes: `recent_emails` (low signal at scale),
`accounts_connected` (= `len(per_account)`), per-account `is_active` (= `active_account`),
`filter_count`/`rule_count` (detail-on-demand via `list_filters`/`list_rules`).

Each run also: fetches folder stats + page 1 per account, diffs against `last_message_ids`
→ `ctx.notify()` on new mail, and warms `ctx.cache` with 25 messages for instant panel load.

`skeleton_alert_mail_inbox_summary(old, new)` returns `{"response": "<n> new unread email(s)"}`
when `unread_total` rises — for kernel badge/push gating.

Panel inbox rendering reads `ctx.cache` (`InboxMessages` model), not the skeleton.

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

- [imperal-sdk](https://github.com/imperalcloud/imperal-sdk) 5.9.9
- [Imperal Cloud](https://panel.imperal.io)
