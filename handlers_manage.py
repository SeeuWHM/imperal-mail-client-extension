"""Mail Client · Email management @chat.function handlers (SDK 5.2.0 / SDL)."""
from __future__ import annotations

from app import chat
from imperal_sdk.chat.action_result import ActionResult
from handlers_manage_impl import (
    impl_archive, impl_delete, impl_mark_read, impl_mark_unread, impl_star,
    impl_move, impl_purge,
    impl_bulk_archive, impl_bulk_delete, impl_bulk_mark_read, impl_bulk_mark_unread,
    impl_bulk_move, impl_bulk_star, impl_bulk_purge,
)
from schemas import (
    MessageIdParams, StarParams, MoveParams, PurgeParams, BulkParams,
    BulkMoveParams, BulkStarParams, BulkPurgeParams,
)
from schemas_sdl_builders import (
    MailOpResult, BulkMailOpResult,
    build_mail_op, build_bulk_mail_op,
)


@chat.function("archive", action_type="write", event="archived",
               effects=["update:email"],
               data_model=MailOpResult,
               id_projection="message_id",
               description="Archive a single email — removes it from INBOX, stays searchable and recoverable. Requires message_id: call inbox() or search() first if you don't have it yet. Not the same as delete().")
async def fn_archive(ctx, params: MessageIdParams) -> ActionResult:
    """Archive a single email — removes it from INBOX, stays searchable and recoverable."""
    try:
        r = await impl_archive(ctx, message_id=params.message_id, account=params.account)
        return ActionResult.success(
            data=build_mail_op(r),
            summary=f"Archived {params.message_id}.",
            refresh_panels=["inbox"],
        )
    except Exception as e:
        return ActionResult.error(str(e), retryable=True)


@chat.function("delete", action_type="write", event="deleted",
               effects=["update:email"],
               data_model=MailOpResult,
               id_projection="message_id",
               description="Move a single email to Trash — recoverable until emptied. Requires message_id: call inbox() or search() first if you don't have it yet. Use purge() for permanent deletion.")
async def fn_delete(ctx, params: MessageIdParams) -> ActionResult:
    """Move a single email to Trash — recoverable until emptied."""
    try:
        r = await impl_delete(ctx, message_id=params.message_id, account=params.account)
        return ActionResult.success(
            data=build_mail_op(r),
            summary=f"Moved {params.message_id} to Trash.",
            refresh_panels=["inbox"],
        )
    except Exception as e:
        return ActionResult.error(str(e), retryable=True)


@chat.function("mark_read", action_type="write", event="marked_read",
               effects=["update:email"],
               data_model=MailOpResult,
               id_projection="message_id",
               description="Mark a single email as read (clears the unread indicator). For multiple emails use bulk_mark_read().")
async def fn_mark_read(ctx, params: MessageIdParams) -> ActionResult:
    """Mark a single email as read (clears the unread indicator)."""
    try:
        r = await impl_mark_read(ctx, message_id=params.message_id, account=params.account)
        return ActionResult.success(
            data=build_mail_op(r),
            summary=f"Marked {params.message_id} as read.",
            refresh_panels=["inbox"],
        )
    except Exception as e:
        return ActionResult.error(str(e), retryable=True)


@chat.function("mark_unread", action_type="write", event="marked_unread",
               effects=["update:email"],
               data_model=MailOpResult,
               id_projection="message_id",
               description="Mark a single email as unread (restores the unread indicator). For multiple emails use bulk_mark_unread().")
async def fn_mark_unread(ctx, params: MessageIdParams) -> ActionResult:
    """Mark a single email as unread (restores the unread indicator)."""
    try:
        r = await impl_mark_unread(ctx, message_id=params.message_id, account=params.account)
        return ActionResult.success(
            data=build_mail_op(r),
            summary=f"Marked {params.message_id} as unread.",
            refresh_panels=["inbox"],
        )
    except Exception as e:
        return ActionResult.error(str(e), retryable=True)


@chat.function("star", action_type="write", event="starred",
               effects=["update:email"],
               data_model=MailOpResult,
               id_projection="message_id",
               description="Add or remove the starred/important flag on an email. Pass starred=true to star, starred=false to unstar — explicit, not a toggle. Requires message_id: call inbox() or search() first if you don't have it yet.")
