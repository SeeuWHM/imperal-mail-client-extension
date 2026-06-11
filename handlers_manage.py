"""Mail Client — unified action @chat.function handlers (SDK 5.2.0 / SDL).

Each function accepts EITHER message_ids (specific emails) OR query (all matching).
- message_ids: single ID or comma-separated list → single or bulk op.
- query: search expression → iterates until all matching emails are processed.
"""
from __future__ import annotations

from app import chat
from imperal_sdk.chat.action_result import ActionResult

from handlers_manage_impl import (
    impl_archive, impl_delete, impl_mark_read, impl_mark_unread, impl_star,
    impl_move, impl_purge,
    impl_bulk_archive, impl_bulk_delete, impl_bulk_mark_read, impl_bulk_mark_unread,
    impl_bulk_move, impl_bulk_star, impl_bulk_purge,
    impl_mark_all_matching,
    _get_acc, _batch_direct,
)
from handlers_cleanup_impl import impl_inbox_cleanup, impl_unsubscribe_from_query
from schemas import BulkOperationResult
from schemas_params import (
    ArchiveParams, DeleteParams, MarkReadParams, StarUnifiedParams,
    MoveUnifiedParams, PurgeUnifiedParams, ApplyActionsParams, InboxCleanupParams,
)
from schemas_sdl_builders import BulkMailOpResult, build_bulk_mail_op


def _ids(s: str) -> list[str]:
    return [i.strip() for i in s.split(",") if i.strip()]


def _single_to_bulk(ok: bool, operation: str) -> BulkOperationResult:
    """Wrap a single-message result into BulkOperationResult for uniform data_model."""
    n = 1 if ok else 0
    field_map = {
        "archive": "archived", "delete": "deleted", "purge": "purged",
        "mark_read": "marked_read", "read": "marked_read",
        "mark_unread": "marked_unread", "unread": "marked_unread",
        "star": "starred", "unstar": "unstarred", "move": "moved",
    }
    kwargs: dict = {"operation": operation, "succeeded": n, "total": 1}
    field = field_map.get(operation)
    if field:
        kwargs[field] = n
    return BulkOperationResult(**kwargs)


# ── archive ───────────────────────────────────────────────────────────────────

@chat.function("archive", action_type="write", event="archived",
               effects=["update:email"],
               data_model=BulkMailOpResult,
               description=(
                   "Archive emails — removes from INBOX, stays recoverable (Gmail: All Mail; "
                   "Outlook: Archive folder; IMAP: moves to Archive). "
                   "Single email: message_ids='<id>'. "
                   "Multiple emails: message_ids='id1,id2,id3'. "
                   "ALL matching a pattern: query='from:linkedin' — iterates until none remain. "
                   "Provide message_ids OR query, not both."
               ))
async def fn_archive(ctx, params: ArchiveParams) -> ActionResult:
    try:
        if params.message_ids:
            ids = _ids(params.message_ids)
            if len(ids) == 1:
                r = await impl_archive(ctx, message_id=ids[0], account=params.account)
                result = _single_to_bulk(r.ok, "archive")
                summary = "Archived 1 email."
            else:
                result = await impl_bulk_archive(ctx, params.message_ids, account=params.account)
                summary = f"Archived {result.succeeded} email(s)."
        elif params.query:
            result = await impl_mark_all_matching(ctx, params.query, "archive", params.account)
            summary = f"Archived {result.succeeded} email(s) matching '{params.query}'."
        else:
            return ActionResult.error("Provide message_ids or query.", retryable=False)
        return ActionResult.success(data=build_bulk_mail_op(result), summary=summary,
                                    refresh_panels=["inbox"])
    except Exception as e:
        return ActionResult.error(str(e), retryable=True)


# ── delete ────────────────────────────────────────────────────────────────────

@chat.function("delete", action_type="write", event="deleted",
               effects=["update:email"],
               data_model=BulkMailOpResult,
               description=(
                   "Move emails to Trash — RECOVERABLE (Gmail: 30 days; Outlook: until emptied). "
                   "Single: message_ids='<id>'. Multiple: message_ids='id1,id2'. "
                   "ALL matching: query='from:newsletter' — iterates until none remain. "
                   "Use purge() for permanent deletion. Provide message_ids OR query."
               ))
