"""Google Mail Provider — Gmail REST API (OAuth2)."""
from __future__ import annotations

import asyncio
import base64
import logging

from imperal_sdk import Context

from .base import BaseMailProvider
from .helpers import (
    GMAIL_API, SKELETON_INBOX,
    _api_get, _api_post,
    _refresh_token_if_needed,
    _remove_from_cache, _update_read_in_cache, _save_last_read,
    _build_message, _decode_body, _decode_body_with_type, _strip_html, _header, _short_sender,
)

log = logging.getLogger(__name__)

FOLDER_LABELS: dict = {
    "sent":    "SENT",   "spam":    "SPAM",
    "trash":   "TRASH",  "starred": "STARRED",
    "draft":   "DRAFT",  "drafts":  "DRAFT",
    "all":     "",       "archive": "",
    "unread":  "UNREAD",
}

_PAGE_FOLDER_LABELS: dict[str, str] = {
    "inbox": "INBOX", "sent": "SENT", "spam": "SPAM",
    "trash": "TRASH", "drafts": "DRAFT", "starred": "STARRED",
}


class GoogleMailProvider(BaseMailProvider):

    @staticmethod
    def _normalize_msg(data: dict) -> dict:
        headers = data.get("payload", {}).get("headers", [])
        label_ids = data.get("labelIds", [])
        parts = data.get("payload", {}).get("parts", [])
        has_attachments = any(
            p.get("filename") and p.get("body", {}).get("attachmentId") for p in parts
        )
        return {
            "message_id": data.get("id", ""),
            "thread_id":  data.get("threadId", ""),
            "from":       _short_sender(_header(headers, "From") or "unknown"),
            "subject":    _header(headers, "Subject") or "(no subject)",
            "snippet":    data.get("snippet", ""),
            "date":       _header(headers, "Date") or "",
            "unread":     "UNREAD" in label_ids,
            "starred":    "STARRED" in label_ids,
            "has_attachments": has_attachments,
            "labels":     label_ids,
        }

    async def fetch_inbox(self, ctx: Context, acc: dict, max_results: int = 20) -> dict:
        email_addr = acc.get("email", "")
        resp = await _api_get(ctx, "messages", acc, params={"labelIds": "INBOX", "maxResults": max_results})
        resp.raise_for_status()
        refs = resp.json().get("messages", [])
        messages = []
        for ref in refs:
            meta = await _api_get(ctx, f"messages/{ref['id']}", acc, params={
                "format": "metadata", "metadataHeaders": ["From", "Subject", "Date"],
            })
            if meta.status_code != 200: continue
            data    = meta.json()
            headers = data.get("payload", {}).get("headers", [])
            messages.append({
                "id":        ref["id"],
                "thread_id": data.get("threadId", ""),
                "subject":   _header(headers, "Subject") or "(no subject)",
                "from":      _short_sender(_header(headers, "From") or "unknown"),
                "date":      _header(headers, "Date") or "",
                "unread":    "UNREAD" in data.get("labelIds", []),
            })
        unread = sum(1 for m in messages if m["unread"])
        return self.ok(email=email_addr, messages=messages, unread_count=unread, source="api")

    async def fetch_page(
        self, ctx: Context, acc: dict, folder: str, limit: int,
        cursor_data: dict | None,
    ) -> tuple[list[dict], dict | None, bool]:
        label_id = _PAGE_FOLDER_LABELS.get(folder.lower(), "INBOX")
        params: dict = {"labelIds": label_id, "maxResults": min(limit, 100)}
        if cursor_data and cursor_data.get("token"):
            params["pageToken"] = cursor_data["token"]

        resp = await _api_get(ctx, "messages", acc, params=params)
        resp.raise_for_status()
        body = resp.json()
        refs = body.get("messages", [])
        next_page_token = body.get("nextPageToken")

        async def _fetch_meta(ref_id: str):
            r = await _api_get(ctx, f"messages/{ref_id}", acc, params={
                "format": "metadata", "metadataHeaders": ["From", "Subject", "Date"],
            })
            return r if r.status_code == 200 else None

        results = await asyncio.gather(*[_fetch_meta(ref["id"]) for ref in refs])
        messages: list[dict] = [self._normalize_msg(r.json()) for r in results if r is not None]
        next_cursor = {"token": next_page_token} if next_page_token else None
        has_more = next_page_token is not None
        return messages, next_cursor, has_more

    async def get_unread_count(self, ctx: Context, acc: dict, folder: str = "inbox") -> int:
        label_id = _PAGE_FOLDER_LABELS.get(folder.lower(), "INBOX")
        resp = await _api_get(ctx, f"labels/{label_id}", acc)
        if resp.status_code != 200:
            return 0
        return resp.json().get("messagesUnread", 0)

    async def read_email(self, ctx: Context, acc: dict, message_id: str) -> dict:
        email_addr = acc.get("email", "")
        resp = await _api_get(ctx, f"messages/{message_id}", acc, params={"format": "full"})
        if resp.status_code == 404:
            return self.err(
                "Message not found in this account. "
                "If it belongs to a different account, switch accounts first."
            )
        resp.raise_for_status()
        msg     = resp.json()
        headers = msg.get("payload", {}).get("headers", [])
        subject = _header(headers, "Subject") or "(no subject)"
        sender  = _header(headers, "From")    or "unknown"
        to_addr = _header(headers, "To")      or ""
        date    = _header(headers, "Date")    or ""
        mid_h   = _header(headers, "Message-ID") or ""
        body, body_type = _decode_body_with_type(msg.get("payload", {}))

        try:
            await _api_post(ctx, f"messages/{message_id}/modify", acc, json={"removeLabelIds": ["UNREAD"]})
            await _update_read_in_cache(ctx, email_addr, message_id, is_read=True)
        except Exception:
            pass

        await _save_last_read(ctx, message_id, subject, sender, mid_h, msg.get("threadId", ""))

        def _walk_attachments(payload):
            atts = []
            for part in payload.get("parts", []):
                if part.get("filename") and part.get("body", {}).get("attachmentId"):
                    atts.append({
                        "id":        part["body"]["attachmentId"],
                        "filename":  part["filename"],
                        "size_kb":   round(part["body"].get("size", 0) / 1024, 1),
                        "mime_type": part.get("mimeType", "application/octet-stream"),
                    })
                atts.extend(_walk_attachments(part))
            return atts

        result: dict = {
            "message_id": message_id, "subject": subject, "from": sender,
            "to": to_addr, "date": date, "body": body,
            "thread_id": msg.get("threadId", ""), "body_type": body_type,
        }
        attachments = _walk_attachments(msg.get("payload", {}))
        if attachments: result["attachments"] = attachments
        return self.ok(**result)

    async def send(self, ctx: Context, acc: dict, to: str, subject: str, body: str,
                   cc: str = "", bcc: str = "") -> dict:
        raw  = _build_message(to, subject, body, from_email=acc.get("email", ""), cc=cc, bcc=bcc)
        resp = await _api_post(ctx, "messages/send", acc, json={"raw": raw})
        if resp.status_code in (200, 201):
            return self.ok(sent=True, to=to, subject=subject, from_=acc.get("email", ""))
        return self.err(f"Send failed {resp.status_code}: {resp.text[:200]}")

    async def reply(self, ctx: Context, acc: dict, message_id: str, body: str,
                    to: str = "", cc: str = "", bcc: str = "") -> dict:
        email_addr = acc.get("email", "")
        meta = await _api_get(ctx, f"messages/{message_id}", acc, params={
            "format": "metadata", "metadataHeaders": ["From", "Subject", "Message-ID"],
        })
        if meta.status_code == 404:
            return self.err(
                "Message not found in this account. "
                "If it belongs to a different account, switch accounts first."
            )
        meta.raise_for_status()
        msg        = meta.json()
        headers    = msg.get("payload", {}).get("headers", [])
        orig_from  = _header(headers, "From")
        orig_subj  = _header(headers, "Subject")
        mid_header = _header(headers, "Message-ID")
        thread_id  = msg.get("threadId", "")
        reply_to   = to.split(",")[0].strip() if to else orig_from
        reply_subj = orig_subj if orig_subj.lower().startswith("re:") else f"Re: {orig_subj}"
        raw        = _build_message(reply_to, reply_subj, body, from_email=email_addr,
                                    cc=cc, bcc=bcc, reply_to_id=mid_header)
        payload: dict = {"raw": raw}
        if thread_id: payload["threadId"] = thread_id
        resp = await _api_post(ctx, "messages/send", acc, json=payload)
        if resp.status_code in (200, 201):
            return self.ok(sent=True, to=_short_sender(reply_to), subject=reply_subj,
                           bcc=bcc if bcc else None, from_=email_addr)
        return self.err(f"Reply failed {resp.status_code}: {resp.text[:200]}")

    async def forward(self, ctx: Context, acc: dict, message_id: str,
                      to: str, comment: str = "") -> dict:
        try:
            resp = await _api_get(ctx, f"messages/{message_id}", acc, params={"format": "full"})
            if resp.status_code == 404:
                return self.err(f"Message {message_id} not found.")
            resp.raise_for_status()
            data     = resp.json()
            headers  = data.get("payload", {}).get("headers", [])
            orig_subj = _header(headers, "Subject") or "(no subject)"
            orig_from = _header(headers, "From") or "unknown"
            orig_date = _header(headers, "Date") or ""
            orig_body = _decode_body(data.get("payload", {}))
        except Exception as e:
            return self.err(f"Could not read original for forward: {e}")

        fwd_subj = f"Fwd: {orig_subj}" if not orig_subj.lower().startswith("fwd:") else orig_subj
        fwd_body = (f"{comment}\n\n" if comment else "") + (
            f"---------- Forwarded message ----------\n"
            f"From: {orig_from}\nDate: {orig_date}\nSubject: {orig_subj}\n\n{orig_body}"
        )
        return await self.send(ctx, acc, to=to, subject=fwd_subj, body=fwd_body)

    async def archive(self, ctx: Context, acc: dict, message_id: str) -> dict:
        email_addr = acc.get("email", "")
        try:
            resp = await _api_post(ctx, f"messages/{message_id}/modify", acc,
                                   json={"removeLabelIds": ["INBOX"]})
            resp.raise_for_status()
        except Exception as e:
            return self.err(f"Gmail archive error: {e}")
        await _remove_from_cache(ctx, email_addr, message_id)
        return self.ok(archived=True, message_id=message_id)

    async def delete(self, ctx: Context, acc: dict, message_id: str) -> dict:
        email_addr = acc.get("email", "")
        try:
            resp = await _api_post(ctx, f"messages/{message_id}/trash", acc, json={})
            resp.raise_for_status()
        except Exception as e:
            return self.err(f"Gmail delete error: {e}")
        await _remove_from_cache(ctx, email_addr, message_id)
        return self.ok(deleted=True, message_id=message_id, note="Can be restored from Trash within 30 days.")

    async def mark_read(self, ctx: Context, acc: dict, message_id: str, read: bool = True) -> dict:
        email_addr = acc.get("email", "")
        payload = {"removeLabelIds": ["UNREAD"]} if read else {"addLabelIds": ["UNREAD"]}
        resp = await _api_post(ctx, f"messages/{message_id}/modify", acc, json=payload)
        if resp.status_code == 200:
            await _update_read_in_cache(ctx, email_addr, message_id, is_read=read)
            return self.ok(marked="read" if read else "unread", message_id=message_id)
        return self.err(f"Mark failed {resp.status_code}")

    async def star(self, ctx: Context, acc: dict, message_id: str, starred: bool = True) -> dict:
        payload = ({"addLabelIds": ["STARRED"]} if starred else {"removeLabelIds": ["STARRED"]})
        resp = await _api_post(ctx, f"messages/{message_id}/modify", acc, json=payload)
        if resp.status_code == 200:
            return self.ok(**{"starred" if starred else "unstarred": True, "message_id": message_id})
        return self.err(f"Star failed {resp.status_code}")

    async def search(self, ctx: Context, acc: dict, query: str, max_results: int = 10) -> dict:
        email_addr = acc.get("email", "")
        resp = await _api_get(ctx, "messages", acc, params={"q": query, "maxResults": min(max_results, 20)})
        resp.raise_for_status()
        refs = resp.json().get("messages", [])
        if not refs: return self.ok(query=query, email=email_addr, results=[], total=0)
        results = []
        for ref in refs:
            meta = await _api_get(ctx, f"messages/{ref['id']}", acc, params={
                "format": "metadata", "metadataHeaders": ["From", "Subject", "Date"],
            })
            if meta.status_code != 200: continue
            data    = meta.json()
            headers = data.get("payload", {}).get("headers", [])
            results.append({
                "id": ref["id"],
                "subject": _header(headers, "Subject") or "(no subject)",
                "from":    _short_sender(_header(headers, "From") or "unknown"),
                "date":    _header(headers, "Date") or "",
                "unread":  "UNREAD" in data.get("labelIds", []),
            })
        return self.ok(query=query, email=email_addr, results=results, total=len(results))

    async def folder(self, ctx: Context, acc: dict, folder_name: str, max_results: int = 20) -> dict:
        email_addr = acc.get("email", "")
        label = FOLDER_LABELS.get(folder_name.lower())
        if label is None:
            return self.err(f"Unknown folder '{folder_name}'. Available: {list(FOLDER_LABELS.keys())}")
        params: dict = {"maxResults": min(max_results, 50)}
        if label: params["labelIds"] = label
        try:
            resp = await _api_get(ctx, "messages", acc, params=params)
            resp.raise_for_status()
            refs = resp.json().get("messages", [])
        except Exception as e:
            return self.err(f"Folder error: {e}")
        if not refs: return self.ok(folder=folder_name, email=email_addr, messages=[], total=0)
        messages = []
        for ref in refs:
            try:
                meta = await _api_get(ctx, f"messages/{ref['id']}", acc, params={
                    "format": "metadata", "metadataHeaders": ["From", "To", "Subject", "Date"],
                })
                if meta.status_code != 200: continue
                data    = meta.json()
                headers = data.get("payload", {}).get("headers", [])
                messages.append({
                    "id":      ref["id"],
                    "subject": _header(headers, "Subject") or "(no subject)",
                    "from":    _short_sender(_header(headers, "From") or _header(headers, "To") or "unknown"),
                    "date":    _header(headers, "Date") or "",
                    "unread":  "UNREAD" in data.get("labelIds", []),
                })
            except Exception: continue
        return self.ok(folder=folder_name, email=email_addr, messages=messages, total=len(messages))

    async def get_thread(self, ctx: Context, acc: dict, thread_id: str) -> dict:
        email_addr = acc.get("email", "")
        resp = await _api_get(ctx, f"threads/{thread_id}", acc, params={"format": "full"})
        if resp.status_code == 404: return self.err(f"Thread {thread_id} not found.")
        resp.raise_for_status()
        thread   = resp.json()
        messages = []
        for msg in thread.get("messages", []):
            headers = msg.get("payload", {}).get("headers", [])
            body, body_type = _decode_body_with_type(msg.get("payload", {}))
            messages.append({
                "id":      msg.get("id", ""),
                "subject": _header(headers, "Subject") or "(no subject)",
                "from":    _short_sender(_header(headers, "From") or "unknown"),
                "date":    _header(headers, "Date") or "",
                "unread":  "UNREAD" in msg.get("labelIds", []),
                "body":    body[:2000],
            })
        return self.ok(thread_id=thread_id, email=email_addr, messages=messages, total=len(messages))

    async def move(self, ctx: Context, acc: dict, message_id: str,
                   from_folder: str = "INBOX", to_folder: str = "INBOX") -> dict:
        to = to_folder.lower()
        try:
            if to == "inbox":
                if from_folder.lower() in ("trash", "deleted"):
                    resp = await _api_post(ctx, f"messages/{message_id}/untrash", acc)
                else:
                    resp = await _api_post(ctx, f"messages/{message_id}/modify", acc,
                                           json={"addLabelIds": ["INBOX"], "removeLabelIds": ["SPAM", "TRASH"]})
            elif to in ("spam", "junk"):
                resp = await _api_post(ctx, f"messages/{message_id}/modify", acc,
                                       json={"addLabelIds": ["SPAM"], "removeLabelIds": ["INBOX"]})
            elif to in ("trash", "deleted"):
                resp = await _api_post(ctx, f"messages/{message_id}/trash", acc)
            elif to in ("archive", "all mail"):
                resp = await _api_post(ctx, f"messages/{message_id}/modify", acc,
                                       json={"removeLabelIds": ["INBOX"]})
            else:
                return self.err(f"Gmail move: unsupported destination '{to_folder}'.")
            resp.raise_for_status()
            return self.ok(moved=True, message_id=message_id,
                           from_folder=from_folder, to_folder=to_folder)
        except Exception as e:
            return self.err(f"Gmail move error: {e}")

    async def purge(self, ctx: Context, acc: dict, message_id: str,
                    from_folder: str = "Trash") -> dict:
        try:
            acc  = await _refresh_token_if_needed(ctx, acc)
            resp = await ctx.http.delete(
                f"{GMAIL_API}/messages/{message_id}",
                headers={"Authorization": f"Bearer {acc['access_token']}"},
            )
            if resp.status_code in (200, 204, 404):
                return self.ok(purged=True, message_id=message_id)
            return self.err(f"Gmail permanent delete failed: {resp.status_code}")
        except Exception as e:
            return self.err(f"Gmail purge failed: {e}")
