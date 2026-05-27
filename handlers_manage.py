"""Mail Client · Email management @chat.function handlers."""
from __future__ import annotations

from app import chat
from imperal_sdk.chat.action_result import ActionResult
from handlers_manage_impl import (
    impl_archive, impl_delete, impl_mark_read, impl_mark_unread, impl_star,
    impl_move, impl_purge,
    impl_bulk_archive, impl_bulk_delete, impl_bulk_mark_read, impl_bulk_mark_unread,
)
from schemas import (
    MessageIdParams, StarParams, MoveParams, PurgeParams, BulkParams,
    OperationResult, BulkOperationResult,
)


@chat.function("archive", action_type="write", event="archived",
               effects=["update:email"],
               data_model=OperationResult,
               id_projection="message_id",
               description="Archive a single email — removes it from INBOX into the archive folder. Remains searchable and recoverable. Not the same as delete().")
async def fn_archive(ctx, params: MessageIdParams) -> ActionResult:
    try:
        r = await impl_archive(ctx, message_id=params.message_id, account=params.account)
        return ActionResult.success(data=r.model_dump(), summary=f"Archived {params.message_id}.", refresh_panels=["inbox"])
    except Exception as e:
        return ActionResult.error(str(e), retryable=True)


@chat.function("delete", action_type="write", event="deleted",
               effects=["update:email"],
               data_model=OperationResult,
               id_projection="message_id",
               description="Move a single email to Trash — recoverable until trash is emptied. Use purge() for permanent unrecoverable deletion.")
async def fn_delete(ctx, params: MessageIdParams) -> ActionResult:
    try:
        r = await impl_delete(ctx, message_id=params.message_id, account=params.account)
        return ActionResult.success(data=r.model_dump(), summary=f"Moved {params.message_id} to Trash.", refresh_panels=["inbox"])
    except Exception as e:
        return ActionResult.error(str(e), retryable=True)


@chat.function("mark_read", action_type="write", event="marked_read",
               effects=["update:email"],
               data_model=OperationResult,
               id_projection="message_id",
               description="Mark a single email as read (clears the unread indicator). For multiple emails use bulk_mark_read().")
async def fn_mark_read(ctx, params: MessageIdParams) -> ActionResult:
    try:
        r = await impl_mark_read(ctx, message_id=params.message_id, account=params.account)
        return ActionResult.success(data=r.model_dump(), summary=f"Marked {params.message_id} as read.", refresh_panels=["inbox"])
    except Exception as e:
        return ActionResult.error(str(e), retryable=True)


@chat.function("mark_unread", action_type="write", event="marked_unread",
               effects=["update:email"],
               data_model=OperationResult,
               id_projection="message_id",
               description="Mark a single email as unread (restores the unread indicator). For multiple emails use bulk_mark_unread().")
async def fn_mark_unread(ctx, params: MessageIdParams) -> ActionResult:
    try:
        r = await impl_mark_unread(ctx, message_id=params.message_id, account=params.account)
        return ActionResult.success(data=r.model_dump(), summary=f"Marked {params.message_id} as unread.", refresh_panels=["inbox"])
    except Exception as e:
        return ActionResult.error(str(e), retryable=True)


@chat.function("star", action_type="write", event="starred",
               effects=["update:email"],
               data_model=OperationResult,
               id_projection="message_id",
               description="Add or remove the starred/important flag on an email. Pass starred=true to star, starred=false to unstar — explicit, not a toggle.")
async def fn_star(ctx, params: StarParams) -> ActionResult:
    try:
        r = await impl_star(ctx, message_id=params.message_id,
                            starred=params.starred, account=params.account)
        action = "Starred" if params.starred else "Unstarred"
        return ActionResult.success(data=r.model_dump(), summary=f"{action} {params.message_id}.", refresh_panels=["inbox"])
    except Exception as e:
        return ActionResult.error(str(e), retryable=True)