async def fn_delete(ctx, params: DeleteParams) -> ActionResult:
    try:
        if params.message_ids:
            ids = _ids(params.message_ids)
            if len(ids) == 1:
                r = await impl_delete(ctx, message_id=ids[0], account=params.account)
                result = _single_to_bulk(r.ok, "delete")
                summary = "Moved 1 email to Trash."
            else:
                result = await impl_bulk_delete(ctx, params.message_ids, account=params.account)
                summary = f"Moved {result.succeeded} email(s) to Trash."
        elif params.query:
            result = await impl_mark_all_matching(ctx, params.query, "delete", params.account)
            summary = f"Moved {result.succeeded} email(s) to Trash (query: '{params.query}')."
        else:
            return ActionResult.error("Provide message_ids or query.", retryable=False)
        return ActionResult.success(data=build_bulk_mail_op(result), summary=summary,
                                    refresh_panels=["inbox"])
    except Exception as e:
        return ActionResult.error(str(e), retryable=True)


# ── mark_read ─────────────────────────────────────────────────────────────────

@chat.function("mark_read", action_type="write", event="marked_read",
               effects=["update:email"],
               data_model=BulkMailOpResult,
               description=(
                   "Mark emails as read (read=true, default) or unread (read=false). "
                   "Single: message_ids='<id>'. Multiple: message_ids='id1,id2'. "
                   "ALL matching: query='from:linkedin' — processes until none remain. "
                   "Provide message_ids OR query."
               ))
async def fn_mark_read(ctx, params: MarkReadParams) -> ActionResult:
    op = "read" if params.read else "unread"
    label = "read" if params.read else "unread"
    try:
        if params.message_ids:
            ids = _ids(params.message_ids)
            if len(ids) == 1:
                r = (await impl_mark_read(ctx, message_id=ids[0], account=params.account)
                     if params.read else
                     await impl_mark_unread(ctx, message_id=ids[0], account=params.account))
                result = _single_to_bulk(r.ok, op)
                summary = f"Marked 1 email as {label}."
            else:
                result = (await impl_bulk_mark_read(ctx, params.message_ids, account=params.account)
                          if params.read else
                          await impl_bulk_mark_unread(ctx, params.message_ids, account=params.account))
                summary = f"Marked {result.succeeded} email(s) as {label}."
        elif params.query:
            result = await impl_mark_all_matching(ctx, params.query, op, params.account)
            summary = f"Marked {result.succeeded} email(s) as {label} (query: '{params.query}')."
        else:
            return ActionResult.error("Provide message_ids or query.", retryable=False)
        return ActionResult.success(data=build_bulk_mail_op(result), summary=summary,
                                    refresh_panels=["inbox"])
    except Exception as e:
        return ActionResult.error(str(e), retryable=True)


# ── star ──────────────────────────────────────────────────────────────────────

@chat.function("star", action_type="write", event="starred",
               effects=["update:email"],
               data_model=BulkMailOpResult,
               description=(
                   "Star (starred=true, default) or unstar (starred=false) emails. "
                   "Single: message_ids='<id>'. Multiple: message_ids='id1,id2'. "
                   "ALL matching: query='from:boss@company.com'. "
                   "Provide message_ids OR query."
               ))
async def fn_star(ctx, params: StarUnifiedParams) -> ActionResult:
    op = "star" if params.starred else "unstar"
    label = "Starred" if params.starred else "Unstarred"
    try:
        if params.message_ids:
            ids = _ids(params.message_ids)
            if len(ids) == 1:
                r = await impl_star(ctx, message_id=ids[0], starred=params.starred,
                                    account=params.account)
                result = _single_to_bulk(r.ok, op)
                summary = f"{label} 1 email."
            else:
                result = await impl_bulk_star(ctx, params.message_ids, starred=params.starred,
                                              account=params.account)
                summary = f"{label} {result.succeeded} email(s)."
        elif params.query:
            result = await impl_mark_all_matching(ctx, params.query, op, params.account)
            summary = f"{label} {result.succeeded} email(s) (query: '{params.query}')."
        else:
            return ActionResult.error("Provide message_ids or query.", retryable=False)
        return ActionResult.success(data=build_bulk_mail_op(result), summary=summary,
                                    refresh_panels=["inbox"])
    except Exception as e:
        return ActionResult.error(str(e), retryable=True)


# ── move ──────────────────────────────────────────────────────────────────────

@chat.function("move", action_type="write", event="moved",
               effects=["update:email"],
               data_model=BulkMailOpResult,
               description=(
                   "Move emails to a folder. to_folder is required. "
                   "Single: message_ids='<id>'. Multiple: message_ids='id1,id2'. "
                   "ALL matching: query='from:linkedin' — moves all until none remain. "
                   "Examples: move to 'spam', 'INBOX', 'Archive', 'trash', or a custom label. "
                   "Provide message_ids OR query."
               ))
