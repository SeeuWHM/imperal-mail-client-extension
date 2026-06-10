"""Mail Client · Email management business logic — impl_* functions."""
from __future__ import annotations

import asyncio

from ctx_helpers import _get_acc
from providers import get_provider
from providers.helpers import _all_accounts, _remove_multiple_from_cache
from schemas import BulkOperationResult, OperationResult

# Hard cap per bulk call.
# Gmail: uses batchModify (1 HTTP call for all IDs — no concurrency concern).
# MS Graph / IMAP: parallel per-message with semaphore.
MAX_BULK_IDS = 200
_BULK_CONCURRENCY = 5   # for non-Gmail providers


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


def _check_bulk_ids(ids: list, operation: str) -> None:
    if not ids:
        raise RuntimeError("No message IDs provided.")
    if len(ids) > MAX_BULK_IDS:
        raise RuntimeError(
            f"Too many message IDs: {len(ids)}. Max per call: {MAX_BULK_IDS}. "
            "For 'mark ALL matching as read' use mark_all_matching_read() instead."
        )


def _make_bulk_result(operation: str, succeeded: int, total: int,
                      failed_count: int = 0, errors: list | None = None) -> BulkOperationResult:
    per_op = {"archive": "archived", "delete": "deleted",
              "read": "marked_read", "unread": "marked_unread"}.get(operation)
    payload: dict = {"operation": operation, "succeeded": succeeded, "total": total,
                     "failed": failed_count or None, "errors": (errors or [])[:3]}
    if per_op:
        payload[per_op] = succeeded
    return BulkOperationResult(**payload)


async def _parallel_bulk(ctx, acc, provider, ids: list, operation: str) -> BulkOperationResult:
    """Parallel per-message fallback (MS Graph, IMAP, non-Gmail providers)."""
    sem = asyncio.Semaphore(_BULK_CONCURRENCY)

    async def _do_one(mid: str) -> dict:
        async with sem:
            op_fn = {"archive": provider.archive, "delete": provider.delete}.get(operation)
            if op_fn:
                return await op_fn(ctx, acc, mid)
            if operation == "read":
                return await provider.mark_read(ctx, acc, mid, read=True)
            if operation == "unread":
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
    return _make_bulk_result(operation, success, len(ids), len(failed), failed)


async def impl_bulk_mark_read(ctx, message_ids: str, account: str = "") -> BulkOperationResult:
    ids = [i.strip() for i in message_ids.split(",") if i.strip()]
    _check_bulk_ids(ids, "read")
    acc, provider = await _get_acc(ctx, account)
    if not acc:
        raise RuntimeError("No email account connected.")
    if hasattr(provider, "bulk_mark_read"):
        r = await provider.bulk_mark_read(ctx, acc, ids, read=True)
        if r.get("RESULT") == "SUCCESS":
            return _make_bulk_result("read", r.get("succeeded", len(ids)), len(ids))
    return await _parallel_bulk(ctx, acc, provider, ids, "read")


async def impl_bulk_mark_unread(ctx, message_ids: str, account: str = "") -> BulkOperationResult:
    ids = [i.strip() for i in message_ids.split(",") if i.strip()]
    _check_bulk_ids(ids, "unread")
    acc, provider = await _get_acc(ctx, account)
    if not acc:
        raise RuntimeError("No email account connected.")
    if hasattr(provider, "bulk_mark_read"):
        r = await provider.bulk_mark_read(ctx, acc, ids, read=False)
        if r.get("RESULT") == "SUCCESS":
            return _make_bulk_result("unread", r.get("succeeded", len(ids)), len(ids))
    return await _parallel_bulk(ctx, acc, provider, ids, "unread")


async def impl_bulk_archive(ctx, message_ids: str, account: str = "") -> BulkOperationResult:
    ids = [i.strip() for i in message_ids.split(",") if i.strip()]
    _check_bulk_ids(ids, "archive")
    acc, provider = await _get_acc(ctx, account)
    if not acc:
        raise RuntimeError("No email account connected.")
    if hasattr(provider, "bulk_archive_messages"):
        r = await provider.bulk_archive_messages(ctx, acc, ids)
        if r.get("RESULT") == "SUCCESS":
            return _make_bulk_result("archive", r.get("succeeded", len(ids)), len(ids))
    return await _parallel_bulk(ctx, acc, provider, ids, "archive")


async def impl_bulk_delete(ctx, message_ids: str, account: str = "") -> BulkOperationResult:
    ids = [i.strip() for i in message_ids.split(",") if i.strip()]
    _check_bulk_ids(ids, "delete")
    acc, provider = await _get_acc(ctx, account)
    if not acc:
        raise RuntimeError("No email account connected.")
    if hasattr(provider, "bulk_trash_messages"):
        r = await provider.bulk_trash_messages(ctx, acc, ids)
        if r.get("RESULT") == "SUCCESS":
            return _make_bulk_result("delete", r.get("succeeded", len(ids)), len(ids))
    return await _parallel_bulk(ctx, acc, provider, ids, "delete")


