"""Mail Client · Smart filters + folder preferences @chat.function handlers (SDK 5.2.0 / SDL).

Smart filters support both:
1. Native provider filters (e.g. Gmail users.settings.filters API) when supported.
2. Local smart virtual folders stored in ctx.store for custom searches across accounts.
"""
from __future__ import annotations

import datetime
import logging

from app import chat
from imperal_sdk.chat.action_result import ActionResult
from mail_providers.errors import mail_error_result
from handlers_inbox_impl import impl_search
from ctx_helpers import _get_acc
from mail_providers.helpers import _active_account
from schemas_params import (
    CreateFilterParams, UpdateFilterParams, FilterIdParam,
    SetFolderPrefsParams, EmptyParams,
)
from schemas_sdl_builders import SearchPage, build_search_page
from schemas_sdl_builders_rules import (
    MailFilter, MailFilterPage, RuleOpResult, MailPrefsResult, MailFoldersResult,
    build_mail_filter, build_mail_filter_page, build_rule_op, build_mail_prefs,
    build_mail_folders,
)

FILTERS_COLLECTION = "mail_filters"
PREFS_COLLECTION = "mail_prefs"

log = logging.getLogger("mail")


async def _resolve_filter(ctx, filter_id: str) -> tuple:
    """Resolve a filter by ID, name, or provider_filter_id.

    Returns (doc_id, doc_data) or (None, None).
    """
    uid = ctx.user.imperal_id
    fid = (filter_id or "").strip()
    if not fid:
        return None, None

    # 1. Try as direct store ID
    try:
        doc = await ctx.store.get(FILTERS_COLLECTION, fid)
        if doc and doc.data.get("owner_id") == uid:
            return doc.id, doc.data
    except Exception:
        pass

    # 2. Query all filters for user and match by name or provider_filter_id or id
    try:
        page = await ctx.store.query(FILTERS_COLLECTION, where={"owner_id": uid}, limit=100)
        for d in page.data:
            if d.id == fid:
                return d.id, d.data
            if (d.data.get("name") or "").lower() == fid.lower():
                return d.id, d.data
            if d.data.get("provider_filter_id") == fid:
                return d.id, d.data
    except Exception as e:
        log.warning("_resolve_filter store query error: %s", e)

    return None, None


# ── Smart filters ─────────────────────────────────────────────────────────────

@chat.function("create_filter", action_type="write", event="filter.created",
               effects=["create:mail_filter"],
               data_model=MailFilter,
               description="Create a smart mailbox (virtual folder). Can filter by domain (from_contains='linkedin.com'), by exact emails (from_emails=['alice@x.com','bob@y.com']), by subject keyword, or any combination. After creating, use apply_filter to see matching emails.")
async def fn_create_filter(ctx, params: CreateFilterParams) -> ActionResult:
    """Create a named smart mailbox filter with search criteria, synced to provider if supported."""
    try:
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        acc, provider = await _get_acc(ctx, params.account)
        account_email = acc.get("email", "") if acc else ""

        from_emails = [e.strip().lower() for e in (params.from_emails or []) if e.strip()]
        name_norm = params.name.strip().lower()

        # Idempotency check in store
        existing = await ctx.store.query(
            FILTERS_COLLECTION,
            where={"owner_id": ctx.user.imperal_id},
            limit=50
        )
        for d in existing.data:
            if (d.data.get("name", "").strip().lower() == name_norm and
                    (d.data.get("account_email", "") or "") == account_email):
                return ActionResult.success(
                    data=build_mail_filter(d.id, d.data),
                    summary=f"Smart filter '{d.data.get('name')}' already exists — reusing it.",
                )

        provider_filter_id = ""
        # If provider supports native filters (e.g. Gmail), create native filter
        if provider and hasattr(provider, "create_filter"):
            crit: dict = {}
            if from_emails:
                crit["from"] = " OR ".join(from_emails) if len(from_emails) > 1 else from_emails[0]
            elif params.from_contains:
                crit["from"] = params.from_contains.strip()

            if params.subject_contains:
                crit["subject"] = params.subject_contains.strip()

            action: dict = {}
            # In Gmail API, a filter requires at least one action
            # Default action: apply label matching filter name or removeLabelIds: []
            if hasattr(provider, "create_folder") and acc:
                try:
                    folder_res = await provider.create_folder(ctx, acc, params.name.strip()[:60])
                    label_id = folder_res.get("id") or folder_res.get("folder_id")
                    if label_id:
                        action["addLabelIds"] = [label_id]
                except Exception as ex:
                    log.debug("create_filter: label auto-create skipped: %s", ex)

            if not action:
                # If no label created, remove SPAM label (Never send to Spam - safe standard Gmail filter action)
                action = {"removeLabelIds": ["SPAM"]}

            if crit:
                native_res = await provider.create_filter(ctx, acc, criteria=crit, action=action)
                if native_res.get("RESULT") == "SUCCESS":
                    provider_filter_id = native_res.get("filter_id", "")

        doc_data = {
            "owner_id": ctx.user.imperal_id,
            "account_email": account_email,
            "name": params.name.strip()[:60],
            "criteria_from": params.from_contains.strip(),
            "criteria_from_emails": from_emails,
            "criteria_subject": params.subject_contains.strip(),
            "criteria_folder": params.folder.strip(),
            "color": params.color or "blue",
            "enabled": True,
            "created_at": now,
            "provider_filter_id": provider_filter_id,
        }
        doc = await ctx.store.create(FILTERS_COLLECTION, doc_data)

        summary = f"Smart filter '{params.name}' created"
        if from_emails:
            summary += f" — watching: {', '.join(from_emails)}"
        if provider_filter_id:
            summary += " (synced to Gmail)"
        return ActionResult.success(
            data=build_mail_filter(doc.id, doc_data),
            summary=summary + ".",
            refresh_panels=["inbox"],
        )
    except Exception as e:
        return mail_error_result(e, retryable=False)


