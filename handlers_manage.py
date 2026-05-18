"""Mail Client · Email management & bulk operations."""
from __future__ import annotations

from app import chat
from imperal_sdk.chat.action_result import ActionResult
from ctx_helpers import _get_acc

from providers import get_provider
from providers.helpers import _all_accounts, _remove_multiple_from_cache

from schemas import (
    BulkOperationResult, OperationResult,
    MessageIdParams, StarParams, MoveParams, PurgeParams, BulkParams,
)


def _unwrap(result: dict, op: str, message_id: str = "") -> OperationResult:
    if result.get("RESULT") == "ERROR":
        raise RuntimeError(result.get("error", f"{op} failed"))
    detail = None
    for k in ("detail", "status", "message", "summary"):
        v = result.get(k)
        if v:
            detail = str(v)
            break
    return OperationResult(ok=True,
                           message_id=message_id or result.get("message_id") or result.get("id"),
                           operation=op, detail=detail)


# ─── impl_* business logic ────────────────────────────────────────────── #


async def _try_all_accounts(ctx, message_id: str, op_name: str, op_fn) -> OperationResult:
    """Try op_fn(acc, provider) across all connected accounts — first success wins.

    Needed because single-message operations (star, archive, etc.) receive a
    message_id that may belong to any connected account, not just the active one.
    Mirrors the multi-account fallback in impl_read_email and impl_forward.
    """
    accounts = await _all_accounts(ctx)
    if not accounts:
        raise RuntimeError("No email account connected. Connect one first.")
    last_err = "Message not found in any connected account."
    for acc in accounts:
        try:
            provider = get_provider(acc)
            result = await op_fn(acc, provider)
            if result.get("RESULT") != "ERROR":
                return _unwrap(result, op_name, message_id)
            last_err = result.get("error", last_err)
        except Exception as e:
            last_err = str(e)
    raise RuntimeError(last_err)


async def impl_archive(ctx, message_id: str, account: str = "") -> OperationResult:
    if account:
        acc, provider = await _get_acc(ctx, account)
        if not acc:
            raise RuntimeError("Account not found.")
        return _unwrap(await provider.archive(ctx, acc, message_id), "archive", message_id)
    return await _try_all_accounts(ctx, message_id, "archive",
                                   lambda acc, prov: prov.archive(ctx, acc, message_id))


async def impl_delete(ctx, message_id: str, account: str = "") -> OperationResult:
    if account:
        acc, provider = await _get_acc(ctx, account)
        if not acc:
            raise RuntimeError("Account not found.")
        return _unwrap(await provider.delete(ctx, acc, message_id), "delete", message_id)
    return await _try_all_accounts(ctx, message_id, "delete",
                                   lambda acc, prov: prov.delete(ctx, acc, message_id))


async def impl_mark_read(ctx, message_id: str, account: str = "") -> OperationResult:
    if account:
        acc, provider = await _get_acc(ctx, account)
        if not acc:
            raise RuntimeError("Account not found.")
        return _unwrap(await provider.mark_read(ctx, acc, message_id, read=True), "mark_read", message_id)
    return await _try_all_accounts(ctx, message_id, "mark_read",
                                   lambda acc, prov: prov.mark_read(ctx, acc, message_id, read=True))


async def impl_mark_unread(ctx, message_id: str, account: str = "") -> OperationResult:
    if account:
        acc, provider = await _get_acc(ctx, account)
        if not acc:
            raise RuntimeError("Account not found.")
        return _unwrap(await provider.mark_read(ctx, acc, message_id, read=False), "mark_unread", message_id)
    return await _try_all_accounts(ctx, message_id, "mark_unread",
                                   lambda acc, prov: prov.mark_read(ctx, acc, message_id, read=False))


async def impl_star(ctx, message_id: str, starred: bool = True, account: str = "") -> OperationResult:
    op = "star" if starred else "unstar"
    if account:
        acc, provider = await _get_acc(ctx, account)
        if not acc:
            raise RuntimeError("Account not found.")
        return _unwrap(await provider.star(ctx, acc, message_id, starred=starred), op, message_id)
    return await _try_all_accounts(ctx, message_id, op,
                                   lambda acc, prov: prov.star(ctx, acc, message_id, starred=starred))


async def impl_move(ctx, message_id: str, from_folder: str, to_folder: str,
                    account: str = "") -> OperationResult:
    acc, provider = await _get_acc(ctx, account)
    if not acc:
        raise RuntimeError("No email account connected. Connect one first.")
    return _unwrap(await provider.move(ctx, acc, message_id,
                                       from_folder=from_folder, to_folder=to_folder),
                   "move", message_id)


