"""Mail Client · Smart filters + folder preferences @chat.function handlers (SDK 5.2.0 / SDL).

Smart filters are virtual mailboxes stored locally in ctx.store.
Applying a filter runs a real-time search against the provider.
"""
from __future__ import annotations

import datetime
import logging

from app import chat
from imperal_sdk.chat.action_result import ActionResult
from handlers_inbox_impl import impl_search
from schemas import SearchResult
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
    """Resolve a filter by ID or by name. Returns (doc_id, doc_data) or (None, None).

    Accepts both the raw store ID and the human-readable filter name so the LLM
    can pass either — e.g. delete_filter(filter_id='WebHostMost Tickets') works
    even without calling list_filters() first.
    """
    uid = ctx.user.imperal_id
    # Try as direct store ID first
    if filter_id:
        try:
            doc = await ctx.store.get(FILTERS_COLLECTION, filter_id)
            if doc and doc.data.get("owner_id") == uid:
                return doc.id, doc.data
        except Exception:
            pass
    # Fall back to name lookup
    page = await ctx.store.query(FILTERS_COLLECTION, where={"owner_id": uid}, limit=20)
    for d in page.data:
        if d.data.get("name", "").lower() == filter_id.lower():
            return d.id, d.data
    return None, None


# ── Smart filters ─────────────────────────────────────────────────────────────

@chat.function("create_filter", action_type="write", event="filter.created",
               effects=["create:mail_filter"],
               data_model=MailFilter,
               description="Create a smart mailbox (virtual folder). Can filter by domain (from_contains='linkedin.com'), by exact emails (from_emails=['alice@x.com','bob@y.com']), by subject keyword, or any combination. After creating, use apply_filter to see matching emails.")
async def fn_create_filter(ctx, params: CreateFilterParams) -> ActionResult:
    """Create a named smart mailbox filter with search criteria."""
    try:
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        # Normalise specific emails list
        from_emails = [e.strip().lower() for e in (params.from_emails or []) if e.strip()]
        doc = await ctx.store.create(FILTERS_COLLECTION, {
            "owner_id": ctx.user.imperal_id,
            "name": params.name.strip()[:60],
            "criteria_from": params.from_contains.strip(),
            "criteria_from_emails": from_emails,
            "criteria_subject": params.subject_contains.strip(),
            "criteria_folder": params.folder.strip(),
            "color": params.color or "blue",
            "enabled": True,
            "created_at": now,
        })
        summary = f"Smart filter '{params.name}' created"
        if from_emails:
            summary += f" — watching: {', '.join(from_emails)}"
        return ActionResult.success(
            data=build_mail_filter(doc.id, doc.data),
            summary=summary + ". Use apply_filter to see matching emails.",
        )
    except Exception as e:
        return ActionResult.error(str(e), retryable=False)


@chat.function("list_filters", action_type="read",
               data_model=MailFilterPage,
               description="List all saved smart mailbox filters (virtual folders). Shows criteria for each. Use filter_id with apply_filter() to view matching emails.")
async def fn_list_filters(ctx, params: EmptyParams) -> ActionResult:
    """List all saved smart mailbox filters."""
    try:
        page = await ctx.store.query(FILTERS_COLLECTION,
                                     where={"owner_id": ctx.user.imperal_id}, limit=20)
        return ActionResult.success(
            data=build_mail_filter_page(page.data),
            summary=f"{len(page.data)} smart filter(s) saved.",
        )
    except Exception as e:
        return ActionResult.error(str(e), retryable=False)


@chat.function("apply_filter", action_type="read",
               data_model=SearchPage,
               id_projection="filter_id",
               description="Apply a smart filter and return matching emails. Pass filter_id OR filter name — both work. Optionally increase max_results (default 20, max 200) for deeper full-mailbox search.")
