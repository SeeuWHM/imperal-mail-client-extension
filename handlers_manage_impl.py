"""Mail Client · Email management business logic — impl_* functions."""
from __future__ import annotations

import asyncio

from ctx_helpers import _get_acc
from providers import get_provider
from providers.helpers import _all_accounts, _remove_multiple_from_cache
from schemas import BulkOperationResult, OperationResult

# Hard cap per bulk call. Sequential calls would time out well below this;
# parallel execution (asyncio.gather) keeps wall-clock under ~3s for 200 IDs.
MAX_BULK_IDS = 200
# 5 simultaneous API calls — safe for all providers:
# Gmail (250 quota/s, mark_read=100 units ≈ 2.5 ops/s), IMAP (server connection limit ~5-10),
# Microsoft Graph (~4 req/s). Even at N=5 this is ~10x faster than sequential.
_BULK_CONCURRENCY = 5


def _unwrap(result: dict, op: str, message_id: str = "") -> OperationResult:
    if result.get("RESULT") == "ERROR":
        raise RuntimeError(result.get("error") or f"{op} failed")
    detail = None
    for k in ("detail", "status", "message", "summary"):
        v = result.get(k)
        if v:
            detail = str(v)
            break
    return OperationResult(ok=True,
                           message_id=message_id or result.get("message_id") or result.get("id"),
                           operation=op, detail=detail)


async def _try_all_accounts(ctx, message_id: str, op_name: str, op_fn) -> OperationResult:
    """Try op_fn(acc, provider) across all connected accounts — first success wins."""
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
            last_err = result.get("error") or last_err
        except Exception as e:
            last_err = str(e) or last_err
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
    """Execute a bulk mail operation in parallel (up to _BULK_CONCURRENCY simultaneous calls).

    Sequential execution caused timeouts on large batches (115 calls × 200ms = 23s).
    Parallel execution completes 200 calls in ~3-5s with a 20-slot semaphore.
    """
    ids = [i.strip() for i in message_ids.split(",") if i.strip()]
    if not ids:
        raise RuntimeError("No message IDs provided.")
    if len(ids) > MAX_BULK_IDS:
        raise RuntimeError(
            f"Too many message IDs: {len(ids)}. Maximum per bulk call is {MAX_BULK_IDS}. "
            "Split into multiple calls or use search(max_results=200) to get IDs in batches."
        )
    acc, provider = await _get_acc(ctx, account)
    if not acc:
        raise RuntimeError("No email account connected. Connect one first.")

    sem = asyncio.Semaphore(_BULK_CONCURRENCY)

    async def _do_one(mid: str) -> dict:
        async with sem:
            op_fn = {"archive": provider.archive, "delete": provider.delete}.get(operation)
            if op_fn:
                return await op_fn(ctx, acc, mid)
            elif operation == "read":
                return await provider.mark_read(ctx, acc, mid, read=True)
            elif operation == "unread":
                return await provider.mark_read(ctx, acc, mid, read=False)
            return {"RESULT": "ERROR", "error": "Unknown operation"}

    task_results = await asyncio.gather(*[_do_one(mid) for mid in ids], return_exceptions=True)

    success, failed, removed = 0, [], []
    for mid, r in zip(ids, task_results):
        if isinstance(r, Exception):
            failed.append(f"{mid[:16]}: {r}")
        elif r.get("RESULT") == "SUCCESS":
            success += 1
            if operation in ("archive", "delete"):
                removed.append(mid)
        else:
            failed.append(f"{mid[:16]}: {r.get('error') or '?'}")

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


