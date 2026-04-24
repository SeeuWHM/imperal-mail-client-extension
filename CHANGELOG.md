# Changelog

## [5.0.0] — 2026-04-25

### Breaking — SDK v2.0.0 (Webbee Single Voice)

- Base class switched from `ChatExtension` to `Extension`. Tool class lives in `tools.py`; instance + lifecycle in `app.py`
- Every tool carries `@sdk_ext.tool(output_schema=<PydanticModel>)` — Webbee Narrator grounds user-facing prose kernel-side
- `system_prompt.txt` deleted — narration is now fully kernel-side via Pydantic schemas
- `schemas.py` added — 20 Pydantic output models covering all 35 tools
- `tools.py` added — `MailExtension(Extension)` class with all tool methods as thin delegators to `handlers_*.py`
- `ctx_helpers.py` added — `_user_id` / `_get_acc` moved out of `app.py` to break import cycle

### Changed

- All `handlers_*.py` functions renamed `fn_*` → `impl_*` and return Pydantic models instead of `ActionResult`
- `cache_models.py` split: model classes → `cache_model_defs.py`, registration stays in `cache_models.py` (breaks `app → tools → handlers → app` cycle)
- `panels.py` / all panel builders updated to use `ctx_helpers._get_acc` instead of `app._get_acc`
- `providers/helpers.py`: `SKELETON_INBOX` removed, new ctx.cache key helpers added (`_inbox_page_key`, `_unread_summary_key`, `_invalidate_first_page`, etc.)
- `providers/cache.py` deleted — replaced by ctx.cache + `cache_model_defs.py`
- `imperal.json` updated to v5.0.0 / sdk_version 2.0.0 with full tool schema (35 tools with `output_schema_ref`)

---

## [4.4.x] — 2026-04-24 (SDK v1.6.0 migration + hotfixes)

### feat: migrate to SDK v1.6.0 (I-SKELETON-LLM-ONLY, ctx.cache)

- Skeleton tools renamed: `skeleton_refresh_mail` → `skeleton_refresh_mail_inbox_summary`, `skeleton_alert_mail` → `skeleton_alert_mail_inbox_summary`
- Skeleton now returns scalar envelope only (no message blobs) per I-SKELETON-LLM-ONLY
- Inbox page caching migrated from Redis → `ctx.cache` (`InboxPage` / `UnreadSummary` models)
- `@ext.skeleton(...)` decorator used for skeleton tools (replaces raw `@ext.tool`)
- Legacy Redis `SKELETON_INBOX` key and `providers/cache.py` replaced by ctx.cache helpers

### hotfix: tolerate unknown UI kwargs in inbox_panel

- `inbox_panel` accepts `**_unused_kwargs` to tolerate `active_message_id` and other future params without 500ing

### fix: Document dataclass compat for ctx.store.query results

- `handlers_connect.py` / `handlers_panel_actions.py`: `d.data` / `d.id` used consistently for store Document objects (resolves `d["doc_id"]` / `d.items()` errors on store query results)

---

## [4.3.6] — 2026-04-24

### Fixed

- **`_switch_active_account` used wrong Document API** — `d.items()` and `d["doc_id"]` are not supported on Store `Document` objects (only `d.get()`/`d["field"]` for data; `d.id` for the ID). Errors were silently swallowed → `is_active` never updated in DB → after reload always reverted to original account. Rewrote using `_all_accounts(ctx)` which returns plain dicts with `doc_id` key
- **Microsoft Starred/Unread showed Inbox without filter** — `_MS_PAGE_FOLDERS` had no mapping for `"starred"` or `"unread"`. Added `$filter=flag/flagStatus eq 'flagged'` for starred and `$filter=isRead eq false` for unread in `MicrosoftMailProvider.fetch_page()`
- **Users icon button appeared to do nothing** — Calling `__panel__accounts` re-rendered the already-visible right panel. Removed; right panel shows accounts by default

### Performance

- **IMAP first-page fetch for 16k+ mailboxes** — Replaced `SEARCH ALL` (downloads all UIDs) with `imap.fetch(f"{count-limit}:{count}", "(UID FLAGS RFC822.HEADER)")` — sequence number range, server-side, no full-mailbox scan. Subsequent pages (cursor) still use SEARCH ALL

### Refactor

- `_sync_imap_search` and `_sync_imap_folder` moved from `imap_read.py` to `imap_write.py` (file size), re-exported for backwards compatibility

---

## [4.3.5] — 2026-04-24

### Fixed

- **Folder filtering not working** — `ui.Select(param_name="folder")` injection was unreliable. Replaced with `_build_folder_tabs()` — 6 explicit buttons, each with `folder=f["key"]` hardcoded in `ui.Call`
- **Account switching from right panel not updating left inbox** — `ui.Call("switch_account")` went through DirectCallWorkflow, no events, inbox never updated. Changed to `ui.Call("__panel__inbox", do_switch_account=email)` — inbox_panel updates `is_active` in store and re-renders immediately
- **Account Select in inbox didn't update DB** — Removed account Select from inbox left panel; switching is exclusively via the right Accounts panel

### Added

- `_switch_active_account(ctx, target_email)` — updates is_active in store using `_all_accounts()` pattern
- `_build_folder_tabs(folder, active_email)` — explicit button-based folder navigation
- `do_switch_account` param on `inbox_panel`

---

## [4.3.4] — 2026-04-24

### Fixed