async def impl_purge(ctx, message_id: str, from_folder: str = "Trash",
                     account: str = "") -> OperationResult:
    acc, provider = await _get_acc(ctx, account)
    if not acc:
        raise RuntimeError("No email account connected. Connect one first.")
    return _unwrap(await provider.purge(ctx, acc, message_id, from_folder=from_folder),
                   "purge", message_id)


async def _run_bulk(ctx, message_ids: str, operation: str, account: str = "") -> BulkOperationResult:
    ids = [i.strip() for i in message_ids.split(",") if i.strip()]
    if not ids:
        raise RuntimeError("No message IDs provided.")
    acc, provider = await _get_acc(ctx, account)
    if not acc:
        raise RuntimeError("No email account connected. Connect one first.")
    success, failed, removed = 0, [], []
    for mid in ids:
        op_fn = {"archive": provider.archive, "delete": provider.delete}.get(operation)
        if op_fn:
            r = await op_fn(ctx, acc, mid)
        elif operation == "read":
            r = await provider.mark_read(ctx, acc, mid, read=True)
        elif operation == "unread":
            r = await provider.mark_read(ctx, acc, mid, read=False)
        else:
            r = {"RESULT": "ERROR", "error": "Unknown operation"}
        if r.get("RESULT") == "SUCCESS":
            success += 1
            if operation in ("archive", "delete"):
                removed.append(mid)
        else:
            failed.append(f"{mid[:16]}: {r.get('error', '?')}")
    if removed:
        await _remove_multiple_from_cache(ctx, acc.get("email", ""), removed)
    per_op_field = {"archive": "archived", "delete": "deleted",
                    "read": "marked_read", "unread": "marked_unread"}.get(operation)
    payload = {"operation": operation, "succeeded": success,
               "total": len(ids), "failed": len(failed) or None, "errors": failed[:3]}
    if per_op_field:
        payload[per_op_field] = success
    return BulkOperationResult(**payload)


async def impl_bulk_archive(ctx, message_ids: str, account: str = "") -> BulkOperationResult:
    return await _run_bulk(ctx, message_ids, "archive", account=account)


async def impl_bulk_delete(ctx, message_ids: str, account: str = "") -> BulkOperationResult:
    return await _run_bulk(ctx, message_ids, "delete", account=account)


async def impl_bulk_mark_read(ctx, message_ids: str, account: str = "") -> BulkOperationResult:
    return await _run_bulk(ctx, message_ids, "read", account=account)


async def impl_bulk_mark_unread(ctx, message_ids: str, account: str = "") -> BulkOperationResult:
    return await _run_bulk(ctx, message_ids, "unread", account=account)


# ─── @chat.function wrappers ──────────────────────────────────────────── #


@chat.function("archive", action_type="write", event="archived",
               effects=["update:email"],
               description="Archive a single email — removes it from INBOX into the archive folder. Remains searchable and recoverable. Not the same as delete().")
async def fn_archive(ctx, params: MessageIdParams) -> ActionResult:
    try:
        r = await impl_archive(ctx, message_id=params.message_id, account=params.account)
        return ActionResult.success(data=r.model_dump(), summary=f"Archived {params.message_id}.", refresh_panels=["inbox"])
    except RuntimeError as e:
        return ActionResult.error(str(e), retryable=True)


@chat.function("delete", action_type="write", event="deleted",
               effects=["update:email"],
               description="Move a single email to Trash — recoverable until trash is emptied. Use purge() for permanent unrecoverable deletion.")
async def fn_delete(ctx, params: MessageIdParams) -> ActionResult:
    try:
        r = await impl_delete(ctx, message_id=params.message_id, account=params.account)
        return ActionResult.success(data=r.model_dump(), summary=f"Moved {params.message_id} to Trash.", refresh_panels=["inbox"])
    except RuntimeError as e:
        return ActionResult.error(str(e), retryable=True)


@chat.function("mark_read", action_type="write", event="marked_read",
               effects=["update:email"],
               description="Mark a single email as read (clears the unread indicator). For multiple emails use bulk_mark_read().")
async def fn_mark_read(ctx, params: MessageIdParams) -> ActionResult:
    try:
        r = await impl_mark_read(ctx, message_id=params.message_id, account=params.account)
        return ActionResult.success(data=r.model_dump(), summary=f"Marked {params.message_id} as read.", refresh_panels=["inbox"])
    except RuntimeError as e:
        return ActionResult.error(str(e), retryable=True)


@chat.function("mark_unread", action_type="write", event="marked_unread",
               effects=["update:email"],
               description="Mark a single email as unread (restores the unread indicator). For multiple emails use bulk_mark_unread().")
async def fn_mark_unread(ctx, params: MessageIdParams) -> ActionResult:
    try:
        r = await impl_mark_unread(ctx, message_id=params.message_id, account=params.account)
        return ActionResult.success(data=r.model_dump(), summary=f"Marked {params.message_id} as unread.", refresh_panels=["inbox"])
    except RuntimeError as e:
        return ActionResult.error(str(e), retryable=True)