async def impl_bulk_star(ctx, message_ids: str, starred: bool = True,
                         account: str = "") -> BulkOperationResult:
    ids = [i.strip() for i in message_ids.split(",") if i.strip()]
    _check_bulk_ids(ids, "star")
    acc, provider = await _get_acc(ctx, account)
    if not acc:
        raise RuntimeError("No email account connected.")
    if hasattr(provider, "bulk_star_messages"):
        r = await provider.bulk_star_messages(ctx, acc, ids, starred=starred)
        if r.get("RESULT") == "SUCCESS":
            op = "star" if starred else "unstar"
            return _make_bulk_result(op, r.get("succeeded", len(ids)), len(ids))
    # Parallel fallback
    ids_str = ",".join(ids)
    sem = asyncio.Semaphore(_BULK_CONCURRENCY)
    async def _do(mid):
        async with sem:
            return await provider.star(ctx, acc, mid, starred=starred)
    results = await asyncio.gather(*[_do(mid) for mid in ids], return_exceptions=True)
    success, failed = 0, []
    for mid, r in zip(ids, results):
        if isinstance(r, Exception):
            failed.append(f"{mid[:16]}: {r}")
        elif r.get("RESULT") == "SUCCESS":
            success += 1
        else:
            failed.append(f"{mid[:16]}: {r.get('error') or '?'}")
    op = "star" if starred else "unstar"
    return _make_bulk_result(op, success, len(ids), len(failed), failed)


async def impl_bulk_move(ctx, message_ids: str, from_folder: str, to_folder: str,
                         account: str = "") -> BulkOperationResult:
    ids = [i.strip() for i in message_ids.split(",") if i.strip()]
    _check_bulk_ids(ids, "move")
    acc, provider = await _get_acc(ctx, account)
    if not acc:
        raise RuntimeError("No email account connected.")
    sem = asyncio.Semaphore(_BULK_CONCURRENCY)
    async def _do(mid):
        async with sem:
            return await provider.move(ctx, acc, mid, from_folder=from_folder, to_folder=to_folder)
    results = await asyncio.gather(*[_do(mid) for mid in ids], return_exceptions=True)
    success, failed = 0, []
    for mid, r in zip(ids, results):
        if isinstance(r, Exception):
            failed.append(f"{mid[:16]}: {r}")
        elif r.get("RESULT") == "SUCCESS":
            success += 1
        else:
            failed.append(f"{mid[:16]}: {r.get('error') or '?'}")
    return BulkOperationResult(operation="move", succeeded=success,
                               total=len(ids), failed=len(failed) or None, errors=failed[:3])


async def impl_bulk_purge(ctx, message_ids: str, from_folder: str = "Trash",
                          account: str = "") -> BulkOperationResult:
    ids = [i.strip() for i in message_ids.split(",") if i.strip()]
    _check_bulk_ids(ids, "purge")
    acc, provider = await _get_acc(ctx, account)
    if not acc:
        raise RuntimeError("No email account connected.")
    if hasattr(provider, "bulk_purge_messages"):
        r = await provider.bulk_purge_messages(ctx, acc, ids)
        if r.get("RESULT") == "SUCCESS":
            return _make_bulk_result("purge", r.get("succeeded", len(ids)), len(ids))
    sem = asyncio.Semaphore(_BULK_CONCURRENCY)
    async def _do(mid):
        async with sem:
            return await provider.purge(ctx, acc, mid, from_folder=from_folder)
    results = await asyncio.gather(*[_do(mid) for mid in ids], return_exceptions=True)
    success, failed = 0, []
    for mid, r in zip(ids, results):
        if isinstance(r, Exception):
            failed.append(f"{mid[:16]}: {r}")
        elif r.get("RESULT") == "SUCCESS":
            success += 1
        else:
            failed.append(f"{mid[:16]}: {r.get('error') or '?'}")
    return _make_bulk_result("purge", success, len(ids), len(failed), failed)


async def impl_mark_all_matching(ctx, query: str, operation: str,
                                 account: str = "") -> BulkOperationResult:
    """Loop: search(query + filter) → bulk op → repeat until empty.

    Handles unlimited emails without pagination issues.
    Each iteration: 1 search call + 1 Gmail batchModify call (for Gmail).
    Safety cap: 20 iterations × 200 IDs = up to 4000 emails per call.
    """
    from handlers_inbox_impl import impl_search

    # Add Gmail state filter so we only fetch emails that still need the operation.
    # This makes each iteration self-terminating: once all matching emails have the
    # desired state, the search returns empty and the loop stops.
    state_filter = {
        "read":    " is:unread",
        "unread":  " is:read",
        "archive": " in:inbox",
        "delete":  " NOT in:trash",
        "star":    " -is:starred",
        "unstar":  " is:starred",
    }.get(operation, "")
    full_query = query.strip() + state_filter

    total_succeeded = 0
    total_attempted = 0
    MAX_ITERATIONS = 20

    for _iteration in range(MAX_ITERATIONS):
        result = await impl_search(ctx, query=full_query, max_results=200, account=account)
        if not result.results:
            break

        ids_list = [m.get("message_id") or m.get("id") or "" for m in result.results]
        ids_list = [i for i in ids_list if i]
        if not ids_list:
            break

        ids_str = ",".join(ids_list)
        total_attempted += len(ids_list)

        if operation == "read":
            bulk = await impl_bulk_mark_read(ctx, ids_str, account=account)
        elif operation == "unread":
            bulk = await impl_bulk_mark_unread(ctx, ids_str, account=account)
        elif operation == "archive":
            bulk = await impl_bulk_archive(ctx, ids_str, account=account)
        elif operation == "delete":
            bulk = await impl_bulk_delete(ctx, ids_str, account=account)
        elif operation in ("star", "unstar"):
            bulk = await impl_bulk_star(ctx, ids_str,
                                        starred=(operation == "star"), account=account)
        else:
            break

        total_succeeded += bulk.succeeded
        if bulk.succeeded == 0:
            break  # nothing changed — stop to avoid infinite loop

    per_op = {"read": "marked_read", "unread": "marked_unread", "archive": "archived",
              "delete": "deleted", "star": "starred", "unstar": "unstarred"}.get(operation)
    payload: dict = {"operation": operation, "succeeded": total_succeeded,
                     "total": total_attempted}
    if per_op:
        payload[per_op] = total_succeeded
    return BulkOperationResult(**payload)