- **Archive/Delete/Spam from email viewer didn't remove email from list** — Root cause: `ui.Call` goes through `DirectCallWorkflow` / Fast-RPC, NOT `SessionWorkflow`. Only `SessionWorkflow` publishes events (Step 10b). Events from `fn_mail_action` never reached the inbox panel
  Solution: `inbox_panel` accepts `do_action` + `do_message_id`. Archive/Spam/Delete buttons call `__panel__inbox` with these params. Panel executes action BEFORE fetching list

### Changed

- Redis cache TTL: 120s → 30s

---

## [4.3.3] — 2026-04-24

### Fixed

- **`"$value"` passed as literal string in Select on_change** — `account="$value"` / `folder="$value"` in `ui.Call` params were literal strings. Removed; `param_name` alone injects selected value
- **`reply_all` type mismatch** — Panel receives string from params but `build_compose_panel` expected bool. Added explicit conversion: `str(reply_all).lower() in ("true", "1", "yes")`
- Expanded refresh event list from 2 to 9 events

---

## [4.3.2] — 2026-04-23

### Fixed

- **Deploy validator FAIL: identity phrase in system_prompt.txt** — `"You are the Mail Client..."` conflicts with kernel L5 OS Identity. Rewritten as module-description: `"Mail Client module — inbox, search, ..."`
- **Deploy validator WARN: google.py was 391 lines** — Split into `google.py` (38L), `google_read.py` (215L), `google_write.py` (154L)

---

## [4.3.1] — 2026-04-23

Full enterprise bug audit — 25 confirmed bugs across 15 files.

### Security (Critical)

- **B1:** Redis cache key `mail:inbox:{email}:...` → `mail:inbox:{tenant_id}:{user_id}:{email}:...` (I-MAIL-INBOX-CACHE-SCOPED-1)
- **B2:** Gmail 404 cross-account fallback removed from `read_email()` + `reply()` (I-MAIL-NO-CROSS-ACCOUNT-FALLBACK-1)

### Fixed (High)

- **B3:** Cache removal functions were NOPs (read from non-existent store collection). Rewrote to call `invalidate_inbox(ctx, email)`
- **B4:** `doc_id` contamination in store updates — excluded from update payloads
- **B5:** `fn_reply` used `ctx.store.query()` instead of `ctx.store.get("mail_last_read", "latest")`
- **B6:** `asyncio.ensure_future` in Temporal activity replaced with `await _save_sent_async()`
- **B7:** `fn_disconnect` now calls `invalidate_inbox` after account deletion
- **F1:** OAuth wizard buttons now use `ui.Send(...)` instead of `ui.Call("get_oauth_url")` — LLM presents URL
- **F2:** Image proxy + attachment download buttons removed (endpoints don't exist on platform)
- **F8:** IMAP account connect race condition — create-then-deactivate order

### Fixed (Medium — Isolation)

- **B8:** `fn_reply` auth guard: `ctx.user.id != "__system__"` + watermark user_id verify
- **B9:** `_save_last_read` now stamps `user_id` in payload
- **B10:** Provider `_INSTANCES` singleton removed — fresh instance per call
- **B11:** `ctx._bulk_skip_cache` dead mutation removed from `_run_bulk`

### Fixed (Medium — UX)

- **B12:** IMAP read/flag now searches `_IMAP_READ_FOLDER_ORDER` (18 folders) instead of INBOX only
- **B13:** Inbox panel uses `provider.get_unread_count()` instead of counting current page
- **F3:** `total_items=0` (hides incorrect paginator)
- **F4:** Reply All only shown when `cc_field` is present (not `to_field`)
- **F5:** FileUpload removed from compose panel (no platform endpoint for binary files)
- **F6:** Redundant `mark_read` call removed from `build_email_viewer`
- **F7:** Back button passes `folder=folder` — returns to correct folder, not always INBOX

### Fixed (Low)

- **B14:** `_sync_imap_search/_folder` return type: `-> list[dict] | None`
- **B15:** Unused `_tenant_id` helper removed from `app.py`
- **B16:** SMTP sendmail unified to `msg_bytes` (was mixing `as_string()` / `as_bytes()`)
- **B17:** `reply_all` param changed to `bool = False` in `build_compose_panel`

---

## [4.3.0] — 2026-04-14

### Added

- 5 `@ext.panel` handlers: inbox (left), email_viewer (center), accounts (right), compose (center), add_account (right)
- Cursor-based `fetch_page()` for all providers (Google: pageToken, Microsoft: $skip, IMAP: UID range)
- `get_unread_count()` for all providers
- Multi-select + bulk actions in inbox panel
- HTML email rendering via `ui.Html(sandbox=True, theme="light")`
- 3-step add-account wizard panel
- `compose_send`, `get_oauth_url`, `folder_counts`, `mail_action`, `add_imap` direct panel functions
- `invalidate_inbox()` Redis cache invalidation on panel actions

### Changed

- IMAP operations split: `imap_read.py` (fetch/read), `imap_write.py` (send/move/flag/purge)
- Redis inbox page cache: 120s TTL (later reduced to 30s in v4.3.4)

### Note

v4.3.0 included attachment download buttons and FileUpload in compose — both removed in v4.3.1 (platform endpoints don't exist).

---

## [4.2.0] — 2026-04-11

### Added

- Multi-provider DUI panels (SDK v1.5.0 baseline)
- IMAP direct fallback on skeleton cache miss
- Fernet encryption for IMAP passwords at rest
- Microsoft Graph `$delta` poller in kernel event_poller
- IMAP fast count poller (60s)
- `connect_yahoo` handler (OAuth pending Yahoo approval)

### Changed

- app_id: `"gmail"` → `"mail"` (old `"gmail"` suspended in Registry)
- Store collection `gmail_accounts` kept as legacy name for data backwards compat
- Scopes migrated: `gmail:*` → `mail:*`