@chat.function("move", action_type="write", event="moved",
               effects=["update:email"],
               data_model=OperationResult,
               id_projection="message_id",
               description="Move an email from one folder to another — e.g. INBOX→spam, Trash→INBOX (untrash). Requires both from_folder and to_folder.")
async def fn_move(ctx, params: MoveParams) -> ActionResult:
    try:
        r = await impl_move(ctx, message_id=params.message_id, from_folder=params.from_folder,
                            to_folder=params.to_folder, account=params.account)
        return ActionResult.success(data=r.model_dump(),
                                    summary=f"Moved {params.message_id} to {params.to_folder}.",
                                    refresh_panels=["inbox"])
    except Exception as e:
        return ActionResult.error(str(e), retryable=True)


@chat.function("purge", action_type="destructive", event="purged",
               effects=["delete:email"],
               data_model=OperationResult,
               id_projection="message_id",
               description="Permanently delete an email from a folder (default: Trash) — cannot be recovered. Use delete() to move to Trash first if unsure.")
async def fn_purge(ctx, params: PurgeParams) -> ActionResult:
    try:
        r = await impl_purge(ctx, message_id=params.message_id,
                             from_folder=params.from_folder, account=params.account)
        return ActionResult.success(data=r.model_dump(),
                                    summary=f"Permanently deleted {params.message_id}.",
                                    refresh_panels=["inbox"])
    except Exception as e:
        return ActionResult.error(str(e), retryable=False)


@chat.function("bulk_archive", action_type="write", event="bulk_archived",
               effects=["update:email"],
               data_model=BulkOperationResult,
               description="Archive multiple emails in one operation. Pass message_ids as a comma-separated string.")
async def fn_bulk_archive(ctx, params: BulkParams) -> ActionResult:
    try:
        r = await impl_bulk_archive(ctx, message_ids=params.message_ids, account=params.account)
        return ActionResult.success(data=r.model_dump(),
                                    summary=f"Archived {r.succeeded} email(s).",
                                    refresh_panels=["inbox"])
    except Exception as e:
        return ActionResult.error(str(e), retryable=True)


@chat.function("bulk_delete", action_type="write", event="bulk_deleted",
               effects=["update:email"],
               data_model=BulkOperationResult,
               description="Move multiple emails to Trash in one operation. Pass message_ids as a comma-separated string.")
async def fn_bulk_delete(ctx, params: BulkParams) -> ActionResult:
    try:
        r = await impl_bulk_delete(ctx, message_ids=params.message_ids, account=params.account)
        return ActionResult.success(data=r.model_dump(),
                                    summary=f"Deleted {r.succeeded} email(s).",
                                    refresh_panels=["inbox"])
    except Exception as e:
        return ActionResult.error(str(e), retryable=True)


@chat.function("bulk_mark_read", action_type="write", event="bulk_marked_read",
               effects=["update:email"],
               data_model=BulkOperationResult,
               description="Mark multiple emails as read in one operation. Pass message_ids as a comma-separated string.")
async def fn_bulk_mark_read(ctx, params: BulkParams) -> ActionResult:
    try:
        r = await impl_bulk_mark_read(ctx, message_ids=params.message_ids, account=params.account)
        return ActionResult.success(data=r.model_dump(),
                                    summary=f"Marked {r.succeeded} email(s) as read.",
                                    refresh_panels=["inbox"])
    except Exception as e:
        return ActionResult.error(str(e), retryable=True)


@chat.function("bulk_mark_unread", action_type="write", event="bulk_marked_unread",
               effects=["update:email"],
               data_model=BulkOperationResult,
               description="Mark multiple emails as unread in one operation. Pass message_ids as a comma-separated string.")
async def fn_bulk_mark_unread(ctx, params: BulkParams) -> ActionResult:
    try:
        r = await impl_bulk_mark_unread(ctx, message_ids=params.message_ids, account=params.account)
        return ActionResult.success(data=r.model_dump(),
                                    summary=f"Marked {r.succeeded} email(s) as unread.",
                                    refresh_panels=["inbox"])
    except Exception as e:
        return ActionResult.error(str(e), retryable=True)
