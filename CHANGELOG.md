# Changelog

## [6.5.3] — 2026-07-29 — Fix (real one this time): renamed providers/ -> mail_providers/ to make the cross-extension collision structurally impossible

### Fixed
- **v6.5.2 was necessary but not sufficient.** Adding `providers` + its submodules to
  `main.py`'s purge list only closed the collision window for THIS extension's own
  reload path. The platform's kernel has a second, independent isolation layer
  (`executor.py::_ext_isolated_import`, gated by a static `_EXT_BARE_NAMES_FOR_ISOLATION`
  allowlist that mirrors `loader.py`'s conflict-name list) — and neither list included
  `providers`. Confirmed live on the server: three extensions ship a top-level package
  literally named `providers` (`file-reader`, `google-drive-connector`, and this one),
  so depending on load order and on whether a given import site is deferred (inside a
  function body, which several of ours are: `panels_filters_bar.py`,
  `handlers_filters.py`, `panels_filter_view.py`, `panels_inbox_panel.py`,
  `panels_accounts.py`, `ctx_helpers.py`) vs top-level, the bare name `providers` could
  still resolve to a DIFFERENT extension's package even after v6.5.2 — which is exactly
  why the left inbox panel and right panel filters were still broken after that release.
- **Real fix:** renamed the package `providers/` -> `mail_providers/` everywhere in this
  extension (16 submodules + all import sites). This makes the name collision
  structurally impossible regardless of load order, deferred-vs-eager import site, or
  whether/when the platform's own kernel isolation lists get updated to include
  `providers` — we no longer depend on that fix landing on their side at all.
- Reproduced the exact adversarial scenario (foreign `providers` package pre-cached in
  `sys.modules` before this extension loads) and confirmed `mail_providers` resolves
  correctly to our own package every time.
- Verified: 48/48 tests pass, all 6 panels register cleanly, `main.py`'s purge list
  simplified accordingly (package renamed so the old `providers.*` purge entries are now
  moot, but kept purging `mail_providers.*` for hot-reload safety).

## [6.5.2] — 2026-07-29 — Fix: left inbox panel gone + right panel filters broken (providers package collision)

### Fixed
- **Left panel missing entirely, right panel filters non-functional.** Root cause: `providers/`
  is a real Python *package* (`providers/__init__.py` exposing `get_provider`,
  `GoogleMailProvider`, `MicrosoftMailProvider`, `ImapMailProvider`), not a flat module — but
  it was missing from `main.py`'s `sys.modules` purge list entirely. Three OTHER extensions
  in this same platform (`doc-reader`, `file-reader`, `proxmox-connector`) also ship a
  top-level package named `providers` with completely different (in file-reader's case,
  empty) contents. In the platform's shared worker process, whichever extension's
  `providers` package got imported first won the bare name in `sys.modules` — if mail-client
  loaded/reloaded after one of those, every one of its modules doing
  `from providers import get_provider` (`panels_inbox_panel.py` — the left `inbox` panel,
  `panels_accounts.py` / `panels_filters_bar.py` — the right panel's Accounts/Filters tabs,
  plus `handlers_connect.py`, `skeleton.py`, `handlers_contacts.py`, `handlers_manage_impl.py`,
  `ctx_helpers.py`) raised `ImportError: cannot import name 'get_provider' from 'providers'`
  instead of loading — which panel-render-failure surfaces exactly as "left panel is gone,
  right panel there but its filter tab doesn't work".
- **Fix:** added `providers` and all 16 of its submodules to `main.py`'s purge list, same
  pattern `doc-reader` already uses for its own (differently-shaped) `providers` package.
  Reproduced the exact failure and confirmed the fix live: with a foreign `providers` package
  pre-cached in `sys.modules`, `from providers import get_provider` raised ImportError before
  the fix and resolved correctly to mail-client's own package after it.
- Verified: 48/48 tests pass, all 6 panels (`inbox`, `email_viewer`, `accounts`, `compose`,
  `add_account`, `secrets`) register cleanly, `providers` resolves to mail-client's own file.

## [6.5.1] — 2026-07-29 — Fix: sys.path leak let another extension's bare `import app` resolve to ours

### Fixed
- **Cross-extension import bleed (`SERVER_URL` missing from `app`).** Signoz report:
  `imperal-platform-worker`'s `ext_scheduler` was raising `cannot import name 'SERVER_URL'
  from 'app' (/opt/extensions/mail/app.py)` ~1430x/24h while running
  `imperal-matomo-analytics-extension.daily_summary` -- a completely different extension.
  Root cause on our side: `main.py` inserted this extension's directory at `sys.path[0]`
  on load and never removed it. Multiple extensions share one worker process, and several
  of them (including `imperal-matomo-analytics-extension`) use the same flat module name
  `app.py`. With our directory left on `sys.path`, a later/deferred bare `import app`
  from another extension could resolve to *our* `app.py` instead of its own, which has no
  `SERVER_URL` constant. Same class of bug already hit `gsc-connector` and
  `bing-webmaster-connector` before (there it was `accounts.py`); this is the same fix:
  once our own modules are cached in `sys.modules` under their bare names, we no longer
  need our directory on `sys.path`, so `main.py` now removes it right after import.
- No behavior change for mail-client itself -- this only stops it from being a source of
  contamination for other extensions sharing the worker process.

## [6.5.0] — 2026-07-19 — Fix: skeleton was re-notifying old mail as "new" (duplicate alerts)

### Fixed
- **`mail_inbox_summary` skeleton — duplicate new-mail notifications.** Live evidence: the
  same subject re-announced up to 16x over a 28h window, some byte-identical texts firing
  5x with gaps as tight as 482s. Root cause: `last_message_ids` was a SNAPSHOT — REPLACED
  every refresh with just the current INBOX page-1 window (`INBOX_FETCH_SIZE=25` ids)
  instead of being unioned with what came before. Any message that fell off that 25-id
  window (page jitter, a burst of >25 new arrivals in one tick, or a `ctx.store.update`
  write silently swallowed by a bare `except: pass`) got re-classified "new" the next time
  it resurfaced in page 1, and `ctx.notify` re-fired the identical text.
- **Fix — three parts:**
  1. The seen-id set is now MONOTONIC: `curr_ids` is UNIONED into the stored set (keyed by
     id → last-seen timestamp, capped at the most recent 500) instead of replacing it. An
     id ever seen is never forgotten and never re-announced. Old bare-list-shaped stored
     data (`last_message_ids: [...]`) is transparently migrated on read.
  2. `ctx.store.update` failures are no longer swallowed silently — on a failed persist,
     notify is SKIPPED for that tick (a watermark we know didn't make it to storage must
     never be allowed to fire notifications; it will correctly retry next tick instead).
  3. Belt-and-suspenders: a persisted `last_notified_date` watermark additionally gates
     notify — a candidate whose own date isn't after the watermark never fires, even if
     its id looks "new" (defense in depth against any future id-diff edge case).
- Audited the sibling snapshot-counter pattern in `newsletter-writer-extension` /
  `article-writer-extension` skeletons (`_load_review_count`/`_save_review_count`) — that
  pattern counts distinct-status totals rather than diffing an id window, so it does not
  reproduce this bug; left unchanged.
- **Upgraded to imperal-sdk 5.9.12** (from 5.9.11) — this release replaces the per-call
  `httpx.AsyncClient()` in `store`/`notify`/`skeleton`/`secrets`/`cache`/`billing` clients
  with one shared keep-alive connection pool per process, directly reducing the class of
  transient write failures (timeouts under load) that could produce the stale watermark
  this ticket's root cause depended on.
- New `tests/test_skeleton.py` (21 tests) — full coverage of the monotonic merge, the
  legacy-shape migration, the failed-write skip, and the date-gate.

## [6.4.0] — 2026-07-18 — `read_attachment`: read the actual content of email attachments

### Added
- **New `@chat.function read_attachment(message_id, attachment_id, account="")`** — downloads
  ONE attachment's real bytes from the provider and extracts its TEXT via the shared
  doc-extractor engine (`https://api.webhostmost.com/doc-extractor`) that File Reader already
  uses in production — under its OWN storage partition (`source="mail_attachment"`), so a read
  attachment's text never mixes with File Reader's own uploaded documents for the same user.
  `read_email()` already reported an attachment's filename/size/mime; it never opened it — this
  closes that gap for PDF/DOCX/XLSX/PPTX/images (OCR/vision)/plain text/CSV, etc.
- **`providers/attachments.py`** — new engine client, modeled 1:1 on file-reader's own
  `providers/extractor.py` (same `ctx.http` platform client, same retry-on-5xx `_send` helper,
  same `imperal_id()` hard-fail-if-missing scoping). `ingest_and_wait()` polls the engine's async
  drain loop (~1s cadence) briefly so a first-time read doesn't come back empty; gives up
  honestly after 8s with a `status="processing"` result rather than stalling the chat turn.
- **`BaseMailProvider.download_attachment()`** — new abstract-with-default method (returns an
  honest "not supported" error by default); implemented per provider:
  - **Gmail** (`google_read.py`) — `GET .../messages/{id}/attachments/{attachmentId}`, decodes
    Gmail's url-safe base64 (`base64.urlsafe_b64decode`, distinct from ordinary base64).
  - **Microsoft Graph** (`microsoft.py`) — `GET .../messages/{id}/attachments/{attachmentId}`,
    rejects non-`fileAttachment` types (item/reference attachments have no bytes to read),
    decodes ordinary base64 `contentBytes`.
  - **IMAP** (`imap.py` + `imap_read_message.py`) — IMAP has no native attachment id (unlike
    Gmail/Graph), so a new `_walk_imap_attachments()` lists real file parts (named, non-multipart)
    keyed by their stable `msg.walk()` index; `_sync_imap_download_attachment()` re-fetches the
    message by UID and decodes that same indexed part. `read_email()`'s IMAP path now actually
    populates `attachments[]` (was hardcoded absent before — IMAP never parsed attachment
    structure at all).
- **`AttachmentContent` (schemas.py) / `AttachmentEntity` (schemas_sdl.py)** — new response model
  + SDL entity (`sdl.Entity` + `sdl.Bodied`), `status` mirrors the engine's own states
  (`ready`/`processing`/`unsupported`/`error`) so a caller can tell "still indexing, try again
  shortly" apart from a real failure.
- **`tests/test_read_attachment.py`** — 27 pytest cases (new `tests/` dir for this extension),
  fully mocked `ctx.http` (no live credentials needed): engine client (ingest success/empty
  content rejected/no documents in response, read_text, overview, retry-on-5xx, retry-on-network-
  exception, hard-fail after repeated 5xx, `ingest_and_wait` cached-hit/polls-until-processed/
  gives-up-after-deadline/no-document-id), all three providers' `download_attachment` (Gmail
  success/404/empty-data, Graph success/404/non-file-attachment/empty-contentBytes, IMAP
  MIME-walk success/invalid-index/no-filename), and `impl_read_attachment` orchestration
  (unknown attachment id, happy path, still-processing, unsupported/failed extraction).

