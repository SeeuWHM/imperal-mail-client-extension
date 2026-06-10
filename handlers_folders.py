"""Mail Client · Mail folder management @chat.function handlers (SDK 5.2.0).

Provides create_mail_folder / delete_mail_folder for creating/removing real folders
and labels in the connected mail account (Gmail labels, Outlook mailFolders, IMAP CREATE).
Created folders are persisted to mail_prefs.custom_folders so they appear in the panel sidebar.
"""
from __future__ import annotations

import logging

from pydantic import BaseModel, Field

from app import chat
from imperal_sdk.chat.action_result import ActionResult
from ctx_helpers import _get_acc
from schemas_sdl_builders_rules import build_rule_op, RuleOpResult

PREFS_COLLECTION = "mail_prefs"
log = logging.getLogger("mail")


class CreateFolderParams(BaseModel):
    folder_name: str = Field(
        description="Name of the new folder or label to create in the mail account"
    )
    account: str = Field(default="", description="Account email or ID (omit for active account)")


class DeleteFolderParams(BaseModel):
    folder_name: str = Field(
        description="Exact name of the folder or label to delete (case-sensitive)"
    )
    account: str = Field(default="", description="Account email or ID (omit for active account)")


async def _add_custom_folder(ctx, folder_name: str) -> None:
    """Persist a custom folder name to mail_prefs.custom_folders."""
    try:
        uid = ctx.user.imperal_id
        page = await ctx.store.query(PREFS_COLLECTION, where={"owner_id": uid}, limit=1)
        if page.data:
            prefs = page.data[0].data
            existing = prefs.get("custom_folders") or []
            if folder_name not in existing:
                await ctx.store.update(PREFS_COLLECTION, page.data[0].id,
                                       {**prefs, "custom_folders": existing + [folder_name]})
        else:
            await ctx.store.create(PREFS_COLLECTION, {
                "owner_id": uid,
                "visible_folders": [],
                "hidden_folders": [],
                "custom_folders": [folder_name],
            })
    except Exception as e:
        log.warning("_add_custom_folder '%s' failed: %s", folder_name, e)


async def _remove_custom_folder(ctx, folder_name: str) -> None:
    """Remove a custom folder name from mail_prefs.custom_folders."""
    try:
        uid = ctx.user.imperal_id
        page = await ctx.store.query(PREFS_COLLECTION, where={"owner_id": uid}, limit=1)
        if page.data:
            prefs = page.data[0].data
            existing = prefs.get("custom_folders") or []
            updated = [f for f in existing if f != folder_name]
            if len(updated) != len(existing):
                await ctx.store.update(PREFS_COLLECTION, page.data[0].id,
                                       {**prefs, "custom_folders": updated})
    except Exception as e:
        log.warning("_remove_custom_folder '%s' failed: %s", folder_name, e)


@chat.function("create_mail_folder", action_type="write", event="folder.created",
               effects=["create:mail_folder"],
               data_model=RuleOpResult,
               description=(
                   "Create a new folder or label in the connected mail account and add it to the "
                   "panel sidebar. Gmail: creates a Gmail label (labels = Gmail's folder system). "
                   "Outlook: creates a real mailFolder. IMAP: creates a server-side folder. "
                   "GMAIL ARCHIVE NOTE: Gmail has NO built-in system Archive folder — archiving "
                   "in Gmail = removing INBOX label (email stays in All Mail, not a separate folder). "
                   "If the user wants a physical folder to browse in Gmail, create it with this "
                   "function first (e.g. 'Archive', 'Work', 'Receipts'), then use move() or "
                   "bulk_move() to put emails there. After creation the folder appears in the sidebar."
               ))
async def fn_create_mail_folder(ctx, params: CreateFolderParams) -> ActionResult:
    """Create a new mail folder or Gmail label and add it to the panel sidebar."""
    try:
        acc, provider = await _get_acc(ctx, params.account)
        if not acc:
            raise RuntimeError("No email account connected.")
        if not hasattr(provider, "create_folder"):
            ptype = acc.get("provider", "oauth")
            return ActionResult.error(
                f"Folder creation is not supported for this account type ({ptype}).",
                retryable=False,
            )
        result = await provider.create_folder(ctx, acc, params.folder_name)
        if result.get("RESULT") == "ERROR":
            return ActionResult.error(result.get("error", "Folder creation failed"),
                                      retryable=False)
        await _add_custom_folder(ctx, params.folder_name)
        return ActionResult.success(
            data=build_rule_op(params.folder_name, f"Created folder '{params.folder_name}'"),
            summary=(
                f"Folder '{params.folder_name}' created and added to the sidebar. "
                "Use move() or bulk_move() with to_folder='{params.folder_name}' to put emails there."
            ),
            refresh_panels=["inbox"],
        )
    except Exception as e:
        return ActionResult.error(str(e), retryable=False)


@chat.function("delete_mail_folder", action_type="destructive", event="folder.deleted",
               effects=["delete:mail_folder"],
               data_model=RuleOpResult,
               description=(
                   "Delete a custom folder or label and remove it from the sidebar. "
                   "Gmail: deletes the Gmail label — emails inside are NOT deleted, they stay in All Mail. "
                   "Outlook: deletes the mailFolder — emails are moved to Deleted Items. "
                   "Cannot delete system folders (INBOX, Sent, Trash, Spam, Drafts, Starred)."
               ))
async def fn_delete_mail_folder(ctx, params: DeleteFolderParams) -> ActionResult:
    """Delete a custom mail folder or Gmail label and remove from sidebar."""
    try:
        acc, provider = await _get_acc(ctx, params.account)
        if not acc:
            raise RuntimeError("No email account connected.")
        if not hasattr(provider, "delete_folder"):
            return ActionResult.error(
                "Folder deletion is not supported for this account type.",
                retryable=False,
            )
        result = await provider.delete_folder(ctx, acc, params.folder_name)
        if result.get("RESULT") == "ERROR":
            return ActionResult.error(result.get("error", "Folder deletion failed"),
                                      retryable=False)
        await _remove_custom_folder(ctx, params.folder_name)
        return ActionResult.success(
            data=build_rule_op(params.folder_name, f"Deleted folder '{params.folder_name}'"),
            summary=f"Folder '{params.folder_name}' deleted and removed from sidebar.",
            refresh_panels=["inbox"],
        )
    except Exception as e:
        return ActionResult.error(str(e), retryable=False)