async def fn_star(ctx, params: StarParams) -> ActionResult:
    """Add or remove the starred/important flag on an email."""
    try:
        r = await impl_star(ctx, message_id=params.message_id,
                            starred=params.starred, account=params.account)
        action = "Starred" if params.starred else "Unstarred"
        return ActionResult.success(
            data=build_mail_op(r),
            summary=f"{action} {params.message_id}.",
            refresh_panels=["inbox"],
        )
    except Exception as e:
        return ActionResult.error(str(e), retryable=True)


@chat.function("move", action_type="write", event="moved",
               effects=["update:email"],
               data_model=MailOpResult,
               id_projection="message_id",
               description="Move an email from one folder to another — e.g. INBOX→spam, Trash→INBOX (untrash). Requires both from_folder and to_folder.")
async def fn_move(ctx, params: MoveParams) -> ActionResult:
    """Move an email from one folder to another — e.g."""
    try:
        r = await impl_move(ctx, message_id=params.message_id, from_folder=params.from_folder,
                            to_folder=params.to_folder, account=params.account)
        return ActionResult.success(
            data=build_mail_op(r),
            summary=f"Moved {params.message_id} to {params.to_folder}.",
            refresh_panels=["inbox"],
        )
    except Exception as e:
        return ActionResult.error(str(e), retryable=True)


@chat.function("purge", action_type="destructive", event="purged",
               effects=["delete:email"],
               data_model=MailOpResult,
               id_projection="message_id",
               description="Permanently delete an email — cannot be recovered. Requires message_id: call inbox() or search() first if you don't have it. Use delete() to move to Trash first if unsure.")
async def fn_purge(ctx, params: PurgeParams) -> ActionResult:
    """Permanently delete an email — cannot be recovered."""
    try:
        r = await impl_purge(ctx, message_id=params.message_id,
                             from_folder=params.from_folder, account=params.account)
        return ActionResult.success(
            data=build_mail_op(r),
            summary=f"Permanently deleted {params.message_id}.",
            refresh_panels=["inbox"],
        )
    except Exception as e:
        return ActionResult.error(str(e), retryable=False)


@chat.function("bulk_archive", action_type="write", event="bulk_archived",
               effects=["update:email"],
               data_model=BulkMailOpResult,
               description="Archive multiple emails in one operation. Pass message_ids as a comma-separated string. WORKFLOW: first call inbox()/folder()/search() on the TARGET mailbox to load the emails and collect their message_ids, then pass account= for THAT SAME mailbox (a message_id from one account does not exist in another — wrong account = the op fails).")
async def fn_bulk_archive(ctx, params: BulkParams) -> ActionResult:
    """Archive multiple emails in one operation."""
    try:
        r = await impl_bulk_archive(ctx, message_ids=params.message_ids, account=params.account)
        return ActionResult.success(
            data=build_bulk_mail_op(r),
            summary=f"Archived {r.succeeded} email(s).",
            refresh_panels=["inbox"],
        )
    except Exception as e:
        return ActionResult.error(str(e), retryable=True)


@chat.function("bulk_delete", action_type="write", event="bulk_deleted",
               effects=["update:email"],
               data_model=BulkMailOpResult,
               description="Move multiple emails to Trash in one operation. Pass message_ids as a comma-separated string. WORKFLOW: first call inbox()/folder()/search() on the TARGET mailbox to load the emails and collect their message_ids, then pass account= for THAT SAME mailbox (a message_id from one account does not exist in another — wrong account = the op fails).")
async def fn_bulk_delete(ctx, params: BulkParams) -> ActionResult:
    """Move multiple emails to Trash in one operation."""
    try:
        r = await impl_bulk_delete(ctx, message_ids=params.message_ids, account=params.account)
        return ActionResult.success(
            data=build_bulk_mail_op(r),
            summary=f"Deleted {r.succeeded} email(s).",
            refresh_panels=["inbox"],
        )
    except Exception as e:
        return ActionResult.error(str(e), retryable=True)


@chat.function("bulk_mark_read", action_type="write", event="bulk_marked_read",
               effects=["update:email"],
               data_model=BulkMailOpResult,
               description="Mark multiple emails as read in one operation. Pass message_ids as a comma-separated string. WORKFLOW: first call inbox()/folder()/search() on the TARGET mailbox to load the emails and collect their message_ids, then pass account= for THAT SAME mailbox (a message_id from one account does not exist in another — wrong account = the op fails). To act on 'all' emails in a folder, list that folder first (inbox()/folder() with the account) and pass every returned message_id.")
