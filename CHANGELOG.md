# Changelog

## [5.2.1] — 2026-05-09

### Fixed

- **Pre-warm `message_id` normalization (skeleton + panels)** — The `for m in more: m = {**m, ...}` loop rebinds the loop variable but does not update the source list. `all_msgs.extend(more)` therefore extended with unnormalized dicts. Emails on pages 2+ of `InboxMessages` had `id` but no `message_id`, causing viewer opens to fail for Gmail. Fixed with a list comprehension that rewrites `more` before extending. Affected paths: `skeleton.py` pre-warm loop and `panels.py _fetch_inbox_messages`. (`panels_schedule.py` already used the correct `norm2.append(m)` pattern.)

- **`fetched_at` required field crash** — `InboxManifest`, `InboxPage`, and `InboxMessages` declared `fetched_at: datetime` without a default. Any call that constructed these models without explicitly passing the field (e.g. from a stored cache hit) raised `ValidationError`. Changed to `Field(default_factory=lambda: datetime.now(timezone.utc))`.

### Refactored

- **`_oauth_state()` DRY** — Was duplicated verbatim in `handlers_connect.py` and `handlers_panel_actions.py`. Extracted to `ctx_helpers.py` with null-safe `ctx.user` access. Both files now import from there.

- **Store access consistency in `impl_connect_imap` / `impl_add_imap`** — Both functions called `_all_accounts()` (returns `list[dict]` with `doc_id` key) but then accessed results as `d.data` / `d.id` (Document API). Changed to `d.get()` / `d["doc_id"]` to match the actual return type.

- **Dedup loop in `impl_sync_contacts`** — Replaced clever one-liner `[c for c in found if not (c["email"] in seen or seen.add(...))]` with explicit loop for readability.

- **`impl_compose_send`** — Removed unused `attachments: list | None = None` parameter (no platform binary upload support).

- **Import ordering in `providers/helpers.py`** — `hashlib` and `re` moved to the top-level import block.

- **Attachment label** — Removed emoji from filename label in `panels_email_viewer.py`.

- **`skeleton.py` pre-warm** — Fixed `get_provider(acc).fetch_page(...)` → `provider.fetch_page(...)` (provider was already resolved above). Corrected comment: `200 initial` → `20 initial` (matches `INBOX_FETCH_SIZE`).

### Improved

- **All 35 `@chat.function` descriptions rewritten** — Every description now unambiguously identifies its function's purpose, distinguishes it from similar functions, and where applicable cross-references the correct alternative (e.g. `delete()` → "use purge() for permanent deletion"). Key corrections:
  - `send`: removed false "Requires subject" claim — subject is auto-generated from body
  - `star`: removed "toggles" — it takes an explicit `starred: bool`, not a toggle
  - `folder` vs `inbox`: clarified that both are equivalent; prefer `inbox()` universally
  - `mail_action` / `compose_send` / `get_oauth_url` / `add_imap`: marked as panel UI helpers — LLM should use the named chat functions instead
  - `mark_read` / `mark_unread`: added cross-reference to `bulk_mark_*` variants
  - `archive` / `delete` / `purge`: explicit three-way distinction

- **`system_prompt.txt` updated** — Added explicit function-selection rules covering folder routing, send vs reply vs forward, connect provider routing, and panel-only function exclusions.

---

## [5.2.0] — 2026-04-30

### Fixed

- **inbox_panel stale account after pagination** — Root cause: platform injected `account=old@email` from previous paginated render into every panel call, including account switches. The longer the user paged, the deeper the stale value embedded in platform's param state. Fix: `account` parameter removed from `inbox_panel` signature entirely — absorbed into `**_unused_kwargs`. Active account always resolved from `ctx.store` via `_active_account(ctx, "")` which uses `is_active` flag. Platform cannot inject a stale account through store.

- **Cache race on account switch** — `get_or_fetch` could return stale entry in the brief window between `cache.delete` and the new write. Fix: when `do_switch_account` is set, cache bypassed entirely — `_fetch_page()` called directly.

- **VALIDATION_MISSING_FIELD for `body`** — LLM sends `content` instead of `body` per training. `SendParams.body` and `ReplyParams.body` now use `AliasChoices("body", "content", "message", "text")`. Schema-level fix — no workaround.