@chat.function("list_filters", action_type="read",
               data_model=MailFilterPage,
               description="List all saved smart mailbox filters and native Gmail filters. Shows criteria for each. Use filter_id with apply_filter() to view matching emails.")
async def fn_list_filters(ctx, params: EmptyParams) -> ActionResult:
    """List smart mailbox filters and synced native provider filters."""
    try:
        acc, provider = await _get_acc(ctx, "")
        active_email = acc.get("email", "") if acc else ""

        # 1. Fetch store filters
        page = await ctx.store.query(
            FILTERS_COLLECTION,
            where={"owner_id": ctx.user.imperal_id},
            limit=50
        )
        stored_filters = [
            d for d in page.data
            if not d.data.get("account_email") or d.data.get("account_email") == active_email
        ]

        stored_provider_ids = {
            d.data.get("provider_filter_id")
            for d in stored_filters
            if d.data.get("provider_filter_id")
        }

        # 2. Fetch native provider filters if supported (e.g. Gmail)
        if provider and hasattr(provider, "list_filters") and acc:
            try:
                native_filters = await provider.list_filters(ctx, acc)
                now = datetime.datetime.now(datetime.timezone.utc).isoformat()
                for nf in native_filters:
                    nf_id = nf.get("id")
                    if nf_id and nf_id not in stored_provider_ids:
                        # Auto-sync native filter to store so it appears seamlessly in UI & SDL
                        new_doc_data = {
                            "owner_id": ctx.user.imperal_id,
                            "account_email": active_email,
                            "name": nf.get("name") or f"Gmail Filter {nf_id[:8]}",
                            "criteria_from": nf.get("criteria_from", ""),
                            "criteria_from_emails": [],
                            "criteria_subject": nf.get("criteria_subject", ""),
                            "criteria_folder": "",
                            "criteria_to": nf.get("criteria_to", ""),
                            "criteria_query": nf.get("criteria_query", ""),
                            "color": "blue",
                            "enabled": True,
                            "created_at": now,
                            "provider_filter_id": nf_id,
                        }
                        created_doc = await ctx.store.create(FILTERS_COLLECTION, new_doc_data)
                        stored_filters.append(created_doc)
                        stored_provider_ids.add(nf_id)
            except Exception as ex:
                log.warning("fn_list_filters: provider.list_filters error: %s", ex)

        return ActionResult.success(
            data=build_mail_filter_page(stored_filters),
            summary=f"{len(stored_filters)} filter(s) for {active_email or 'all accounts'}.",
        )
    except Exception as e:
        return mail_error_result(e, retryable=False)


@chat.function("apply_filter", action_type="read",
               data_model=SearchPage,
               id_projection="filter_id",
               description="Apply a smart filter and return matching emails. Pass filter_id OR filter name — both work. Optionally increase max_results (default 20, max 200) for deeper full-mailbox search.")
