"""IMAP/SMTP Mail Provider — handles both password IMAP and Yahoo XOAUTH2."""
from __future__ import annotations

import asyncio
import logging

from imperal_sdk import Context

from .base import BaseMailProvider
from .helpers import (
    _refresh_token_if_needed, _decrypt_password,
    _remove_from_cache, _update_read_in_cache, _save_last_read,
    IMAP_FOLDER_CANDIDATES,
)
from .imap_connection import _imap_connect_auth, _sync_imap_test, _sync_smtp_test  # noqa: F401
from .imap_read import (
    _sync_imap_inbox, _sync_imap_fetch_page, _sync_imap_unread_count,
    _sync_imap_folder_stats,
    _sync_imap_read, _sync_imap_search, _sync_imap_folder,
)
from .imap_write import (
    _sync_smtp_send, _sync_smtp_xoauth2_send, _save_to_imap_sent,
    _sync_imap_move, _sync_imap_flag_op, _sync_imap_purge,
)

log = logging.getLogger(__name__)

IMAP_ARCHIVE_FOLDERS = ["Archive", "[Gmail]/All Mail", "Archives", "All Messages"]
IMAP_TRASH_FOLDERS   = ["Trash", "[Gmail]/Trash", "Deleted Items", "Deleted Messages"]


