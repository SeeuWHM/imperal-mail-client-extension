"""Google Mail Provider — read operations (fetch, read, search, folder, thread)."""
from __future__ import annotations

import asyncio

from imperal_sdk import Context

from .helpers import (
    _api_get, _api_post,
    _update_read_in_cache, _save_last_read,
    _decode_body, _decode_body_with_type, _strip_html, _header, _short_sender,
)

_PAGE_FOLDER_LABELS: dict[str, str] = {
    "inbox": "INBOX", "sent": "SENT", "spam": "SPAM",
    "trash": "TRASH", "drafts": "DRAFT", "starred": "STARRED",
}

FOLDER_LABELS: dict = {
    "sent":    "SENT",   "spam":    "SPAM",
    "trash":   "TRASH",  "starred": "STARRED",
    "draft":   "DRAFT",  "drafts":  "DRAFT",
    "all":     "",       "archive": "",
    "unread":  "UNREAD",
}

# Upper bound for accurate search counting via id-only pagination. Gmail's
# resultSizeEstimate is unreliable, so search() counts real message IDs page by
# page (500/page). The cap bounds latency on very large result sets — beyond it
# the reported total is the cap (a "≥cap" floor), which is plenty for routing.
_SEARCH_COUNT_CAP = 2000

# Max concurrent per-message metadata fetches when building search previews.
# Gmail has no batch in this client, so previews are fetched one HTTP call each;
# doing them serially turned a 200-result filter into 200 round-trips (the panel
# timeout). Bounded concurrency keeps it fast without tripping Gmail rate limits.
_META_CONCURRENCY = 12