async def fn_apply_filter(ctx, params: FilterIdParam) -> ActionResult:
    """Apply a smart filter — runs live search with stored criteria."""
    try:
        doc_id, doc_data = await _resolve_filter(ctx, params.filter_id)
        if not doc_id:
            return ActionResult.error(
                f"Filter '{params.filter_id}' not found. Use list_filters() to see your filters.",
                retryable=False
            )

        from panels_filter_view import _build_filter_query
        query = _build_filter_query(doc_data) or doc_data.get("name", "")
        search_account = doc_data.get("account_email", "")

        result = await impl_search(
            ctx,
            query=query,
            max_results=params.max_results,
            account=search_account
        )
        name = doc_data.get("name", "filter")
        return ActionResult.success(
            data=build_search_page(result),
            summary=f"Filter '{name}': {result.total} matching email(s).",
        )
    except Exception as e:
        return mail_error_result(e, retryable=True)


@chat.function("update_filter", action_type="write", event="filter.updated",
               effects=["update:mail_filter"],
               data_model=MailFilter,
               id_projection="filter_id",
               description="Update a smart filter — rename it or change its search criteria. Pass filter_id OR filter name — both work.")
async def fn_update_filter(ctx, params: UpdateFilterParams) -> ActionResult:
    """Update a smart filter's name or criteria."""
    try:
        doc_id, doc_data = await _resolve_filter(ctx, params.filter_id)
        if not doc_id:
            return ActionResult.error(f"Filter '{params.filter_id}' not found.", retryable=False)

        patch = dict(doc_data)
        if params.name:
            patch["name"] = params.name.strip()[:60]
        if params.from_contains != "__keep__":
            patch["criteria_from"] = params.from_contains.strip()
        if params.subject_contains != "__keep__":
            patch["criteria_subject"] = params.subject_contains.strip()
        if params.color:
            patch["color"] = params.color

        updated = await ctx.store.update(FILTERS_COLLECTION, doc_id, patch)
        return ActionResult.success(
            data=build_mail_filter(doc_id, updated.data),
            summary=f"Filter '{updated.data['name']}' updated.",
            refresh_panels=["inbox"],
        )
    except Exception as e:
        return mail_error_result(e, retryable=False)


@chat.function("delete_filter", action_type="destructive", event="filter.deleted",
               effects=["delete:mail_filter"],
               data_model=RuleOpResult,
               id_projection="filter_id",
               description="Delete a smart filter. Pass filter_id OR filter name — both work. The emails are NOT deleted, only the filter definition.")
async def fn_delete_filter(ctx, params: FilterIdParam) -> ActionResult:
    """Delete a smart mailbox filter by ID or name (and remove from provider if synced)."""
    try:
        doc_id, doc_data = await _resolve_filter(ctx, params.filter_id)
        if not doc_id:
            return ActionResult.error(
                f"Filter '{params.filter_id}' not found. Use list_filters() to see available filters.",
                retryable=False
            )

        name = doc_data.get("name", "filter")
        provider_filter_id = doc_data.get("provider_filter_id", "")
        account_email = doc_data.get("account_email", "")

        # If synced with provider (e.g. Gmail), delete from provider
        if provider_filter_id:
            acc, provider = await _get_acc(ctx, account_email)
            if provider and hasattr(provider, "delete_filter") and acc:
                try:
                    await provider.delete_filter(ctx, acc, provider_filter_id)
                except Exception as ex:
                    log.warning("delete_filter: provider deletion error: %s", ex)

        await ctx.store.delete(FILTERS_COLLECTION, doc_id)
        return ActionResult.success(
            data=build_rule_op(doc_id, f"Deleted filter '{name}'"),
            summary=f"Smart filter '{name}' deleted.",
            refresh_panels=["inbox"],
        )
    except Exception as e:
        return mail_error_result(e, retryable=False)


# ── Folder preferences ────────────────────────────────────────────────────────

@chat.function("set_folder_prefs", action_type="write", event="prefs.updated",
               effects=["update:mail_prefs"],
               data_model=MailPrefsResult,
               description="Set which mail folders are shown in the inbox view. WARNING: this REPLACES the entire visible set — it does NOT add to it. When the user asks to ADD a folder (e.g. 'add starred'), you MUST first call get_folder_prefs to read the current visible folders, then pass the existing list PLUS the new one. Always include 'INBOX' unless the user explicitly asks to hide it. Pass an ordered list like ['INBOX','starred','sent']. Pass an empty list to reset to showing ALL folders. TRIGGERS (this is about PANEL VISIBILITY, NOT listing emails — do NOT call inbox()/folder() for these): 'show/display these folders in the panel', 'add starred to my folders/panel', 'hide trash from the panel'.")
