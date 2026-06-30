"""IMAP bulk operations mixin — native UID STORE/COPY batch commands."""
from __future__ import annotations

import asyncio

from imperal_sdk import Context

from .imap_write import (
    _sync_imap_bulk_flag,
    _sync_imap_bulk_move,
    _sync_imap_bulk_read_and_move,
    _sync_imap_bulk_purge,
)

IMAP_ARCHIVE_FOLDERS = ["Archive", "[Gmail]/All Mail", "Archives", "All Messages"]
IMAP_TRASH_FOLDERS   = ["Trash", "[Gmail]/Trash", "Deleted Items", "Deleted Messages"]


class ImapBulkMixin:
    """Native IMAP bulk ops — one STORE/COPY command per N messages, like Gmail batchModify."""

    async def bulk_mark_read(self, ctx: Context, acc: dict,
                              message_ids: list, read: bool = True) -> dict:
        args = await self._imap_args(ctx, acc)
        ok, count = await asyncio.to_thread(
            _sync_imap_bulk_flag, acc.get("email", ""), args["host"], args["port"],
            message_ids, "Seen", read,
            password=args["password"], access_token=args["access_token"],
        )
        if ok:
            return self.ok(succeeded=count, total=len(message_ids))
        return self.err("IMAP bulk mark_read failed")

    async def bulk_archive_messages(self, ctx: Context, acc: dict,
                                     message_ids: list) -> dict:
        args = await self._imap_args(ctx, acc)
        ok, count = await asyncio.to_thread(
            _sync_imap_bulk_move, acc.get("email", ""), args["host"], args["port"],
            message_ids, IMAP_ARCHIVE_FOLDERS,
            password=args["password"], access_token=args["access_token"],
        )
        if ok:
            return self.ok(succeeded=count, total=len(message_ids))
        return self.err("IMAP bulk archive failed")

    async def bulk_trash_messages(self, ctx: Context, acc: dict,
                                   message_ids: list) -> dict:
        args = await self._imap_args(ctx, acc)
        ok, count = await asyncio.to_thread(
            _sync_imap_bulk_move, acc.get("email", ""), args["host"], args["port"],
            message_ids, IMAP_TRASH_FOLDERS,
            password=args["password"], access_token=args["access_token"],
        )
        if ok:
            return self.ok(succeeded=count, total=len(message_ids))
        return self.err("IMAP bulk trash failed")

    async def bulk_star_messages(self, ctx: Context, acc: dict,
                                  message_ids: list, starred: bool = True) -> dict:
        args = await self._imap_args(ctx, acc)
        ok, count = await asyncio.to_thread(
            _sync_imap_bulk_flag, acc.get("email", ""), args["host"], args["port"],
            message_ids, "Flagged", starred,
            password=args["password"], access_token=args["access_token"],
        )
        if ok:
            return self.ok(succeeded=count, total=len(message_ids))
        return self.err("IMAP bulk star failed")

    async def bulk_read_and_archive(self, ctx: Context, acc: dict,
                                     message_ids: list) -> dict:
        args = await self._imap_args(ctx, acc)
        ok, count = await asyncio.to_thread(
            _sync_imap_bulk_read_and_move, acc.get("email", ""), args["host"], args["port"],
            message_ids, IMAP_ARCHIVE_FOLDERS,
            password=args["password"], access_token=args["access_token"],
        )
        if ok:
            return self.ok(succeeded=count, total=len(message_ids))
        return self.err("IMAP bulk read_and_archive failed")

    async def bulk_purge_messages(self, ctx: Context, acc: dict,
                                   message_ids: list) -> dict:
        args = await self._imap_args(ctx, acc)
        ok, count = await asyncio.to_thread(
            _sync_imap_bulk_purge, acc.get("email", ""), args["host"], args["port"],
            message_ids,
            password=args["password"], access_token=args["access_token"],
        )
        if ok:
            return self.ok(succeeded=count, total=len(message_ids))
        return self.err("IMAP bulk purge failed")

    async def bulk_apply_label(self, ctx: Context, acc: dict,
                                message_ids: list, label_name: str) -> dict:
        """Move multiple messages to a custom IMAP folder — one UID COPY + STORE + EXPUNGE."""
        args = await self._imap_args(ctx, acc)
        ok, count = await asyncio.to_thread(
            _sync_imap_bulk_move, acc.get("email", ""), args["host"], args["port"],
            message_ids, [label_name],
            password=args["password"], access_token=args["access_token"],
        )
        if ok:
            return self.ok(succeeded=count, total=len(message_ids))
        return self.err(f"IMAP folder '{label_name}' not found or move failed.")