class GoogleReadMixin:

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
            if meta.status_code != 200:
                continue
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
        params: dict = {"maxResults": min(limit, 100)}
        if cursor_data and cursor_data.get("token"):
            params["pageToken"] = cursor_data["token"]
        if folder.lower() == "archive":
            # Gmail has no Archive label — archived = not in inbox/trash/spam/drafts
            params["q"] = "-in:inbox -in:trash -in:spam -in:drafts"
        else:
            params["labelIds"] = _PAGE_FOLDER_LABELS.get(folder.lower(), "INBOX")
        resp = await _api_get(ctx, "messages", acc, params=params)
        resp.raise_for_status()
        body           = resp.json()
        refs           = body.get("messages", [])
        next_page_token = body.get("nextPageToken")

        async def _fetch_meta(ref_id: str):
            r = await _api_get(ctx, f"messages/{ref_id}", acc, params={
                "format": "metadata", "metadataHeaders": ["From", "Subject", "Date"],
            })
            return r if r.status_code == 200 else None

        results  = await asyncio.gather(*[_fetch_meta(ref["id"]) for ref in refs])
        messages = [self._normalize_msg(r.json()) for r in results if r is not None]
        next_cursor = {"token": next_page_token} if next_page_token else None
        return messages, next_cursor, next_page_token is not None

    async def get_unread_count(self, ctx: Context, acc: dict, folder: str = "inbox") -> int:
        if folder.lower() == "archive":
            return 0  # Gmail archive has no direct label for unread count
        label_id = _PAGE_FOLDER_LABELS.get(folder.lower(), "INBOX")
        resp = await _api_get(ctx, f"labels/{label_id}", acc)
        if resp.status_code != 200:
            return 0
        return resp.json().get("messagesUnread", 0)

    async def get_folder_stats(self, ctx: Context, acc: dict, folder: str = "inbox") -> dict:
        if folder.lower() == "archive":
            return {"total": 0, "unread": 0}  # Gmail archive needs a search for counts
        label_id = _PAGE_FOLDER_LABELS.get(folder.lower(), "INBOX")
        resp = await _api_get(ctx, f"labels/{label_id}", acc)
        if resp.status_code != 200:
            return {"total": 0, "unread": 0}
        data = resp.json()
        return {"total": data.get("messagesTotal", 0), "unread": data.get("messagesUnread", 0)}

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
        cc_addr = _header(headers, "Cc")      or ""
        date    = _header(headers, "Date")    or ""
        mid_h   = _header(headers, "Message-ID") or ""
        body, body_type = _decode_body_with_type(msg.get("payload", {}))
        try:
            await _api_post(ctx, f"messages/{message_id}/modify", acc, json={"removeLabelIds": ["UNREAD"]})
            await _update_read_in_cache(ctx, email_addr, message_id, is_read=True)
        except Exception:
            pass
        await _save_last_read(ctx, message_id, subject, sender, mid_h, msg.get("threadId", ""), account=email_addr)

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
            "to": to_addr, "cc": cc_addr, "date": date, "body": body,
            "thread_id": msg.get("threadId", ""), "body_type": body_type,
        }
        attachments = _walk_attachments(msg.get("payload", {}))
        if attachments:
            result["attachments"] = attachments
        return self.ok(**result)

    async def search(self, ctx: Context, acc: dict, query: str, max_results: int = 10) -> dict:
        email_addr = acc.get("email", "")
        page_size  = min(max(max_results, 1), 500)
        # First page (ids only). We NEVER trust resultSizeEstimate — it is a wildly
        # inaccurate estimate (e.g. reports 15 for a query Gmail itself counts as 50).
        resp = await _api_get(ctx, "messages", acc, params={
            "q": query, "maxResults": page_size,
            "fields": "messages/id,nextPageToken",
        })
        resp.raise_for_status()
        body = resp.json()
        refs = body.get("messages", []) or []
        if not refs:
            return self.ok(query=query, email=email_addr, results=[], total=0)

        # Accurate total: walk nextPageToken counting real message IDs (id-only,
        # no metadata fetch — cheap), bounded by _SEARCH_COUNT_CAP.
        total      = len(refs)
        page_token = body.get("nextPageToken")
        while page_token and total < _SEARCH_COUNT_CAP:
            r = await _api_get(ctx, "messages", acc, params={
                "q": query, "maxResults": 500, "pageToken": page_token,
                "fields": "messages/id,nextPageToken",
            })
            r.raise_for_status()
            b = r.json()
            total     += len(b.get("messages", []) or [])
            page_token = b.get("nextPageToken")

        # Build previews (and ids for bulk ops) only for the first page. Fetch
        # metadata concurrently (bounded) — serial fetches over a 200-result page
        # were the filter-panel timeout. gather() preserves order.
        sem = asyncio.Semaphore(_META_CONCURRENCY)

        async def _preview(ref: dict):
            async with sem:
                meta = await _api_get(ctx, f"messages/{ref['id']}", acc, params={
                    "format": "metadata", "metadataHeaders": ["From", "Subject", "Date"],
                })
            if meta.status_code != 200:
                return None
            data    = meta.json()
            headers = data.get("payload", {}).get("headers", [])
            return {
                "id":      ref["id"],
                "subject": _header(headers, "Subject") or "(no subject)",
                "from":    _short_sender(_header(headers, "From") or "unknown"),
                "date":    _header(headers, "Date") or "",
                "unread":  "UNREAD" in data.get("labelIds", []),
            }

        fetched = await asyncio.gather(*[_preview(r) for r in refs])
        results = [m for m in fetched if m]
        return self.ok(query=query, email=email_addr, results=results, total=total)

    async def folder(self, ctx: Context, acc: dict, folder_name: str, max_results: int = 20) -> dict:
        email_addr = acc.get("email", "")
        label = FOLDER_LABELS.get(folder_name.lower())
        if label is None:
            return self.err(f"Unknown folder '{folder_name}'. Available: {list(FOLDER_LABELS.keys())}")
        params: dict = {"maxResults": min(max_results, 50)}
        if label:
            params["labelIds"] = label
        try:
            resp = await _api_get(ctx, "messages", acc, params=params)
            resp.raise_for_status()
            refs = resp.json().get("messages", [])
        except Exception as e:
            return self.err(f"Folder error: {e}")
        if not refs:
            return self.ok(folder=folder_name, email=email_addr, messages=[], total=0)
        messages = []
        for ref in refs:
            try:
                meta = await _api_get(ctx, f"messages/{ref['id']}", acc, params={
                    "format": "metadata", "metadataHeaders": ["From", "To", "Subject", "Date"],
                })
                if meta.status_code != 200:
                    continue
                data    = meta.json()
                headers = data.get("payload", {}).get("headers", [])
                messages.append({
                    "id":      ref["id"],
                    "subject": _header(headers, "Subject") or "(no subject)",
                    "from":    _short_sender(_header(headers, "From") or _header(headers, "To") or "unknown"),
                    "date":    _header(headers, "Date") or "",
                    "unread":  "UNREAD" in data.get("labelIds", []),
                })
            except Exception:
                continue
        return self.ok(folder=folder_name, email=email_addr, messages=messages, total=len(messages))

    async def get_thread(self, ctx: Context, acc: dict, thread_id: str) -> dict:
        email_addr = acc.get("email", "")
        resp = await _api_get(ctx, f"threads/{thread_id}", acc, params={"format": "full"})
        if resp.status_code == 404:
            return self.err(f"Thread {thread_id} not found.")
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