### Why not `ctx.files`
Considered wiring to the new kernel-injected `ctx.files` primitive (imperal-sdk 5.9.11+, per the
File Mage design doc) instead of a bespoke HTTP client. Its exact method contract could not be
independently confirmed against a live kernel checkout in this session — the design doc says
`ctx.files.extract(bytes, filename)`, a later delegation ticket says
`ctx.files.ingest(content, filename, mime_type=...)` — a real discrepancy, not a formatting
nuance, and this ships to every Mail Client user. Verified the doc-extractor engine's actual
`/v1/documents` contract directly against its own source over SSH instead, and reused the
already-proven client pattern from File Reader's `providers/extractor.py`. Revisit once
`ctx.files`'s contract is confirmed the same way.

### Fixed (housekeeping, same pass)
- **9 pre-existing `V11` missing-docstring warnings** (`inbox_analytics`, `archive`, `delete`,
  `mark_read`, `star`, `move`, `apply_actions`, `inbox_cleanup`, `purge`) — one-line docstrings
  added to each. `imperal validate` now reports **0 errors, 0 warnings** (was 9 warnings).

## 2026-07-18 — SDK 5.9.9 + English-only tool descriptions (no version bump)

- SDK pin bumped: 5.9.3 → 5.9.9 (README badge only — no `pyproject.toml` in this repo).
- All `@chat.function` descriptions stripped to English-only (was bilingual `'какая-то русская
  фраза', 'english phrase'` example lists) — workspace-wide policy, all 9 SeeU extensions.
  Also translated two non-description spots that were doing the same job with raw Russian text
  instead of an English hint: `schemas_params.py`'s folder-name alias dict (`{"входящие": "INBOX",
  ...}` → English keys only) and `handlers_cleanup_impl.py`'s unsubscribe-detection keyword list
  (dropped the `"отписат"` entry). `skeleton.py`'s comment example translated too.
- No functional/version change — `imperal build`/`imperal validate` re-run clean, 0 new
  errors/warnings (same 9 pre-existing `V11` missing-docstring warnings as before).

## [6.2.0] — 2026-06-16 — background_task for query= bulk ops (SDK 5.3.0)

### Changed
- archive, delete, mark_read, purge, inbox_cleanup: query= path now uses ctx.background_task(long_running=True)
  — handler returns immediate ack, platform injects final result as a new bot turn
  — prevents session timeout when processing thousands of matching emails
- SDK pin bumped: 5.2.2 → 5.3.0

## v5.8.0 — 2026-06-09 — admin-ticket fixes (inbox total / MS date search / routing)

Three fixes from the Imperal-admin ticket, verified against the live code, our prior
count work (`b34b99a`, `4a590a7`), and `docs.imperal.io`. (`count`/`count_today` was already
shipped as `count_emails` in `4a590a7` — confirmed, no change needed.)

- **Inbox no longer reports a fake total** (`schemas_sdl_builders.build_inbox_page`):
  was `total=len(items)` — the length of a CAPPED display page, a lying fact that leaks into
  the narrator/chains. Now `total=None`, which SDL explicitly permits (`EntityList.total` is
  `int | None`, "total across all pages, **if known**" — for a page it is not known). Pagination
  awareness stays via `has_more` + `unread_count`. `SearchPage.total` is untouched (it carries a
  real provider count). To COUNT, callers use `count_emails()`.
- **Microsoft date-operator search** (`providers/microsoft.py`): Gmail date operators
  (`newer_than:1d`, `after:`, `before:`) are Gmail-only — Graph treated them as plain `$search`
  text, so date searches/counts on MS accounts were wrong. Now `search()` translates them to a
  Graph `$filter` on `receivedDateTime` (same field/format proven in `get_today_count`):
  pure-date → `$filter` with exact `@odata.count`; text-only → unchanged `$search`; mixed
  text+date → `$filter` date window + client-side text match (Graph forbids `$search`+`$filter`
  together, so this is the only reliable path; total bounded by the ≤250 window). Unparseable
  date tokens are left intact, never silently dropped. This also fixes `count_emails(query=…)`
  date counts on MS (it routes through the same `search`).
- **`inbox()` description rewritten** for routing precision: explicitly sends COUNT
  ("how many / сколько / total / all") → `count_emails()`, DATE/period ("today / this week /
  since …") → `search()` with the matching Gmail date operator (`newer_than:1d` etc.), and
  sender/keyword → `search()`. States plainly that the list is a capped page with no folder total.

## skeleton read-query COUNT surface — 2026-06-06 (commit `b34b99a`; all providers)

Skeleton reworked from a recent-items list into a **count surface** so the brain answers
"сколько всего / непрочитано / спам / архив / сегодня" **directly from skeleton facts** —
no search, so no search-count cap (the `2001` bug) and no page-limited list (the `15` bug).

- **New provider methods** (`base` default + Google/Microsoft overrides; IMAP via default + SINCE):
  - `get_counts(ctx, acc) → {total, inbox_total, unread, spam, archive}` — normalized.
    Google `total` = `users.getProfile.messagesTotal`; Microsoft `total` = `/me/messages $count`
    (ConsistencyLevel: eventual); IMAP `total` = INBOX total (best-effort). Gmail `archive` = 0
    (no Archive folder). `spam`/`archive` via each provider's folder stats.
  - `get_today_count(ctx, acc) → int` — Google `after:YYYY/MM/DD` (id-pagination, not estimate),
    Microsoft `$filter receivedDateTime ge … + $count`, IMAP `SEARCH SINCE`.
- **`skeleton.py`** envelope (5 fields): `active_account`, `unread_total`, `today_total`,
  `total_all`, `per_account` `[≤5 {email, total, unread, spam, archive}]`. Per-account loop now
  calls `get_counts` + `get_today_count` (instead of a single folder-stat). Cache warmup uses
  `inbox_total` (panel inbox total stays correct); `ctx.store` unread/last_message_ids untouched.
- **Dropped:** `recent_emails` (low signal at scale — anchored to the busiest mailbox),
  `accounts_connected`, per-account `is_active`, `filter_count`/`rule_count` (detail-on-demand).
- **Cost:** ~+3 API calls/account/tick (getProfile/$count + spam stat + today). Within quota.

## skeleton recent-emails surface — 2026-06-06 (commit `479c612`; built strictly per docs)

Implemented **exactly** to the docs recipe `recipes/skeleton-data-surface` (counts + a
recent-item array ≤5, label key `title`, `{"response":{…}}`, degrade-to-zeros, ≤6 top-level fields).

- **`skeleton.py`** — `skeleton_refresh_mail_inbox_summary` now returns the 6-field envelope:
  `unread_total`, `active_account`, `per_account` `[{email, unread_count}]`,
  **`recent_emails`** `[≤5 {title, from, account, date}]`, `filter_count`, `rule_count`.
  `recent_emails` = newest ≤5 across all accounts, assembled from the page-1 messages the
  skeleton already fetches → **no extra API call**. `date` normalized to `YYYY-MM-DD`.
  Added the recipe's `uid` guard (`{"response": {"note": …}}` when no user).
- **Dropped** as redundant: `accounts_connected` (= `len(per_account)`) and per-account
  `is_active` (= top-level `active_account`).
- **Untouched** (panel depends on them): the `ctx.cache` warmup (25 msgs incl. `date`) and the
  `ctx.store` per-account `unread_count` / `last_message_ids` updates.
- **`schemas.py`** — reference `InboxSummary` model synced to the new shape (skeleton still
  returns a raw dict; the model documents the shape only).

## post-5.7.0 patches — 2026-06-05/06 (commits `f549e4d` → `391b897`; code version stays 5.7.0)

### Skeleton — zero-Pydantic response (fixes persistent InboxSummary ValidationError)
- **`skeleton.py`** — `skeleton_refresh_mail_inbox_summary` now returns a RAW dict
  `{"response": {…6 fields…}}`. No `InboxSummary(...)`, no `PerAccountUnread(...)`, no
  `model_dump()` anywhere in the response path. `per_account` is a list of plain dicts
  `{email, unread_count, is_active}`. This removed the recurring 3-error ValidationError on
  every skeleton run (`f549e4d` ActionResult→dict, `53436d4` drop total_messages, `ff7108e` zero Pydantic).
- **`schemas.py`** — `PerAccountUnread.total_messages` removed; `InboxSummary.per_account: list[dict]`.
- `skeleton_alert_mail_inbox_summary` now takes `(old, new)` snapshots and reports the unread delta.

### Search & filter counting — accurate, no timeout (`fc9474d`)
- **`providers/google_read.py`** — `search()` counts the TRUE total by paginating real
  message IDs (`fields=messages/id,nextPageToken`, cap 2000) and **ignores Gmail
  `resultSizeEstimate`** (it under-reported, e.g. 15 for a 50-result query). Previews are
  now fetched concurrently (`Semaphore(12)`) — eliminates the 15 s filter-panel timeout on
  large result sets.
- **`handlers_inbox.py`** — `search` description rewritten: `from:<brand>` not `from:domain.com`
  (catches subdomains/related domains/display name), Gmail date operators (`newer_than:1d`,
  `after:/before:`), and "total is accurate, no need for large max_results just to count".

### Filters & folder prefs (`fc9474d`, `391b897`)
- **`handlers_filters.py`** — `create_filter` is idempotent (same name + account_email → reuse,
  no duplicates). `set_folder_prefs` description: it REPLACES the visible set (read current
  prefs first when "adding"), + panel-visibility trigger phrases (RU/EN).

### Bulk operations (`391b897`)
- **`handlers_manage.py`** — all 7 bulk descriptions now instruct: load message_ids first via
  inbox()/folder()/search() on the TARGET mailbox, and pass `account=` for that same mailbox
  (a message_id from one account 404s on another). Fixes partial bulk failures (9/10, 1/3).

### Branch/deploy note
- Local branch is `master`; the Developer Portal deploys from `main`. All of the above reached
  prod only after `git push origin master:main` (the fixes had been committed to `master` but
  never pushed to `main`).

## [5.7.0] — 2026-06-04 (commit `c15a81a`)

### Smart Filters — panel integration + per-account + pagination
- **`panels_filter_view.py`** — `render_filter_panel` fetches all results (up to 200) in one API call, client-side pagination N/M pages; no extra calls per page. 15s asyncio timeout prevents panel hang.
- **`panels_filters_bar.py`** — filter bar is per-account (shows only filters for current active account). No duplicate ✕ clear button (header ✕ serves this).
- **`panels_inbox.py`** — `_build_folder_tabs`: all folder tab buttons now explicitly pass `filter_id=""`. Fixes SDK param accumulation bug that caused every inbox render to trigger a Gmail search → infinite loading.
- **`handlers_filters.py`** — `create_filter` stores `account_email`; `list_filters`/`apply_filter` filter by active account. `from_emails: list[str]` param for exact sender addresses. `apply_filter` uses filter's specific account.
- **`schemas_params.py`** — `CreateFilterParams`: added `account`, `from_emails` fields.

### Skeleton — properly optimized for docs 6-field classifier rule
- `InboxSummary`: 6 fields in importance order: `unread_total`, `accounts_connected`, `per_account`, `active_account`, `filter_count`, `rule_count`
- `PerAccountUnread`: `total_messages` = real API count (not page size 25), `is_active` flag
- `filter_count` / `rule_count` from `ctx.store.count()` (docs-documented pattern)
- `recent_messages` removed from classifier data: list[25] collapses to `list[25]` hint (useless). Cache warmup (25 msgs → ctx.cache for instant panel load) unchanged.
- skeleton summary: `"18624 unread | active:ignat@webhostmost.com | 3filt 2rules"`

### Automation rules — event-driven primary path
- **`handlers_rule_event.py`** — `process_event_email()`: event-driven, user-scoped ctx, no fan-out needed. Falls back to `_process_user_rules` if no message_id in event.
- **`app.py`** — `on_email_received`: logs event keys, calls `process_event_email`. Confirmed in prod logs.
- **`handlers_rule_runner.py`** — `_parse_date()`: RFC2822 + ISO → datetime (fixes string comparison bug). `_do_autoreply`: uses `provider.send()` not `reply()` (reliable, no thread headers needed). `last_run_at` always updated. Loop protection expanded.
- **Known issue**: `on_email_received` ctx.user.imperal_id="" in current platform → rules not found. Needs platform investigation.

### Bug fixes
- **UnboundLocalError** — `panels_inbox_panel.py`: removed duplicate `from panels_inbox import _build_email_list` inside `if filter_id:` block. Was causing `cannot access local variable` error → ALL inbox panel renders failing.
- **`trigger_rules_now`** — new `@chat.function` for manual rule trigger from chat with debug output.
- **`list_mail_folders`** — moved to `handlers_filters.py`, changed `data_model=MailFoldersResult` (was wrong `AccountsPage`). SDL violation fixed.
- **Security** — replaced `__import__("datetime")` ×3 with `import datetime as _dt` at module level.
- **`status()` description** — updated to explicitly return real email addresses, not generic types.
- **`trigger_rules_now` description** — clear trigger phrases so LLM routes correctly.

### SDL audit
- `schemas_sdl_rules.py`: added `MailFoldersResult`, `MailFoldersResult` SDL entity
- `schemas_sdl_builders_rules.py`: added `build_mail_folders()`, `build_mail_folders()`
- All 60 `@chat.function` handlers: `data_model=` SDL entity + `imperal build` → x-sdl in manifest

### Right panel — Accounts tab visual
- Active account: `"✓ Active — Google"` subtitle, `"✓ 18624"` badge (checkmark + unread count)
- Filters tab: shows `from: ignat@..., zalupa@...` (from_emails) instead of "match all"
- Filters tab: NOT clickable, only Delete action on right (management only in right panel)

---

## [5.6.0] — 2026-06-01

### Smart Filters (virtual mailboxes)
- **`handlers_filters.py`** — `create_filter / list_filters / apply_filter / update_filter / delete_filter`. All accept filter_id OR filter_name (lookup by both).
- **`set_folder_prefs / get_folder_prefs`** — choose visible folders in left panel.
- **`panels_filters_bar.py`** — filter buttons in left panel (initial implementation with apply_filter in chat).

### Automation Rules
- **`create_forward_rule`** — silent forward only. Explicit NOT to create autoreply simultaneously.
- **`create_autoreply`** — time_window or always mode. Dedup via `mail_autoreply_sent`. Loop protection.
- **`list_rules / toggle_rule / delete_rule`** — ID or name lookup.
- **`handlers_rule_runner.py`** — `@ext.schedule("mail_rule_runner", cron="*/5 * * * *")`. Fan-out with `list_users → as_user`.

### Bulk operations (complete set)
- `bulk_move / bulk_star / bulk_purge` — new bulk handlers.
- All `BulkParams`: `@field_validator` coerces `list[str] → CSV` — LLM can pass list from previous search.

### Other
- `set_folder_prefs`: `@field_validator` normalizes "inbox"→"INBOX", Russian aliases.
- `search`: `oldest_first` bool (for finding first-ever email), `folder` (IMAP), max_results 1-200.
- `list_mail_folders`: lists available folders + visibility state.
- Email body: `raw_body` (HTML stripped) + `excerpt` (800 chars) in `build_email_message`.
- Right panel: 3-tab (Accounts / Filters / Rules) with accumulated `tab=` param.

---

## [5.5.0] — 2026-06-01

### SDL migration (SDK 5.2.0 — Structured Data Layer)
- **New `schemas_sdl.py`** — 22 SDL entity classes (`sdl.Entity` + facets). Emails compose `Correspondents`/`Bodied`/`MessageState`/`Threaded`/`Attached`; contacts compose `ContactPoints`; lists use `sdl.EntityList[T]`. Mail-specific fields use the `mail.*` namespace via `sdl.field(role=...)`.
- **New `schemas_sdl_builders.py`** — 24 builder functions converting impl-layer Pydantic results (`EmailBody`, `InboxPageResult`, …) → SDL entities. Includes address parsing (`"Name <email>"` → `sdl.Ref(kind="contact")`), RFC2822/ISO date → `datetime`, `body_type` → SDL `body_format`, `unread` → inverted `is_read`.
- **All 35 `@chat.function` handlers** switched `data_model=` from plain Pydantic response models (`EmailBody`, `InboxPageResult`, …) to SDL entities (`EmailMessage`, `InboxPage`, …). Each handler now passes `data=build_*(r)` instead of `data=r.model_dump()`.
- **`main.py`** — `schemas_sdl` + `schemas_sdl_builders` added to `sys.modules` purge list and import order (before handlers).
- **`imperal.json`** — `sdk_version` `5.0.0` → `5.2.0`. NOTE: per-tool `return_schema` stays `{}` (manifest hand-maintained; generated by `imperal build`).

### Layering (not duplication)
- `schemas.py` (26 impl response models) is retained and load-bearing — `impl_*` functions return these; builders consume them. `schemas_sdl.py` is the presentation/contract layer on top. No model removed.

### Notes / legacy
- **`system_prompt.txt`** is orphaned (the file read was removed in 5.4.2+; the file itself was never deleted). Safe to delete.
- `ChatExtension(tool_name="tool_mail_client_chat")` retained — `tool_name` is still a required positional arg in SDK 5.2.0 (emits DeprecationWarning; removal blocked until SDK drops the param).
- Version bumped `5.4.2` → `5.5.0` (`app.py`, `imperal.json`, `main.py` docstring).

---

## [5.4.2+] — 2026-05-28

### Fixed
- **Star badge (blue dot on read email after starring)** — `_execute_panel_action` no longer invalidates cache for state-only actions (`star/unstar/mark_read/mark_unread`). Only structural actions (archive/delete/spam/restore/unarchive/unspam) invalidate. Optimistic patch now receives `do_was_unread=is_unread` from the star button click, explicitly preserving the displayed read state on `star/unstar`.
- **HTML tags visible as text in sent emails** — `panels_email_viewer.py`: auto-detect HTML body when `body_type != "html"` but content starts with `<`. Fixes RichEditor-composed emails returning `body_type="text"` from some providers.
- **Compose panel conflict with email_viewer** — `compose`: added `center_overlay=True`, changed `mode` default to `""`, added `return None` guard when `mode=""`. Prevents compose from occupying center slot on cold start and conflicting with email_viewer (both are now proper center overlays).
- **`email_viewer` showing "Select an email" on cold start** — Returns `None` instead of `ui.Empty(...)` when `message_id=""`. Center slot stays null; chat fills full width by default.
- **Pagination cursor not resetting on folder/search switch** — `page_cursor=""`, `prev_cursor=""`, `page_num=1` explicitly passed in all reset points (folder tabs, search bar submit, ✕ clear button, account switch).
- **No unread count on pages 2+** — `folder_stats_unread` accumulated param carries unread count across page navigation; provider doesn't return stats on page 2+.
- **ERROR without message on provider failures** — all `@chat.function` wrappers changed from `except RuntimeError` to `except Exception`. Network/SSL/timeout errors from providers now surface as readable error messages.
- **`ui.Password` regression in add_account wizard** — both password fields in `_step_password` and `_step_advanced` restored to `ui.Password` (were reverted to `ui.Input` during v5.4.2 file split).

### Added
- **Pagination ← N → navigation** — arrow-only buttons (no Russian text) with page number between them. `prev_cursor` param enables true back-navigation to previous page (not just page 1). Pages 2+ cached under `msgs:{email}:{folder}:p{N}` (TTL=60s) — back navigation hits cache instantly.
- **Skeleton `recent_messages`** — `InboxSummary.ActionResult.data` now includes up to 25 message previews from first account (`message_id/subject/from/date/snippet/unread/starred`, NO body). Enters LLM classifier envelope → Webbee knows inbox contents without calling `inbox()`.
- **`id_projection` on 12 functions** — SDK v4.1.2: `message_id` on read_email/reply/forward/archive/delete/mark_read/mark_unread/star/move/purge; `thread_id` on get_thread; `email` on delete_contact. Tells kernel chain planner which params field carries the target ID.
- **`data_model=` on all 35 handlers** — V23 (read) and V24 (write) SDK 5.0.1 validators satisfied. Schemas already existed; wired up to decorators.

### SDK Compliance
- **Removed `system_prompt=`** from `ChatExtension` (no-op in SDK 5.0.0, LLM router removed).
- **Removed `_SYSTEM_PROMPT` file load** from `app.py` (wasted I/O at startup).
- **Removed secrets panel hack** from `app.py` (`ext._panels["secrets"]["slot"] = "overlay"`) — dead code in SDK 5.0.1+ which lazy-registers secrets panel only when `@ext.secret` is declared.
- **Updated function descriptions** — `inbox`: PRIMARY function for listing emails; `search`: only for specific searches; `reply`/`forward`: instructs chain planner to call `inbox()` first.

### Refactor
- **`panels.py` split** (v5.4.2 300-line rule) — `inbox_panel` + `_fetch_inbox_messages` extracted to `panels_inbox_panel.py`. `panels.py` reduced to ~45 lines (panel decorators only). `main.py` updated with new module in `_MODULES` + import.

---

## [5.3.6] — 2026-05-17

### Fixed
- **`handlers_ui.py:_email_ui`** — `body.body_text` → `body.body` (поле переименовано в v5.3.3, legacy-имя не обновили). Рендеринг полученного письма в inline чат-UI вызывал `AttributeError`.
- **`schemas.py:SkeletonAlertMessage`** — модель описывала `message: str` вместо актуального ответа `{unread_total: int, per_account: list}`. Приведена в соответствие с `skeleton_alert_mail_inbox_summary`.
- **`main.py`** — docstring всё ещё говорил `v5.2.0 / SDK v4.x`. Обновлён до `v5.3.6 / SDK v5.0.0`.

### Docs
- **`README.md`** — SDK badge `2.0.0` → `5.0.0`, версия `5.0.0` → `5.3.6`, убран несуществующий `tools.py`, исправлены слоты панелей (email_viewer/compose/add_account — overlay+center_overlay, не center/right), `InboxPage` → `InboxMessages`, добавлены все новые файлы в архитектурную таблицу, обновлена секция skeleton.
- **`extensions/mail-client.md`** — версия/дата/коммит; "Optimistic UI" перемещена из Known Limitations в What Works; добавлены v5.3.4+v5.3.5 в changelog таблицу; исправлена заметка про panels_compose.py (password → TagInput defaults); обновлён security invariant `compose_send to`.

---

## [5.3.5] — 2026-05-17

### Fixed
- **`skeleton.py` — `skeleton_alert_mail_inbox_summary` стаб** (регрессия из merge-конфликта v5.3.3): alert tool был заглушкой `data={}, summary=""`. Реализован как lightweight check: читает `unread_count` из store для каждого аккаунта (без API-вызовов) и возвращает `unread_total` + `per_account`. Ядро использует это для значка и gating push-уведомлений.
- **`skeleton.py` — нет таймаутов**: `_refresh_token_if_needed`, `get_folder_stats`, `fetch_page` вызывались без `asyncio.wait_for`. Зависший IMAP/OAuth-коннект мог заморозить весь skeleton indefinitely. Добавлены таймауты: 5 s на token refresh + folder stats, 10 s на fetch_page (аналогично panels.py).

### Verified OK (не требует изменений)
- Открытие письма → mark as read: все 3 провайдера (Gmail, Microsoft, IMAP) вызывают `_update_read_in_cache` → `_invalidate_first_page` внутри `read_email`. Когда пользователь возвращается в inbox, кеш уже инвалидирован → fetch fresh → письмо отображается как прочитанное.

---

## [5.3.4] — 2026-05-17

### Fixed
- **Bug 2 — Reply "TO field empty" error** (`handlers_panel_compose.py`): TagInput pre-filled `values=` are display-only and not always submitted by the SDK form. For reply mode, if `to` arrives empty but `message_id` is set, the handler now fetches the original message's `from` field as a server-side fallback before raising the "required" error.
- **Bug 3 — Unconfirmed TagInput text lost on submit** (`panels_compose.py`): Added `to` and `cc` to Form `defaults` so pre-filled recipient tags have a fallback value even when the user never interacts with (and thus never "confirms") the TagInput field.
- **Bug 1 — Starred email read/unread state not updating visually** (`panels.py`): Applied optimistic in-memory patch to cached `InboxMessages` after `mark_read`, `mark_unread`, `star`, and `unstar` inline panel actions. Patches the specific message's `unread`/`starred` flag and writes the result back to cache, bypassing Gmail eventual-consistency lag that caused the old state to survive the next `fetch_page` call.

---

## [5.3.3-patch2] — 2026-05-17

### Fixed
- **`handlers_contacts.py:impl_contacts`** — `for d in docs` + `d.get()` on `Page` объект → `for d in docs.data` + `d.data.get()`. Список контактов через чат всегда возвращал пустой массив.
- **`handlers_contacts.py:impl_add_contact`** — `if existing:` всегда True (Page truthy даже когда пустой) → `if existing.data:`. Добавление контактов было невозможно: сразу выпадал "already exists".
- **`panels_compose.py`** — contact suggestions: та же ошибка `for d in docs` + `d.get("email")` → `docs.data` + `d.data.get("email")`. Autocomplete поля "Кому" в compose всегда был пустой.
- **`main.py`** — docstring версия исправлена с `v5.2.0` на `v5.3.3 / SDK v5.0.0`.

---

## [5.3.3-patch1] — 2026-05-17

### Fixed
- **Layout: compose холодный старт** — `compose_panel` всегда рендерил UI при вызове с дефолтными параметрами, занимая center slot при восстановлении состояния Kernel. Добавлен параметр `compose_active: str = ""` — панель возвращает `None` пока не передан `compose_active=True`. Все 4 точки вызова обновлены: Reply/Reply All/Forward в `panels_email_viewer.py`, Reply в `panels_inbox.py`.
- **Layout: email viewer холодный старт** — `email_viewer_panel` возвращал `ui.Empty(...)` при пустом `message_id`, занимая center slot. Изменён на `return None`.
- **Layout: slot="overlay"** — `email_viewer` и `compose` переведены с `slot="center"` на `slot="overlay"` + `center_overlay=True`, чтобы чат занимал центр по умолчанию.

---

## [5.3.3] — 2026-05-17

### Fixed
- **`schemas.py:EmailBody`** — поля `body_text`/`body_html` переименованы в `body`/`body_type` (соответствие реальному выводу всех трёх провайдеров). LLM никогда не получал тело письма.
- **`providers/helpers.py:_active_account`** — `for d in docs` → `for d in docs.data`, `if not docs` → `if not docs.data`, `d.get()` → `d.data.get()`. Document/Page паттерн был неправильный.
- **`panels.py:compose`** — добавлен `center_overlay=True` в `@ext.panel` декоратор.
- **`panels.py`** — cache write-back после account switch и integrity guard re-fetch.
- **`handlers_manage.py`** — добавлен `_invalidate_first_page()` во все 7 `impl_*` функций (archive/delete/mark_read/mark_unread/star/move/purge). До этого inbox показывал устаревшее состояние до 90 сек.
- **`skeleton.py`** — alert tool был пустым стабом, реализован полностью.
- **`app.py`** — `ext._panels["secrets"]` обёрнут в `try/except` для совместимости с SDK 5.0.0.
- **`handlers_ui.py`** — `body.body_text` → `body.body` (следствие EmailBody fix).

---

## [5.3.1-patch] — 2026-05-10

### Fixed
- **`refresh_panels=["inbox"]` missing from all chat-path write handlers** — `archive`, `delete`, `mark_read`, `mark_unread`, `star`, `move`, `purge`, `bulk_archive`, `bulk_delete`, `bulk_mark_read`, `bulk_mark_unread` (`handlers_manage.py`) and `send`, `reply`, `forward` (`handlers_inbox.py`) had no `refresh_panels`. Inbox appeared stale after every write action until next skeleton tick (60s TTL). Added `refresh_panels=["inbox"]` to all 13 handlers.

---

## [5.3.1] — 2026-05-09

### Fixed
- **Duplicate emails on load_more (cross-account cursor replay)** — `encode_cursor()` now accepts optional `account=""` param — cursor payload carries `_a` field binding it to the originating mailbox. `load_more` guard checks `_a == active_email` before appending; cursors from the wrong account or without `_a` are silently skipped. `clean_cursor()` strips `_a` before passing to provider (providers are unaware of this field).
- **Outlook hang** — Microsoft Graph occasionally returns cursors that loop on the same page; guard added to detect and break the loop.

---

## [5.3.0] — 2026-05-09

### Added

**Compose panel:**
- `ui.TagInput` for To/CC/BCC — autocomplete from `mail_contacts` store (up to 200 suggestions), email validation, comma/semicolon delimiters; `ComposeSendParams` coerces tag lists to CSV string for the existing `impl_send`/`impl_reply` signature
- `ui.RichEditor` for body — TipTap WYSIWYG with `toolbar=True`, replaces plain `ui.TextArea`

**Email viewer:**
- `ui.Tabs` — "Message" + "Headers" tabs; action bar stays sticky above tabs (outside tab container)
- Headers tab: `ui.KeyValue` with full metadata (from, to, cc, date, folder, message_id)
- `ui.Error` with retry action on load failure

**Inbox list:**
- `ui.ListItem(expandable=True)` — click to expand shows snippet + 4 inline action buttons (Reply, Archive, Delete, Mark Read) without opening the viewer; saves a round trip for quick actions

---

## [INBOX_INLINE_LIMIT] — 2026-05-09

### Changed
- **`INBOX_INLINE_LIMIT` 300 → 70** (`panels.py`) — panel cold-fetch was timing out on large mailboxes. 70 ≈ 3 pages at 25 msg/page; skeleton pre-warms up to 300 in background. Hot-cache path is unaffected.

---

## [5.2.4] — 2026-05-09

### Fixed
- **`interval:Ns` silently dropped by SDK** — `interval:30s` on `accounts_panel` never worked (SDK discards unrecognised refresh values). Removed. Account switching now driven by `refresh_panels` on ActionResult (works from both LLM `SessionWorkflow` and panel `DirectCallWorkflow`).
- **Account switch / disconnect / connect not updating panels** — `fn_switch_account`, `fn_disconnect`, `fn_connect_imap` now return `refresh_panels=["inbox","accounts"]` so both panels re-render immediately regardless of call path.

### Changed
- `accounts_panel` refresh: `interval:30s` removed; panel re-renders only when triggered by `refresh_panels` from a write action

---

## [5.2.3] — 2026-05-09

### Changed
- **`INBOX_INLINE_LIMIT` 200 → 300** — extend cold-fetch to match skeleton pre-warm depth (subsequently reverted to 70 to avoid timeouts)
- **`on_end_reached` pagination** — `_build_email_list` passes `total_items` from `InboxManifest` to `ui.List` so the native paginator shows real `< 1/N >` range even before all messages are fetched; `on_end_reached` fires `load_more` when user navigates past last loaded page via native arrows
- **`load_more` guard** — checks `InboxMessages.folder` and `InboxMessages.account_id` match current context before appending; stale replays after folder/account switch are silently ignored

---

## [5.2.2] — 2026-05-09

### Added
- **Remove/disconnect button per account** in accounts panel — `ui.Stack` layout replaces `ui.List`; `do_remove` param handles disconnect + cache invalidation inline in the panel
- **"Load more" button** in inbox list — `load_more_cursor` param on `inbox_panel` fetches next page live from API (no cache), appends to `InboxMessages` cache, re-renders with extended list; `_build_email_list` gains `next_cursor` param to show/hide the button

### Changed
- Accounts panel badge update: `interval:5s` (was `interval:30s`)

---

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