async def fn_move(ctx, params: MoveUnifiedParams) -> ActionResult:
    try:
        if params.message_ids:
            ids = _ids(params.message_ids)
            if len(ids) == 1:
                r = await impl_move(ctx, message_id=ids[0], from_folder=params.from_folder,
                                    to_folder=params.to_folder, account=params.account)
                result = _single_to_bulk(r.ok, "move")
                summary = f"Moved 1 email to {params.to_folder}."
            else:
                result = await impl_bulk_move(ctx, params.message_ids,
                                              from_folder=params.from_folder,
                                              to_folder=params.to_folder,
                                              account=params.account)
                summary = f"Moved {result.succeeded} email(s) to {params.to_folder}."
        elif params.query:
            result = await impl_mark_all_matching(ctx, params.query, "move", params.account,
                                                  to_folder=params.to_folder)
            summary = f"Moved {result.succeeded} email(s) to {params.to_folder}."
        else:
            return ActionResult.error("Provide message_ids or query.", retryable=False)
        return ActionResult.success(data=build_bulk_mail_op(result), summary=summary,
                                    refresh_panels=["inbox"])
    except Exception as e:
        return ActionResult.error(str(e), retryable=True)


# ── apply_actions ─────────────────────────────────────────────────────────────

@chat.function("apply_actions", action_type="write", event="bulk_marked_read",
               effects=["update:email"],
               data_model=BulkMailOpResult,
               description=(
                   "Apply MULTIPLE operations to the SAME emails in one efficient call. "
                   "Use when combining actions on same set: ['read','archive'], ['unsubscribe','archive','read']. "
                   "Gmail: label ops combined into ONE batchModify. "
                   "Allowed: 'archive', 'read', 'unread', 'star', 'unstar', 'delete', 'unsubscribe'. "
                   "'unsubscribe': reads List-Unsubscribe header from most recent matching email and calls it. "
                   "ALL matching: query='from:neil patel'. Single: message_ids='<id>'. "
                   "For single-operation use archive/delete/mark_read/star directly."
               ))
async def fn_apply_actions(ctx, params: ApplyActionsParams) -> ActionResult:
    allowed = {"archive", "read", "unread", "star", "unstar", "delete", "unsubscribe"}
    bad = [o for o in params.operations if o not in allowed]
    if bad:
        return ActionResult.error(
            f"Invalid operation(s): {bad}. Allowed: {sorted(allowed)}", retryable=False
        )
    if not params.operations:
        return ActionResult.error("operations list is empty.", retryable=False)

    # Unsubscribe is handled separately — it's a one-shot HTTP call, not a batch label op.
    unsub_note = ""
    core_ops = [o for o in params.operations if o != "unsubscribe"]

    ops_str = ",".join(core_ops) if core_ops else ""
    try:
        # Handle unsubscribe first if requested
        if "unsubscribe" in params.operations:
            unsub_query = params.query
            if not unsub_query and params.message_ids:
                ids_u = _ids(params.message_ids)
                unsub_query = f"rfc822msgid:{ids_u[0]}" if ids_u else ""
            unsub_result: dict = {"success": False, "note": "No query provided."}
            if unsub_query:
                unsub_result = await impl_unsubscribe_from_query(ctx, unsub_query,
                                                                  params.account)
            unsub_note = unsub_result.get("note", "")
            if not core_ops:
                n = 1 if unsub_result.get("success") else 0
                return ActionResult.success(
                    data=build_bulk_mail_op(BulkOperationResult(operation="unsubscribe",
                                                                 succeeded=n, total=1)),
                    summary=unsub_note or "Unsubscribe attempted.",
                    refresh_panels=["inbox"],
                )

        if params.message_ids:
            ids = _ids(params.message_ids)
            ids_str = ",".join(ids)
            acc, provider = await _get_acc(ctx, params.account)
            # Gmail: _batch_direct combines into ONE batchModify call
            r = await _batch_direct(provider, ctx, acc, ids, ops_str)
            if r.get("RESULT") == "SUCCESS":
                n = r.get("succeeded", len(ids))
                result = BulkOperationResult(operation=ops_str, succeeded=n, total=len(ids))
            else:
                # Slow path (IMAP/MS): apply each operation sequentially
                last = BulkOperationResult(operation=ops_str, succeeded=0, total=len(ids))
                for op in params.operations:
                    if op == "read":
                        last = await impl_bulk_mark_read(ctx, ids_str, account=params.account)
                    elif op == "unread":
                        last = await impl_bulk_mark_unread(ctx, ids_str, account=params.account)
                    elif op == "archive":
                        last = await impl_bulk_archive(ctx, ids_str, account=params.account)
                    elif op == "delete":
                        last = await impl_bulk_delete(ctx, ids_str, account=params.account)
                    elif op in ("star", "unstar"):
                        last = await impl_bulk_star(ctx, ids_str, starred=(op == "star"),
                                                    account=params.account)
                result = BulkOperationResult(operation=ops_str, succeeded=last.succeeded,
                                             total=len(ids))
            prefix = f"{unsub_note} " if unsub_note else ""
            summary = f"{prefix}Applied {core_ops} to {result.succeeded} email(s)."
        elif params.query:
            result = await impl_mark_all_matching(ctx, params.query, ops_str, params.account)
            prefix = f"{unsub_note} " if unsub_note else ""
            summary = (f"{prefix}Applied {core_ops} to {result.succeeded} email(s) "
                       f"(query: '{params.query}').")
        else:
            return ActionResult.error("Provide message_ids or query.", retryable=False)
        return ActionResult.success(data=build_bulk_mail_op(result), summary=summary,
                                    refresh_panels=["inbox"])
    except Exception as e:
        return ActionResult.error(str(e), retryable=True)


