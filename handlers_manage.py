"""Mail Client · Email management & bulk operations (SDK v2.0.0)."""
from __future__ import annotations

from ctx_helpers import _get_acc

from providers.helpers import _remove_multiple_from_cache

from schemas import BulkOperationResult, OperationResult


def _unwrap(result: dict, op: str, message_id: str = "") -> OperationResult:
    """Convert legacy provider ``RESULT: SUCCESS|ERROR`` dict to OperationResult.

    Raises RuntimeError on provider ERROR so the kernel surfaces a clear
    failure to the Narrator; returns OperationResult on success.
    """
    if result.get("RESULT") == "ERROR":
        raise RuntimeError(result.get("error", f"{op} failed"))
    detail = None
    for k in ("detail", "status", "message", "summary"):
        v = result.get(k)
        if v:
            detail = str(v)
            break
    return OperationResult(
        ok=True,
        message_id=message_id or result.get("message_id") or result.get("id"),
        operation=op,
        detail=detail,
    )


# ─── Single Operations ────────────────────────────────────────────────── #


async def impl_archive(ctx, message_id: str, account: str = "") -> OperationResult:
    acc, provider = await _get_acc(ctx, account)
    if not acc:
        raise RuntimeError("No email account connected. Connect one first.")
    return _unwrap(await provider.archive(ctx, acc, message_id), "archive", message_id)


async def impl_delete(ctx, message_id: str, account: str = "") -> OperationResult:
    acc, provider = await _get_acc(ctx, account)
    if not acc:
        raise RuntimeError("No email account connected. Connect one first.")
    return _unwrap(await provider.delete(ctx, acc, message_id), "delete", message_id)


async def impl_mark_read(ctx, message_id: str, account: str = "") -> OperationResult:
    acc, provider = await _get_acc(ctx, account)
    if not acc:
        raise RuntimeError("No email account connected. Connect one first.")
    return _unwrap(
        await provider.mark_read(ctx, acc, message_id, read=True),
        "mark_read", message_id,
    )


async def impl_mark_unread(ctx, message_id: str, account: str = "") -> OperationResult:
    acc, provider = await _get_acc(ctx, account)
    if not acc:
        raise RuntimeError("No email account connected. Connect one first.")
    return _unwrap(
        await provider.mark_read(ctx, acc, message_id, read=False),
        "mark_unread", message_id,
    )


async def impl_star(
    ctx, message_id: str, starred: bool = True, account: str = "",
) -> OperationResult:
    acc, provider = await _get_acc(ctx, account)
    if not acc:
        raise RuntimeError("No email account connected. Connect one first.")
    return _unwrap(
        await provider.star(ctx, acc, message_id, starred=starred),
        "star" if starred else "unstar", message_id,
    )


async def impl_move(
    ctx, message_id: str, from_folder: str, to_folder: str, account: str = "",
) -> OperationResult:
    acc, provider = await _get_acc(ctx, account)
    if not acc:
        raise RuntimeError("No email account connected. Connect one first.")
    return _unwrap(
        await provider.move(
            ctx, acc, message_id,
            from_folder=from_folder, to_folder=to_folder,
        ),
        "move", message_id,
    )


async def impl_purge(
    ctx, message_id: str, from_folder: str = "Trash", account: str = "",
) -> OperationResult:
    acc, provider = await _get_acc(ctx, account)
    if not acc:
        raise RuntimeError("No email account connected. Connect one first.")
    return _unwrap(
        await provider.purge(ctx, acc, message_id, from_folder=from_folder),
        "purge", message_id,
    )


# ─── Bulk Operations ──────────────────────────────────────────────────── #


async def _run_bulk(
    ctx, message_ids: str, operation: str, account: str = "",
) -> BulkOperationResult:
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
    per_op_field = {
        "archive": "archived",
        "delete": "deleted",
        "read": "marked_read",
        "unread": "marked_unread",
    }.get(operation)
    payload = {
        "operation": operation,
        "succeeded": success,
        "total": len(ids),
        "failed": len(failed) or None,
        "errors": failed[:3],
    }
    if per_op_field:
        payload[per_op_field] = success
    return BulkOperationResult(**payload)


async def impl_bulk_archive(
    ctx, message_ids: str, account: str = "",
) -> BulkOperationResult:
    return await _run_bulk(ctx, message_ids, "archive", account=account)


async def impl_bulk_delete(
    ctx, message_ids: str, account: str = "",
) -> BulkOperationResult:
    return await _run_bulk(ctx, message_ids, "delete", account=account)


async def impl_bulk_mark_read(
    ctx, message_ids: str, account: str = "",
) -> BulkOperationResult:
    return await _run_bulk(ctx, message_ids, "read", account=account)


async def impl_bulk_mark_unread(
    ctx, message_ids: str, account: str = "",
) -> BulkOperationResult:
    return await _run_bulk(ctx, message_ids, "unread", account=account)
