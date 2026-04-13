"""Mail Client · Email management & bulk operations."""
from __future__ import annotations

from pydantic import BaseModel, Field

from app import chat, ActionResult, _get_acc, _no_account_error, _wrap_provider_result

from providers.helpers import _remove_multiple_from_cache


# ─── Models ───────────────────────────────────────────────────────────── #

class MessageIdParams(BaseModel):
    """Target a specific email."""
    message_id: str = Field(description="Email message ID")
    account: str    = Field(default="", description="Email account")


class StarParams(BaseModel):
    """Star or unstar an email."""
    message_id: str = Field(description="Email message ID")
    starred: bool   = Field(default=True, description="Star (true) or unstar (false)")
    account: str    = Field(default="", description="Email account")


class MoveParams(BaseModel):
    """Move email between folders."""
    message_id: str  = Field(description="Email message ID")
    from_folder: str = Field(description="Source folder (INBOX, Junk, Trash, Archive)")
    to_folder: str   = Field(description="Destination folder")
    account: str     = Field(default="", description="Email account")


class PurgeParams(BaseModel):
    """Permanently delete an email."""
    message_id: str  = Field(description="Email message ID")
    from_folder: str = Field(default="Trash", description="Folder containing the message")
    account: str     = Field(default="", description="Email account")


class BulkParams(BaseModel):
    """Operate on multiple emails."""
    message_ids: str = Field(description="Comma-separated message IDs")
    account: str     = Field(default="", description="Email account")


# ─── Single Operations ────────────────────────────────────────────────── #

@chat.function("archive", action_type="write", event="archived", description="Archive an email.")
async def fn_archive(ctx, params: MessageIdParams) -> ActionResult:
    acc, provider = await _get_acc(ctx, params.account)
    if not acc: return _no_account_error()
    return _wrap_provider_result(await provider.archive(ctx, acc, params.message_id), f"Email {params.message_id[:16]} archived")


@chat.function("delete", action_type="destructive", event="deleted", description="Move email to Trash.")
async def fn_delete(ctx, params: MessageIdParams) -> ActionResult:
    acc, provider = await _get_acc(ctx, params.account)
    if not acc: return _no_account_error()
    return _wrap_provider_result(await provider.delete(ctx, acc, params.message_id), f"Email {params.message_id[:16]} trashed")


@chat.function("mark_read", action_type="write", description="Mark an email as read.")
async def fn_mark_read(ctx, params: MessageIdParams) -> ActionResult:
    acc, provider = await _get_acc(ctx, params.account)
    if not acc: return _no_account_error()
    return _wrap_provider_result(await provider.mark_read(ctx, acc, params.message_id, read=True), "Marked as read")


@chat.function("mark_unread", action_type="write", description="Mark an email as unread.")
async def fn_mark_unread(ctx, params: MessageIdParams) -> ActionResult:
    acc, provider = await _get_acc(ctx, params.account)
    if not acc: return _no_account_error()
    return _wrap_provider_result(await provider.mark_read(ctx, acc, params.message_id, read=False), "Marked as unread")


@chat.function("star", action_type="write", description="Star or unstar an email.")
async def fn_star(ctx, params: StarParams) -> ActionResult:
    acc, provider = await _get_acc(ctx, params.account)
    if not acc: return _no_account_error()
    return _wrap_provider_result(await provider.star(ctx, acc, params.message_id, starred=params.starred),
                                 f"{'Starred' if params.starred else 'Unstarred'}")


@chat.function("move", action_type="write", event="moved", description="Move email between folders.")
async def fn_move(ctx, params: MoveParams) -> ActionResult:
    acc, provider = await _get_acc(ctx, params.account)
    if not acc: return _no_account_error()
    return _wrap_provider_result(await provider.move(ctx, acc, params.message_id, from_folder=params.from_folder, to_folder=params.to_folder),
                                 f"Moved {params.from_folder} → {params.to_folder}")


@chat.function("purge", action_type="destructive", event="purged", description="Permanently delete an email.")
async def fn_purge(ctx, params: PurgeParams) -> ActionResult:
    acc, provider = await _get_acc(ctx, params.account)
    if not acc: return _no_account_error()
    return _wrap_provider_result(await provider.purge(ctx, acc, params.message_id, from_folder=params.from_folder),
                                 "Permanently deleted")


# ─── Bulk Operations ──────────────────────────────────────────────────── #

async def _run_bulk(ctx, params: BulkParams, operation: str) -> ActionResult:
    ids = [i.strip() for i in params.message_ids.split(",") if i.strip()]
    if not ids:
        return ActionResult.error("No message IDs provided.")
    acc, provider = await _get_acc(ctx, params.account)
    if not acc:
        return _no_account_error()
    success, failed, removed = 0, [], []
    ctx._bulk_skip_cache = True
    try:
        for mid in ids:
            op = {"archive": provider.archive, "delete": provider.delete}.get(operation)
            if op:
                r = await op(ctx, acc, mid)
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
    finally:
        ctx._bulk_skip_cache = False
    if removed:
        await _remove_multiple_from_cache(ctx, acc.get("email", ""), removed)
    if failed:
        return ActionResult.success(data={f"{operation}d": success, "failed": len(failed), "errors": failed[:3]},
                                    summary=f"Bulk {operation}: {success}/{len(ids)}, {len(failed)} failed")
    return ActionResult.success(data={f"{operation}d": success, "total": len(ids)},
                                summary=f"Bulk {operation}: all {success} succeeded")


@chat.function("bulk_archive", action_type="write", event="archived", description="Archive multiple emails.")
async def fn_bulk_archive(ctx, params: BulkParams) -> ActionResult:
    return await _run_bulk(ctx, params, "archive")


@chat.function("bulk_delete", action_type="destructive", event="deleted", description="Delete multiple emails.")
async def fn_bulk_delete(ctx, params: BulkParams) -> ActionResult:
    return await _run_bulk(ctx, params, "delete")


@chat.function("bulk_mark_read", action_type="write", description="Mark multiple emails as read.")
async def fn_bulk_mark_read(ctx, params: BulkParams) -> ActionResult:
    return await _run_bulk(ctx, params, "read")


@chat.function("bulk_mark_unread", action_type="write", description="Mark multiple emails as unread.")
async def fn_bulk_mark_unread(ctx, params: BulkParams) -> ActionResult:
    return await _run_bulk(ctx, params, "unread")