async def fn_apply_filter(ctx, params: FilterIdParam) -> ActionResult:
    """Apply a smart filter — runs live full-mailbox search with stored criteria."""
    try:
        doc_id, doc_data = await _resolve_filter(ctx, params.filter_id)
        if not doc_id:
            return ActionResult.error(
                f"Filter '{params.filter_id}' not found. Use list_filters() to see your filters.",
                retryable=False)

        from panels_filter_view import _build_filter_query
        query = _build_filter_query(doc_data) or doc_data.get("name", "")

        result = await impl_search(ctx, query=query, max_results=params.max_results)
        name = doc_data.get("name", "filter")
        return ActionResult.success(
            data=build_search_page(result),
            summary=f"Filter '{name}': {result.total} matching email(s).",
        )
    except Exception as e:
        return ActionResult.error(str(e), retryable=True)


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
        )
    except Exception as e:
        return ActionResult.error(str(e), retryable=False)


@chat.function("delete_filter", action_type="destructive", event="filter.deleted",
               effects=["delete:mail_filter"],
               data_model=RuleOpResult,
               id_projection="filter_id",
               description="Delete a smart filter. Pass filter_id OR filter name — both work. The emails are NOT deleted, only the filter definition.")
async def fn_delete_filter(ctx, params: FilterIdParam) -> ActionResult:
    """Delete a smart mailbox filter by ID or name."""
    try:
        doc_id, doc_data = await _resolve_filter(ctx, params.filter_id)
        if not doc_id:
            return ActionResult.error(
                f"Filter '{params.filter_id}' not found. Use list_filters() to see available filters.",
                retryable=False)
        name = doc_data.get("name", "filter")
        await ctx.store.delete(FILTERS_COLLECTION, doc_id)
        return ActionResult.success(
            data=build_rule_op(doc_id, f"Deleted filter '{name}'"),
            summary=f"Smart filter '{name}' deleted.",
        )
    except Exception as e:
        return ActionResult.error(str(e), retryable=False)


# ── Folder preferences ────────────────────────────────────────────────────────

@chat.function("set_folder_prefs", action_type="write", event="prefs.updated",
               effects=["update:mail_prefs"],
               data_model=MailPrefsResult,
               description="Choose which mail folders are shown in your inbox view. Pass an ordered list like ['INBOX','Starred','Work','Receipts']. Pass empty list to show all folders.")
async def fn_set_folder_prefs(ctx, params: SetFolderPrefsParams) -> ActionResult:
    """Set which mail folders are visible in the inbox panel."""
    try:
        uid = ctx.user.imperal_id
        existing = await ctx.store.query(PREFS_COLLECTION, where={"owner_id": uid}, limit=1)
        visible = [f.strip() for f in params.visible_folders if f.strip()]
        # all standard folders except those in visible list are "hidden"
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
        return ActionResult.error(str(e), retryable=False)


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
        return ActionResult.error(str(e), retryable=False)


@chat.function("list_mail_folders", action_type="read",
               data_model=MailFoldersResult,
               description="List all available mail folders (INBOX/sent/drafts/spam/trash/starred/archive) and show which are currently visible or hidden in the panel. Use when user asks 'what folders do I have', 'какие папки в почте', 'what sections are hidden'.")
async def fn_list_mail_folders(ctx, params: EmptyParams) -> ActionResult:
    """List available mail folders + current visibility preferences as SDL entity."""
    try:
        from panels_inbox import FOLDERS
        prefs_page = await ctx.store.query(PREFS_COLLECTION,
                                           where={"owner_id": ctx.user.imperal_id}, limit=1)
        hidden_keys: list[str] = []
        if prefs_page.data:
            hidden_keys = prefs_page.data[0].data.get("hidden_folders", [])
        all_keys = [f["key"] for f in FOLDERS]
        visible  = [k for k in all_keys if k not in hidden_keys]
        summary  = f"Visible: {', '.join(visible) or 'all'}"
        if hidden_keys:
            summary += f". Hidden: {', '.join(hidden_keys)}"
        return ActionResult.success(
            data=build_mail_folders(all_keys, visible, hidden_keys),
            summary=summary + ".",
        )
    except Exception as e:
        return ActionResult.error(str(e), retryable=False)