- **VALIDATION_MISSING_FIELD for `subject`** — `SendParams.subject` now optional (`default=""`). `impl_send` auto-generates subject from first line of body (up to 60 chars) when omitted.

- **doc_id pollution in store documents** — `_all_accounts()` returns `{"doc_id": d.id, **d.data}` dicts. On subsequent `ctx.store.update`, spreading `{**acc}` included `doc_id` as a document field. Fixed in `handlers_connect.py` and `handlers_panel_actions.py`: strip `doc_id` before update payload.

### Changed

- `inbox_panel` drops `account` parameter — store-based resolution only
- `folder_counts` uses `asyncio.gather` for all 7 folders in parallel (was sequential)
- Pagination: `Previous / Page N / Next` UI (developer/transactions pattern) with `page_num` + `prev_cursor` chain
- Folder tabs + RefreshCw button no longer pass `account=` to `__panel__inbox`
- `imperal.json` rewritten to SDK v3.x format: single `tool_mail_client_chat` entry point (was 35 manual tool entries); `sdk_version` field removed; `capabilities` corrected to match `app.py`

### Added

- `schemas_params.py` — 20 `@chat.function` Pydantic param models extracted from `schemas.py` (300L rule)
- `panels_inbox.py` — inbox UI helpers extracted from `panels.py` (300L rule)
- `imap_read_message.py` — `_sync_imap_read`, `_sync_imap_search`, `_sync_imap_folder`, `_parse_imap_body` extracted from `imap_read.py` (300L rule)
- `system_prompt.txt` recreated — was deleted in v5.0.0 migration; restored for ChatExtension

---

## [5.1.0] — 2026-04-30

### Fixed

- **Microsoft Starred = Inbox** — `_MS_PAGE_FOLDERS` had no `"starred"` mapping → defaulted to `"inbox"`. And `$orderby` combined with `$filter` on `/me/messages` returns Graph API 400 "InefficientFilter". Fix: `params.pop("$orderby", None)` + `$filter=flag/flagStatus eq 'flagged'` on `/me/messages` endpoint.

- **IMAP starred empty** — IMAP has no "starred" folder; flagged messages live in INBOX with `\Flagged` flag. `_sync_imap_fetch_page` for `"starred"`: selects INBOX, `SEARCH FLAGGED`. `_sync_imap_unread_count`: `SEARCH FLAGGED UNSEEN`.

- **prev/next email arrows did nothing** — `email_list_ids` was built incrementally: first email got `"id1"`, second got `"id1,id2"` — most emails had incomplete lists. Fix: build full `msg_ids` list before the loop, assign `full_ids` to all items with `current_index=i`.

- **Active badge never updated** — `accounts_panel` had `on_event:` refresh that required events from DirectCallWorkflow (which don't publish). Changed to `refresh="interval:30s"` — re-reads `is_active` from store every 30s.

- **`on_end_reached` cursor leaked across accounts** — Platform stored cursor in panel state. On any re-render (folder switch, account switch), platform re-sent `cursor=page2_cursor + account=old`. Fixed by removing `on_end_reached` entirely; replaced with explicit Prev/Next buttons.

- **Google/Microsoft: only one account per provider** — `impl_connect` and `impl_connect_microsoft` returned "already_connected" if any account of that type existed. Removed early return — always generates OAuth URL; supports multiple accounts per provider.

- **`star` action in `impl_mail_action`** — Missing `starred=True` kwarg in action_map. Also added `"unstar"` entry with `starred=False`.

- **`compose_send` Re:/Fwd: double prefix** — Subject prefix check was case-sensitive (`startswith("Re:")` missed `re:`, `RE:`). Changed to `.lower().startswith(...)`.

- **reply-all email exclusion** — Used substring match (`account_email not in addr`) — prone to false positives. Changed to regex-parse `<email>` and exact lowercase comparison.

- **`folder_counts` 6 sequential requests** — Replaced with `asyncio.gather` for parallel execution.

- **`ui.List total_items=0`** — Caused platform to render built-in pagination arrows `← 1/10 →` conflicting with manual Prev/Next buttons. Removed `total_items` parameter.

### Added

- Archive folder added to `FOLDERS` list in `panels_inbox.py` and `FOLDER_KEYS` in `handlers_panel_actions.py`
- Prev/Next navigation in email viewer (`_action_bar` receives `email_list_ids` + `current_index`)

---

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