async def fn_bulk_mark_read(ctx, params: BulkParams) -> ActionResult:
    """Mark multiple emails as read in one operation."""
    try:
        r = await impl_bulk_mark_read(ctx, message_ids=params.message_ids, account=params.account)
        return ActionResult.success(
            data=build_bulk_mail_op(r),
            summary=f"Marked {r.succeeded} email(s) as read.",
            refresh_panels=["inbox"],
        )
    except Exception as e:
        return ActionResult.error(str(e), retryable=True)


@chat.function("bulk_mark_unread", action_type="write", event="bulk_marked_unread",
               effects=["update:email"],
               data_model=BulkMailOpResult,
               description="Mark multiple emails as unread in one operation. Pass message_ids as a comma-separated string. WORKFLOW: first call inbox()/folder()/search() on the TARGET mailbox to load the emails and collect their message_ids, then pass account= for THAT SAME mailbox (a message_id from one account does not exist in another — wrong account = the op fails). To act on 'all' emails in a folder, list that folder first (inbox()/folder() with the account) and pass every returned message_id.")
async def fn_bulk_mark_unread(ctx, params: BulkParams) -> ActionResult:
    """Mark multiple emails as unread in one operation."""
    try:
        r = await impl_bulk_mark_unread(ctx, message_ids=params.message_ids, account=params.account)
        return ActionResult.success(
            data=build_bulk_mail_op(r),
            summary=f"Marked {r.succeeded} email(s) as unread.",
            refresh_panels=["inbox"],
        )
    except Exception as e:
        return ActionResult.error(str(e), retryable=True)


@chat.function("bulk_move", action_type="write", event="bulk_moved",
               effects=["update:email"],
               data_model=BulkMailOpResult,
               description="Move multiple emails from one folder to another in one batch. Pass message_ids as comma-separated string. Examples: move spam to INBOX, move selected to archive, move trash items back to INBOX. Get the message_ids first via inbox()/folder()/search() on the SAME mailbox and pass account= for that mailbox (ids are per-account).")
async def fn_bulk_move(ctx, params: BulkMoveParams) -> ActionResult:
    """Move multiple emails from one folder to another in one batch."""
    try:
        r = await impl_bulk_move(ctx, message_ids=params.message_ids,
                                 from_folder=params.from_folder, to_folder=params.to_folder,
                                 account=params.account)
        return ActionResult.success(
            data=build_bulk_mail_op(r),
            summary=f"Moved {r.succeeded} email(s) to {params.to_folder}.",
            refresh_panels=["inbox"],
        )
    except Exception as e:
        return ActionResult.error(str(e), retryable=True)


@chat.function("bulk_star", action_type="write", event="bulk_starred",
               effects=["update:email"],
               data_model=BulkMailOpResult,
               description="Star or unstar multiple emails in one batch. Pass message_ids as comma-separated string. Use starred=true to star, starred=false to unstar. WORKFLOW: first call inbox()/folder()/search() on the TARGET mailbox to load the emails and collect their message_ids, then pass account= for THAT SAME mailbox (a message_id from one account does not exist in another — wrong account = the op fails).")
async def fn_bulk_star(ctx, params: BulkStarParams) -> ActionResult:
    """Star or unstar multiple emails in one batch."""
    try:
        r = await impl_bulk_star(ctx, message_ids=params.message_ids,
                                 starred=params.starred, account=params.account)
        action = "Starred" if params.starred else "Unstarred"
        return ActionResult.success(
            data=build_bulk_mail_op(r),
            summary=f"{action} {r.succeeded} email(s).",
            refresh_panels=["inbox"],
        )
    except Exception as e:
        return ActionResult.error(str(e), retryable=True)


@chat.function("bulk_purge", action_type="destructive", event="bulk_purged",
               effects=["delete:email"],
               data_model=BulkMailOpResult,
               description="Permanently delete multiple emails in one batch — cannot be recovered. Use delete() or bulk_delete() first if unsure. Pass message_ids as comma-separated string. Get the message_ids first via inbox()/folder()/search() on the SAME mailbox and pass account= for that mailbox (ids are per-account).")
async def fn_bulk_purge(ctx, params: BulkPurgeParams) -> ActionResult:
    """Permanently delete multiple emails in one batch — irreversible."""
    try:
        r = await impl_bulk_purge(ctx, message_ids=params.message_ids,
                                  from_folder=params.from_folder, account=params.account)
        return ActionResult.success(
            data=build_bulk_mail_op(r),
            summary=f"Permanently deleted {r.succeeded} email(s).",
            refresh_panels=["inbox"],
        )
    except Exception as e:
        return ActionResult.error(str(e), retryable=False)