class ImapMailProvider(BaseMailProvider):

    def _imap_args(self, acc: dict) -> dict:
        if acc.get("provider", "imap") == "yahoo":
            return {
                "host": acc.get("imap_host", "imap.mail.yahoo.com"),
                "port": acc.get("imap_port", 993),
                "access_token": acc.get("access_token", ""),
                "password": "",
            }
        password = _decrypt_password(acc.get("password", ""), acc.get("password_encrypted", False))
        return {"host": acc.get("imap_host", ""), "port": acc.get("imap_port", 993),
                "password": password, "access_token": ""}

    async def _ensure_token(self, ctx: Context, acc: dict) -> dict:
        if acc.get("provider") == "yahoo":
            return await _refresh_token_if_needed(ctx, acc)
        return acc

    async def _smtp_dispatch(self, acc: dict, args: dict, email_addr: str,
                             to: str, subject: str, body: str,
                             cc: str = "", bcc: str = "",
                             reply_to_mid: str = "") -> tuple[bool, str, bytes]:
        smtp_host = acc.get("smtp_host", "")
        smtp_port = acc.get("smtp_port", 587)
        if acc.get("provider") == "yahoo":
            return await asyncio.to_thread(
                _sync_smtp_xoauth2_send, email_addr, args["access_token"],
                smtp_host, smtp_port, to, subject, body, cc, bcc, reply_to_mid)
        return await asyncio.to_thread(
            _sync_smtp_send, email_addr, args["password"],
            smtp_host, smtp_port, to, subject, body, cc, bcc, reply_to_mid)

    async def _save_sent_async(self, email_addr: str, args: dict, msg_bytes: bytes) -> None:
        """Save sent copy to IMAP Sent folder.

        Awaited directly — asyncio.ensure_future is unreliable inside Temporal
        activities (the worker runtime may cancel pending tasks on activity return).
        _save_to_imap_sent already has its own try/except so failures are non-fatal.
        """
        await asyncio.to_thread(
            _save_to_imap_sent, email_addr, args["host"], args["port"], msg_bytes,
            password=args["password"], access_token=args["access_token"])

    async def fetch_inbox(self, ctx: Context, acc: dict, max_results: int = 20) -> dict:
        email_addr = acc.get("email", "")
        acc = await self._ensure_token(ctx, acc)
        args = self._imap_args(acc)
        messages = await asyncio.to_thread(
            _sync_imap_inbox, email_addr, args["host"], args["port"], max_results,
            password=args["password"], access_token=args["access_token"])
        unread = sum(1 for m in messages if m.get("unread"))
        return self.ok(email=email_addr, messages=messages, unread_count=unread, source="api")

    async def fetch_page(self, ctx: Context, acc: dict, folder: str, limit: int,
                         cursor_data: dict | None) -> tuple[list[dict], dict | None, bool]:
        last_uid = cursor_data.get("last_uid") if cursor_data else None
        imap_folder = "INBOX" if folder.lower() == "inbox" else folder
        email_addr = acc.get("email", "")
        acc = await self._ensure_token(ctx, acc)
        args = self._imap_args(acc)
        messages, new_last_uid, has_more = await asyncio.to_thread(
            _sync_imap_fetch_page, email_addr, args["host"], args["port"],
            imap_folder, limit, last_uid,
            password=args["password"], access_token=args["access_token"])
        next_cursor = {"last_uid": new_last_uid} if new_last_uid and has_more else None
        return messages, next_cursor, has_more

    async def get_unread_count(self, ctx: Context, acc: dict, folder: str = "inbox") -> int:
        imap_folder = "INBOX" if folder.lower() == "inbox" else folder
        acc = await self._ensure_token(ctx, acc)
        args = self._imap_args(acc)
        try:
            return await asyncio.to_thread(
                _sync_imap_unread_count, acc.get("email", ""), args["host"], args["port"],
                imap_folder, password=args["password"], access_token=args["access_token"])
        except Exception:
            return 0

    async def get_folder_stats(self, ctx: Context, acc: dict, folder: str = "inbox") -> dict:
        imap_folder = "INBOX" if folder.lower() == "inbox" else folder
        acc = await self._ensure_token(ctx, acc)
        args = self._imap_args(acc)
        try:
            return await asyncio.to_thread(
                _sync_imap_folder_stats, acc.get("email", ""), args["host"], args["port"],
                imap_folder, password=args["password"], access_token=args["access_token"])
        except Exception:
            return {"total": 0, "unread": 0}

    async def read_email(self, ctx: Context, acc: dict, message_id: str) -> dict:
        email_addr = acc.get("email", "")
        acc  = await self._ensure_token(ctx, acc)
        args = self._imap_args(acc)
        try:
            data = await asyncio.to_thread(
                _sync_imap_read, email_addr, args["host"], args["port"], message_id,
                password=args["password"], access_token=args["access_token"])
        except Exception as e:
            return self.err(f"IMAP error: {e}")
        if not data: return self.err(f"Message {message_id} not found.")
        body = data.get("body", "")
        if len(body) > 4000: data["body"] = body[:4000]; data["truncated"] = True
        await _save_last_read(ctx, message_id, data.get("subject", ""), data.get("from", ""),
                              data.get("message_id_header", ""), "", account=email_addr)
        await _update_read_in_cache(ctx, email_addr, message_id, is_read=True)
        return self.ok(**data, message_id=message_id)

    async def send(self, ctx: Context, acc: dict, to: str, subject: str, body: str,
                   cc: str = "", bcc: str = "") -> dict:
        email_addr = acc.get("email", "")
        acc  = await self._ensure_token(ctx, acc)
        args = self._imap_args(acc)
        ok, err, msg_bytes = await self._smtp_dispatch(acc, args, email_addr, to, subject, body, cc, bcc)
        if not ok: return self.err(f"SMTP error: {err}")
        await self._save_sent_async(email_addr, args, msg_bytes)
        return self.ok(sent=True, to=to, subject=subject, from_=email_addr)

    async def reply(self, ctx: Context, acc: dict, message_id: str, body: str,
                    to: str = "", cc: str = "", bcc: str = "") -> dict:
        email_addr = acc.get("email", "")
        acc  = await self._ensure_token(ctx, acc)
        args = self._imap_args(acc)
        try:
            orig = await asyncio.to_thread(
                _sync_imap_read, email_addr, args["host"], args["port"], message_id,
                password=args["password"], access_token=args["access_token"])
        except Exception as e:
            return self.err(f"Could not read original: {e}")
        if not orig: return self.err(f"Message {message_id} not found.")
        orig_from  = orig.get("from", "")
        orig_subj  = orig.get("subject", "")
        mid_header = orig.get("message_id_header", "")
        reply_to   = to.split(",")[0].strip() if to else orig_from
        reply_subj = orig_subj if orig_subj.lower().startswith("re:") else f"Re: {orig_subj}"
        ok, err, msg_bytes = await self._smtp_dispatch(
            acc, args, email_addr, reply_to, reply_subj, body, cc, bcc, mid_header)
        if not ok: return self.err(f"SMTP reply error: {err}")
        await self._save_sent_async(email_addr, args, msg_bytes)
        return self.ok(sent=True, to=reply_to, subject=reply_subj,
                       bcc=bcc if bcc else None, from_=email_addr)

    async def forward(self, ctx: Context, acc: dict, message_id: str,
                      to: str, comment: str = "") -> dict:
        read_result = await self.read_email(ctx, acc, message_id)
        if read_result.get("RESULT") == "ERROR":
            return self.err(f"Could not read original: {read_result['error']}")
        orig_subj = read_result.get("subject", "")
        fwd_subj  = f"Fwd: {orig_subj}" if not orig_subj.startswith("Fwd:") else orig_subj
        fwd_body  = (f"{comment}\n\n" if comment else "") + (
            f"---------- Forwarded message ----------\n"
            f"From: {read_result.get('from', '')}\n"
            f"Date: {read_result.get('date', '')}\n"
            f"Subject: {orig_subj}\n\n{read_result.get('body', '')}")
        return await self.send(ctx, acc, to=to, subject=fwd_subj, body=fwd_body)

    async def archive(self, ctx: Context, acc: dict, message_id: str) -> dict:
        email_addr = acc.get("email", "")
        acc  = await self._ensure_token(ctx, acc)
        args = self._imap_args(acc)
        ok, err = await asyncio.to_thread(
            _sync_imap_move, email_addr, args["host"], args["port"],
            message_id, IMAP_ARCHIVE_FOLDERS,
            password=args["password"], access_token=args["access_token"])
        if ok:
            await _remove_from_cache(ctx, email_addr, message_id)
            return self.ok(archived=True, message_id=message_id)
        return self.err(f"IMAP archive error: {err}")

    async def delete(self, ctx: Context, acc: dict, message_id: str) -> dict:
        email_addr = acc.get("email", "")
        acc  = await self._ensure_token(ctx, acc)
        args = self._imap_args(acc)
        ok, err = await asyncio.to_thread(
            _sync_imap_move, email_addr, args["host"], args["port"],
            message_id, IMAP_TRASH_FOLDERS,
            password=args["password"], access_token=args["access_token"])
        if ok:
            await _remove_from_cache(ctx, email_addr, message_id)
            return self.ok(deleted=True, message_id=message_id)
        return self.err(f"IMAP delete error: {err}")

    async def mark_read(self, ctx: Context, acc: dict, message_id: str, read: bool = True) -> dict:
        email_addr = acc.get("email", "")
        acc  = await self._ensure_token(ctx, acc)
        args = self._imap_args(acc)
        ok, err = await asyncio.to_thread(
            _sync_imap_flag_op, email_addr, args["host"], args["port"],
            message_id, "Seen", read,
            password=args["password"], access_token=args["access_token"])
        if ok:
            await _update_read_in_cache(ctx, email_addr, message_id, is_read=read)
            return self.ok(marked="read" if read else "unread", message_id=message_id)
        return self.err(err)

    async def star(self, ctx: Context, acc: dict, message_id: str, starred: bool = True) -> dict:
        acc  = await self._ensure_token(ctx, acc)
        args = self._imap_args(acc)
        ok, err = await asyncio.to_thread(
            _sync_imap_flag_op, acc.get("email", ""), args["host"], args["port"],
            message_id, "Flagged", starred,
            password=args["password"], access_token=args["access_token"])
        if ok: return self.ok(**{"starred" if starred else "unstarred": True, "message_id": message_id})
        return self.err(err)

    async def search(self, ctx: Context, acc: dict, query: str, max_results: int = 10) -> dict:
        email_addr = acc.get("email", "")
        acc  = await self._ensure_token(ctx, acc)
        args = self._imap_args(acc)
        results = await asyncio.to_thread(
            _sync_imap_search, email_addr, args["host"], args["port"], query, max_results,
            password=args["password"], access_token=args["access_token"])
        if results is None:
            return self.err(f"IMAP search failed — could not connect to {args['host']}.")
        return self.ok(query=query, email=email_addr, results=results, total=len(results))

    async def folder(self, ctx: Context, acc: dict, folder_name: str, max_results: int = 20) -> dict:
        email_addr = acc.get("email", "")
        acc  = await self._ensure_token(ctx, acc)
        args = self._imap_args(acc)
        messages = await asyncio.to_thread(
            _sync_imap_folder, email_addr, args["host"], args["port"], folder_name, max_results,
            password=args["password"], access_token=args["access_token"])
        if messages is None:
            return self.err(f"Could not open folder '{folder_name}' on {email_addr}.")
        return self.ok(folder=folder_name, email=email_addr, messages=messages, total=len(messages))

    async def move(self, ctx: Context, acc: dict, message_id: str,
                   from_folder: str = "INBOX", to_folder: str = "INBOX") -> dict:
        email_addr = acc.get("email", "")
        if from_folder.lower() == to_folder.lower():
            return self.err("Source and destination folders are the same.")
        acc = await self._ensure_token(ctx, acc)
        args = self._imap_args(acc)
        src_candidates  = IMAP_FOLDER_CANDIDATES.get(from_folder.lower(), [from_folder])
        dest_candidates = IMAP_FOLDER_CANDIDATES.get(to_folder.lower(), [to_folder])
        ok, err = await asyncio.to_thread(
            _sync_imap_move, email_addr, args["host"], args["port"],
            message_id, dest_candidates,
            password=args["password"], access_token=args["access_token"],
            source_folder=src_candidates[0], source_candidates=src_candidates)
        if ok:
            await _remove_from_cache(ctx, email_addr, message_id)
            return self.ok(moved=True, message_id=message_id,
                           from_folder=from_folder, to_folder=to_folder)
        return self.err(f"IMAP move failed: {err}")

    async def purge(self, ctx: Context, acc: dict, message_id: str,
                    from_folder: str = "Trash") -> dict:
        email_addr = acc.get("email", "")
        acc = await self._ensure_token(ctx, acc)
        args = self._imap_args(acc)
        ok, err = await asyncio.to_thread(
            _sync_imap_purge, email_addr, args["host"], args["port"],
            message_id, from_folder,
            password=args["password"], access_token=args["access_token"])
        if ok:
            await _remove_from_cache(ctx, email_addr, message_id)
            return self.ok(purged=True, message_id=message_id, folder=from_folder)
        return self.err(f"IMAP purge failed: {err}")

    async def get_thread(self, ctx: Context, acc: dict, thread_id: str) -> dict:
        return self.err("Thread view is not available for IMAP accounts.")
