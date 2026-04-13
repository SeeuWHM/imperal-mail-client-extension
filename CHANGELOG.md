# Changelog

## [4.3.0] — 2026-04-14

### Added
- 5 `@ext.panel` handlers replacing legacy React UI: inbox (left), email_viewer (center), accounts (right), compose (center), add_account (right)
- Infinite scroll pagination with cursor-based `fetch_page()` for all providers
- Multi-select + bulk actions in inbox panel (archive/delete/mark)
- HTML email rendering via `ui.Html(theme="light")` in email viewer
- Attachment download via `ui.Open(url)` proxy buttons
- 3-step add-account wizard panel (providers → password → advanced)
- `invalidate_inbox()` Redis cache invalidation on panel actions
- `compose_send` handler for reply/forward/new from compose panel
- `get_oauth_url`, `folder_counts`, `mail_action`, `add_imap` direct panel functions

### Changed
- `fetch_page()` added to all providers (Google: pageToken, Microsoft: $skip, IMAP: UID-range)
- `get_unread_count()` added to all providers
- IMAP read operations split into `imap_read.py`, write into `imap_write.py`
- Redis inbox page cache (120s TTL) shared across Temporal workers

## [4.2.0] — 2026-04-11

### Added
- Mail v4 DUI panels (SDK v1.5.0)
- IMAP direct fallback on skeleton cache miss
- Fernet encryption for IMAP passwords
- Microsoft Graph `$delta` poller in kernel event_poller
- IMAP fast count poller (60s)
- `connect_yahoo` handler (OAuth pending Yahoo approval)

### Changed  
- app_id `"mail"` everywhere (old `"gmail"` suspended in Registry)
- Store collection still `gmail_accounts` (legacy name preserved)
- Scopes migrated: `gmail:*` → `mail:*`