# ── inbox_cleanup ─────────────────────────────────────────────────────────────

@chat.function("inbox_cleanup", action_type="write", event="bulk_archived",
               effects=["update:email"],
               data_model=BulkMailOpResult,
               description=(
                   "Bulk cleanup by category or sender — no need to know the exact query. "
                   "categories: 'promotions', 'social', 'newsletters', 'outreach', 'updates', 'forums', 'spam'. "
                   "Gmail maps to native category: labels; Outlook/IMAP use pattern matching. "
                   "Use when user says 'clean up obvious outreach', 'archive all promotions', "
                   "'delete my newsletters', 'unsubscribe from this sender'. "
                   "from_senders=['neil patel'] for specific senders. "
                   "operation: 'archive' (default), 'delete', 'read', 'star', "
                   "'unsubscribe' (find List-Unsubscribe header and call it)."
               ))
async def fn_inbox_cleanup(ctx, params: InboxCleanupParams) -> ActionResult:
    try:
        if params.operation == "unsubscribe":
            from handlers_cleanup_impl import impl_unsubscribe_from_query, _build_cleanup_query
            query = await _build_cleanup_query(ctx, params.categories, params.from_senders,
                                               params.older_than_days, params.account)
            result_dict = await impl_unsubscribe_from_query(ctx, query, params.account)
            n = 1 if result_dict.get("success") else 0
            bulk = BulkOperationResult(operation="unsubscribe", succeeded=n, total=1)
            return ActionResult.success(
                data=build_bulk_mail_op(bulk),
                summary=result_dict.get("note", "Unsubscribe attempted."),
                refresh_panels=["inbox"],
            )

        result = await impl_inbox_cleanup(
            ctx,
            categories=params.categories,
            from_senders=params.from_senders,
            older_than_days=params.older_than_days,
            operation=params.operation,
            account=params.account,
        )
        op_label = {"archive": "archived", "delete": "moved to Trash",
                    "read": "marked as read", "star": "starred"}.get(params.operation,
                                                                      params.operation)
        return ActionResult.success(
            data=build_bulk_mail_op(result),
            summary=f"{result.succeeded} email(s) {op_label}.",
            refresh_panels=["inbox"],
        )
    except ValueError as e:
        return ActionResult.error(str(e), retryable=False)
    except Exception as e:
        return ActionResult.error(str(e), retryable=True)


# ── purge ─────────────────────────────────────────────────────────────────────

@chat.function("purge", action_type="destructive", event="purged",
               effects=["delete:email"],
               data_model=BulkMailOpResult,
               description=(
                   "PERMANENTLY delete emails — cannot be recovered from Trash or anywhere. "
                   "Single: message_ids='<id>'. Multiple: message_ids='id1,id2'. "
                   "ALL matching: query='from:newsletter@X.com'. "
                   "Use delete() first if unsure (moves to Trash, recoverable). "
                   "Provide message_ids OR query."
               ))
async def fn_purge(ctx, params: PurgeUnifiedParams) -> ActionResult:
    try:
        if params.message_ids:
            ids = _ids(params.message_ids)
            if len(ids) == 1:
                r = await impl_purge(ctx, message_id=ids[0], from_folder=params.from_folder,
                                     account=params.account)
                result = _single_to_bulk(r.ok, "purge")
                summary = "Permanently deleted 1 email."
            else:
                result = await impl_bulk_purge(ctx, params.message_ids,
                                               from_folder=params.from_folder,
                                               account=params.account)
                summary = f"Permanently deleted {result.succeeded} email(s)."
        elif params.query:
            result = await impl_mark_all_matching(ctx, params.query, "purge", params.account)
            summary = (f"Permanently deleted {result.succeeded} email(s) "
                       f"(query: '{params.query}').")
        else:
            return ActionResult.error("Provide message_ids or query.", retryable=False)
        return ActionResult.success(data=build_bulk_mail_op(result), summary=summary,
                                    refresh_panels=["inbox"])
    except Exception as e:
        return ActionResult.error(str(e), retryable=False)