async def fn_set_folder_prefs(ctx, params: SetFolderPrefsParams) -> ActionResult:
    """Set which mail folders are visible in the inbox panel."""
    try:
        uid = ctx.user.imperal_id
        existing = await ctx.store.query(PREFS_COLLECTION, where={"owner_id": uid}, limit=1)
        visible = [f.strip() for f in params.visible_folders if f.strip()]
        _curr_acc = await _active_account(ctx, "")
        _ptype = _curr_acc.get("provider", "oauth") if _curr_acc else "oauth"
        from panels_inbox import _ALLMAIL_PROVIDERS
        if _ptype in _ALLMAIL_PROVIDERS:
            all_folders = ["INBOX", "sent", "drafts", "spam", "trash", "starred", "all_mail"]
        else:
            all_folders = ["INBOX", "sent", "drafts", "spam", "trash", "starred", "archive"]
        hidden = [f for f in all_folders if f not in visible] if visible else []
        doc_data = {"owner_id": uid, "visible_folders": visible, "hidden_folders": hidden}
        if existing.data:
            await ctx.store.update(PREFS_COLLECTION, existing.data[0].id, doc_data)
        else:
            await ctx.store.create(PREFS_COLLECTION, doc_data)
        summary = (f"Showing folders: {', '.join(visible)}."
                   if visible else "Showing all folders.")
        return ActionResult.success(
            data=build_mail_prefs(visible, hidden),
            summary=summary,
            refresh_panels=["inbox"],
        )
    except Exception as e:
        return mail_error_result(e, retryable=False)


@chat.function("get_folder_prefs", action_type="read",
               data_model=MailPrefsResult,
               description="Show current folder visibility settings — which folders are visible and which are hidden in your inbox view.")
async def fn_get_folder_prefs(ctx, params: EmptyParams) -> ActionResult:
    """Get current folder visibility preferences."""
    try:
        uid = ctx.user.imperal_id
        page = await ctx.store.query(PREFS_COLLECTION, where={"owner_id": uid}, limit=1)
        if not page.data:
            return ActionResult.success(
                data=build_mail_prefs([], []),
                summary="No folder preferences set — all folders visible.",
            )
        d = page.data[0].data
        return ActionResult.success(
            data=build_mail_prefs(d.get("visible_folders", []), d.get("hidden_folders", [])),
            summary=f"Visible: {', '.join(d.get('visible_folders', []) or ['all'])}.",
        )
    except Exception as e:
        return mail_error_result(e, retryable=False)


@chat.function("list_mail_folders", action_type="read",
               data_model=MailFoldersResult,
               description=(
                   "List all available mail folders and custom labels, showing which are visible "
                   "or hidden in the panel. Gmail shows 'All Mail' instead of 'Archive' (Gmail has "
                   "no system Archive folder). Custom folders created via create_mail_folder() also "
                   "appear here. Use when user asks 'what folders do I have'."
               ))
async def fn_list_mail_folders(ctx, params: EmptyParams) -> ActionResult:
    """List available mail folders + custom labels + current visibility preferences."""
    try:
        from panels_inbox import FOLDERS, _ALLMAIL_PROVIDERS
        acc = await _active_account(ctx, "")
        ptype = acc.get("provider", "oauth") if acc else "oauth"
        is_allmail = ptype in _ALLMAIL_PROVIDERS

        prefs_page = await ctx.store.query(PREFS_COLLECTION,
                                           where={"owner_id": ctx.user.imperal_id}, limit=1)
        hidden_keys: list[str] = []
        custom_folders: list[str] = []
        if prefs_page.data:
            d = prefs_page.data[0].data
            hidden_keys = d.get("hidden_folders") or []
            custom_folders = d.get("custom_folders") or []

        all_keys = [
            f["key"] for f in FOLDERS
            if not (f["key"] == "archive" and is_allmail)
            and not (f["key"] == "all_mail" and not is_allmail)
        ] + custom_folders

        visible = [k for k in all_keys if k not in hidden_keys]
        summary = f"Visible: {', '.join(visible) or 'all'}"
        if hidden_keys:
            summary += f". Hidden: {', '.join(hidden_keys)}"
        if custom_folders:
            summary += f". Custom: {', '.join(custom_folders)}"
        return ActionResult.success(
            data=build_mail_folders(all_keys, visible, hidden_keys),
            summary=summary + ".",
        )
    except Exception as e:
        return mail_error_result(e, retryable=False)