async def impl_bulk_move(ctx, message_ids: str, from_folder: str, to_folder: str,
                         account: str = "") -> BulkOperationResult:
    ids = [i.strip() for i in message_ids.split(",") if i.strip()]
    if not ids:
        raise RuntimeError("No message IDs provided.")
    if len(ids) > MAX_BULK_IDS:
        raise RuntimeError(
            f"Too many message IDs: {len(ids)}. Maximum per bulk call is {MAX_BULK_IDS}."
        )
    acc, provider = await _get_acc(ctx, account)
    if not acc:
        raise RuntimeError("No email account connected. Connect one first.")

    sem = asyncio.Semaphore(_BULK_CONCURRENCY)

    async def _do_one(mid: str) -> dict:
        async with sem:
            return await provider.move(ctx, acc, mid, from_folder=from_folder, to_folder=to_folder)

    task_results = await asyncio.gather(*[_do_one(mid) for mid in ids], return_exceptions=True)

    success, failed = 0, []
    for mid, r in zip(ids, task_results):
        if isinstance(r, Exception):
            failed.append(f"{mid[:16]}: {r}")
        elif r.get("RESULT") == "SUCCESS":
            success += 1
        else:
            failed.append(f"{mid[:16]}: {r.get('error') or '?'}")

    return BulkOperationResult(operation="move", succeeded=success,
                               total=len(ids), failed=len(failed) or None, errors=failed[:3])


async def impl_bulk_star(ctx, message_ids: str, starred: bool = True,
                         account: str = "") -> BulkOperationResult:
    ids = [i.strip() for i in message_ids.split(",") if i.strip()]
    if not ids:
        raise RuntimeError("No message IDs provided.")
    if len(ids) > MAX_BULK_IDS:
        raise RuntimeError(
            f"Too many message IDs: {len(ids)}. Maximum per bulk call is {MAX_BULK_IDS}."
        )
    acc, provider = await _get_acc(ctx, account)
    if not acc:
        raise RuntimeError("No email account connected. Connect one first.")

    sem = asyncio.Semaphore(_BULK_CONCURRENCY)

    async def _do_one(mid: str) -> dict:
        async with sem:
            return await provider.star(ctx, acc, mid, starred=starred)

    task_results = await asyncio.gather(*[_do_one(mid) for mid in ids], return_exceptions=True)

    success, failed = 0, []
    for mid, r in zip(ids, task_results):
        if isinstance(r, Exception):
            failed.append(f"{mid[:16]}: {r}")
        elif r.get("RESULT") == "SUCCESS":
            success += 1
        else:
            failed.append(f"{mid[:16]}: {r.get('error') or '?'}")

    op = "star" if starred else "unstar"
    return BulkOperationResult(operation=op, succeeded=success,
                               total=len(ids), failed=len(failed) or None, errors=failed[:3])


async def impl_bulk_purge(ctx, message_ids: str, from_folder: str = "Trash",
                          account: str = "") -> BulkOperationResult:
    ids = [i.strip() for i in message_ids.split(",") if i.strip()]
    if not ids:
        raise RuntimeError("No message IDs provided.")
    if len(ids) > MAX_BULK_IDS:
        raise RuntimeError(
            f"Too many message IDs: {len(ids)}. Maximum per bulk call is {MAX_BULK_IDS}."
        )
    acc, provider = await _get_acc(ctx, account)
    if not acc:
        raise RuntimeError("No email account connected. Connect one first.")

    sem = asyncio.Semaphore(_BULK_CONCURRENCY)

    async def _do_one(mid: str) -> dict:
        async with sem:
            return await provider.purge(ctx, acc, mid, from_folder=from_folder)

    task_results = await asyncio.gather(*[_do_one(mid) for mid in ids], return_exceptions=True)

    success, failed = 0, []
    for mid, r in zip(ids, task_results):
        if isinstance(r, Exception):
            failed.append(f"{mid[:16]}: {r}")
        elif r.get("RESULT") == "SUCCESS":
            success += 1
        else:
            failed.append(f"{mid[:16]}: {r.get('error') or '?'}")

    return BulkOperationResult(operation="purge", succeeded=success,
                               total=len(ids), failed=len(failed) or None, errors=failed[:3])
