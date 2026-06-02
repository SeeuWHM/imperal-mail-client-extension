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
    MailFilter, MailFilterPage, RuleOpResult, MailPrefsResult,
    build_mail_filter, build_mail_filter_page, build_rule_op, build_mail_prefs,
)

FILTERS_COLLECTION = "mail_filters"
PREFS_COLLECTION = "mail_prefs"

log = logging.getLogger("mail")


# ── Smart filters ─────────────────────────────────────────────────────────────

@chat.function("create_filter", action_type="write", event="filter.created",
               effects=["create:mail_filter"],
               data_model=MailFilter,
               description="Create a smart mailbox (virtual folder) — define search criteria once, apply anytime. Examples: 'LinkedIn emails', 'receipts from shop.com', 'emails about invoices'. After creating, use apply_filter(filter_id) to see matching emails.")
async def fn_create_filter(ctx, params: CreateFilterParams) -> ActionResult:
    """Create a named smart mailbox filter with search criteria."""
    try:
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        doc = await ctx.store.create(FILTERS_COLLECTION, {
            "owner_id": ctx.user.imperal_id,
            "name": params.name.strip()[:60],
            "criteria_from": params.from_contains.strip(),
            "criteria_subject": params.subject_contains.strip(),
            "criteria_folder": params.folder.strip(),
            "color": params.color or "blue",
            "enabled": True,
            "created_at": now,
        })
        return ActionResult.success(
            data=build_mail_filter(doc.id, doc.data),
            summary=f"Smart filter '{params.name}' created — use apply_filter to see matching emails.",
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
               description="Apply a smart filter and return matching emails. Runs a live search against the provider using the filter's criteria. Pass filter_id from list_filters(). Optionally increase max_results for deeper search.")
async def fn_apply_filter(ctx, params: FilterIdParam) -> ActionResult:
    """Apply a smart filter — runs live search with stored criteria, returns matching emails."""
    try:
        doc = await ctx.store.get(FILTERS_COLLECTION, params.filter_id)
        if not doc or doc.data.get("owner_id") != ctx.user.imperal_id:
            return ActionResult.error("Filter not found. Use list_filters() to see your filters.", retryable=False)

        parts = []
        if doc.data.get("criteria_from"):
            parts.append(f"from:{doc.data['criteria_from']}")
        if doc.data.get("criteria_subject"):
            parts.append(f"subject:{doc.data['criteria_subject']}")
        query = " ".join(parts) if parts else doc.data.get("name", "")

        result = await impl_search(ctx, query=query, max_results=params.max_results)
        name = doc.data.get("name", "filter")
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
               description="Update a smart filter — rename it or change its search criteria. Use list_filters() to get filter_id.")
async def fn_update_filter(ctx, params: UpdateFilterParams) -> ActionResult:
    """Update a smart filter's name or criteria."""
    try:
        doc = await ctx.store.get(FILTERS_COLLECTION, params.filter_id)
        if not doc or doc.data.get("owner_id") != ctx.user.imperal_id:
            return ActionResult.error("Filter not found.", retryable=False)
        patch = dict(doc.data)
        if params.name:
            patch["name"] = params.name.strip()[:60]
        if params.from_contains != "__keep__":
            patch["criteria_from"] = params.from_contains.strip()
        if params.subject_contains != "__keep__":
            patch["criteria_subject"] = params.subject_contains.strip()
        if params.color:
            patch["color"] = params.color
        updated = await ctx.store.update(FILTERS_COLLECTION, params.filter_id, patch)
        return ActionResult.success(
            data=build_mail_filter(params.filter_id, updated.data),
            summary=f"Filter '{updated.data['name']}' updated.",
        )
    except Exception as e:
        return ActionResult.error(str(e), retryable=False)


@chat.function("delete_filter", action_type="destructive", event="filter.deleted",
               effects=["delete:mail_filter"],
               data_model=RuleOpResult,
               id_projection="filter_id",
               description="Permanently delete a smart filter. The emails themselves are not affected — only the filter definition is removed.")
async def fn_delete_filter(ctx, params: FilterIdParam) -> ActionResult:
    """Delete a smart mailbox filter."""
    try:
        doc = await ctx.store.get(FILTERS_COLLECTION, params.filter_id)
        if not doc or doc.data.get("owner_id") != ctx.user.imperal_id:
            return ActionResult.error("Filter not found.", retryable=False)
        name = doc.data.get("name", "filter")
        await ctx.store.delete(FILTERS_COLLECTION, params.filter_id)
        return ActionResult.success(
            data=build_rule_op(params.filter_id, f"Deleted filter '{name}'"),
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