@chat.function("star", action_type="write", event="starred",
               effects=["update:email"],
               description="Add or remove the starred/important flag on an email. Pass starred=true to star, starred=false to unstar — explicit, not a toggle.")
async def fn_star(ctx, params: StarParams) -> ActionResult:
    try:
        r = await impl_star(ctx, message_id=params.message_id,
                            starred=params.starred, account=params.account)
        action = "Starred" if params.starred else "Unstarred"
        return ActionResult.success(data=r.model_dump(), summary=f"{action} {params.message_id}.", refresh_panels=["inbox"])
    except RuntimeError as e:
        return ActionResult.error(str(e), retryable=True)


@chat.function("move", action_type="write", event="moved",
               effects=["update:email"],
               description="Move an email from one folder to another — e.g. INBOX→spam, Trash→INBOX (untrash). Requires both from_folder and to_folder.")
async def fn_move(ctx, params: MoveParams) -> ActionResult:
    try:
        r = await impl_move(ctx, message_id=params.message_id, from_folder=params.from_folder,
                            to_folder=params.to_folder, account=params.account)
        return ActionResult.success(data=r.model_dump(),
                                    summary=f"Moved {params.message_id} to {params.to_folder}.",
                                    refresh_panels=["inbox"])
    except RuntimeError as e:
        return ActionResult.error(str(e), retryable=True)


@chat.function("purge", action_type="destructive", event="purged",
               effects=["delete:email"],
               description="Permanently delete an email from a folder (default: Trash) — cannot be recovered. Use delete() to move to Trash first if unsure.")
async def fn_purge(ctx, params: PurgeParams) -> ActionResult:
    try:
        r = await impl_purge(ctx, message_id=params.message_id,
                             from_folder=params.from_folder, account=params.account)
        return ActionResult.success(data=r.model_dump(),
                                    summary=f"Permanently deleted {params.message_id}.",
                                    refresh_panels=["inbox"])
    except RuntimeError as e:
        return ActionResult.error(str(e), retryable=False)


@chat.function("bulk_archive", action_type="write", event="bulk_archived",
               effects=["update:email"],
               description="Archive multiple emails in one operation. Pass message_ids as a comma-separated string.")
async def fn_bulk_archive(ctx, params: BulkParams) -> ActionResult:
    try:
        r = await impl_bulk_archive(ctx, message_ids=params.message_ids, account=params.account)
        return ActionResult.success(data=r.model_dump(),
                                    summary=f"Archived {r.succeeded} email(s).",
                                    refresh_panels=["inbox"])
    except RuntimeError as e:
        return ActionResult.error(str(e), retryable=True)


@chat.function("bulk_delete", action_type="write", event="bulk_deleted",
               effects=["update:email"],
               description="Move multiple emails to Trash in one operation. Pass message_ids as a comma-separated string.")
async def fn_bulk_delete(ctx, params: BulkParams) -> ActionResult:
    try:
        r = await impl_bulk_delete(ctx, message_ids=params.message_ids, account=params.account)
        return ActionResult.success(data=r.model_dump(),
                                    summary=f"Deleted {r.succeeded} email(s).",
                                    refresh_panels=["inbox"])
    except RuntimeError as e:
        return ActionResult.error(str(e), retryable=True)


@chat.function("bulk_mark_read", action_type="write", event="bulk_marked_read",
               effects=["update:email"],
               description="Mark multiple emails as read in one operation. Pass message_ids as a comma-separated string.")
async def fn_bulk_mark_read(ctx, params: BulkParams) -> ActionResult:
    try:
        r = await impl_bulk_mark_read(ctx, message_ids=params.message_ids, account=params.account)
        return ActionResult.success(data=r.model_dump(),
                                    summary=f"Marked {r.succeeded} email(s) as read.",
                                    refresh_panels=["inbox"])
    except RuntimeError as e:
        return ActionResult.error(str(e), retryable=True)


@chat.function("bulk_mark_unread", action_type="write", event="bulk_marked_unread",
               effects=["update:email"],
               description="Mark multiple emails as unread in one operation. Pass message_ids as a comma-separated string.")
async def fn_bulk_mark_unread(ctx, params: BulkParams) -> ActionResult:
    try:
        r = await impl_bulk_mark_unread(ctx, message_ids=params.message_ids, account=params.account)
        return ActionResult.success(data=r.model_dump(),
                                    summary=f"Marked {r.succeeded} email(s) as unread.",
                                    refresh_panels=["inbox"])
    except RuntimeError as e:
        return ActionResult.error(str(e), retryable=True)
