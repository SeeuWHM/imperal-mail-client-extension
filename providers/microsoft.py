"""Microsoft Mail Provider — Microsoft Graph API (OAuth2)."""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from imperal_sdk import Context

from .base import BaseMailProvider
from .microsoft_write import MicrosoftWriteMixin
from .helpers import (
    _graph_get, _graph_patch,
    _refresh_token_if_needed,
    _save_last_read, _update_read_in_cache,
    _strip_html, _norm_graph_msg,
    MS_GRAPH_BASE,
)

log = logging.getLogger(__name__)

_MS_PAGE_FOLDERS: dict = {
    "inbox": "inbox", "sent": "sentitems", "spam": "junkemail",
    "trash": "deleteditems", "drafts": "drafts", "archive": "archive",
}


class MicrosoftMailProvider(MicrosoftWriteMixin, BaseMailProvider):

    async def fetch_inbox(self, ctx: Context, acc: dict, max_results: int = 20) -> dict:
        email_addr = acc.get("email", "")
        acc = await _refresh_token_if_needed(ctx, acc)
        resp = await _graph_get(ctx, "/me/mailFolders/inbox/messages", acc, params={
            "$top": max_results, "$orderby": "receivedDateTime desc",
            "$select": "id,subject,from,receivedDateTime,isRead,conversationId,hasAttachments,bodyPreview",
        })
        resp.raise_for_status()
        messages = [_norm_graph_msg(m) for m in resp.json().get("value", [])]
        unread   = sum(1 for m in messages if m["unread"])
        return self.ok(email=email_addr, messages=messages, unread_count=unread, source="api")

    async def fetch_page(
        self, ctx: Context, acc: dict, folder: str, limit: int,
        cursor_data: dict | None,
    ) -> tuple[list[dict], dict | None, bool]:
        skip = cursor_data.get("skip", 0) if cursor_data else 0
        params: dict = {
            "$top": limit, "$skip": skip,
            "$orderby": "receivedDateTime desc",
            "$select": "id,conversationId,from,subject,bodyPreview,"
                       "receivedDateTime,isRead,flag,hasAttachments",
        }
        # Starred = flagged messages — $orderby is incompatible with cross-folder $filter
        if folder.lower() == "starred":
            params.pop("$orderby", None)
            params["$filter"] = "flag/flagStatus eq 'flagged'"
            endpoint = "/me/messages"
        else:
            ms_folder = _MS_PAGE_FOLDERS.get(folder.lower(), "inbox")
            endpoint = f"/me/mailFolders/{ms_folder}/messages"
        resp = await _graph_get(ctx, endpoint, acc, params=params)
        resp.raise_for_status()
        data = resp.json()
        raw_msgs = data.get("value", [])
        messages = [_norm_graph_msg(m) for m in raw_msgs]
        has_more = "@odata.nextLink" in data or len(raw_msgs) == limit
        next_cursor = {"skip": skip + limit} if has_more else None
        return messages, next_cursor, has_more

    async def get_unread_count(self, ctx: Context, acc: dict, folder: str = "inbox") -> int:
        try:
            if folder.lower() == "starred":
                # Count unread flagged messages
                resp = await _graph_get(ctx, "/me/messages", acc, params={
                    "$filter": "flag/flagStatus eq 'flagged' and isRead eq false",
                    "$top": 1, "$count": "true",
                    "$select": "id",
                })
                resp.raise_for_status()
                return resp.json().get("@odata.count", 0)
            ms_folder = _MS_PAGE_FOLDERS.get(folder.lower(), "inbox")
            resp = await _graph_get(ctx, f"/me/mailFolders/{ms_folder}", acc)
            resp.raise_for_status()
            return resp.json().get("unreadItemCount", 0)
        except Exception:
            return 0

    async def get_folder_stats(self, ctx: Context, acc: dict, folder: str = "inbox") -> dict:
        try:
            if folder.lower() == "starred":
                return {"total": 0, "unread": await self.get_unread_count(ctx, acc, folder)}
            ms_folder = _MS_PAGE_FOLDERS.get(folder.lower(), "inbox")
            resp = await _graph_get(ctx, f"/me/mailFolders/{ms_folder}", acc)
            resp.raise_for_status()
            data = resp.json()
            return {"total": data.get("totalItemCount", 0), "unread": data.get("unreadItemCount", 0)}
        except Exception:
            return {"total": 0, "unread": 0}

    async def get_counts(self, ctx: Context, acc: dict) -> dict:
        """Normalized counts. total = whole mailbox via /me/messages $count
        (ConsistencyLevel: eventual). spam = JunkEmail, archive = Archive folder."""
        inbox = await self.get_folder_stats(ctx, acc, "inbox")
        spam  = await self.get_folder_stats(ctx, acc, "spam")
        arch  = await self.get_folder_stats(ctx, acc, "archive")
        total = int(inbox.get("total", 0) or 0)
        try:
            acc = await _refresh_token_if_needed(ctx, acc)
            resp = await ctx.http.get(
                f"{MS_GRAPH_BASE}/me/messages",
                headers={"Authorization": f"Bearer {acc['access_token']}",
                         "ConsistencyLevel": "eventual"},
                params={"$top": 1, "$count": "true", "$select": "id"},
            )
            if resp.status_code == 200:
                total = int(resp.json().get("@odata.count", total) or total)
        except Exception:
            pass
        return {
            "total":       total,
            "inbox_total": int(inbox.get("total", 0) or 0),
            "unread":      int(inbox.get("unread", 0) or 0),
            "spam":        int(spam.get("total", 0) or 0),
            "archive":     int(arch.get("total", 0) or 0),
        }

    async def get_today_count(self, ctx: Context, acc: dict) -> int:
        """Messages received in the current UTC day (Inbox), via Graph $count + $filter."""
        midnight = datetime.now(timezone.utc).strftime("%Y-%m-%dT00:00:00Z")
        try:
            acc = await _refresh_token_if_needed(ctx, acc)
            resp = await ctx.http.get(
                f"{MS_GRAPH_BASE}/me/mailFolders/inbox/messages",
                headers={"Authorization": f"Bearer {acc['access_token']}",
                         "ConsistencyLevel": "eventual"},
                params={"$top": 1, "$count": "true", "$select": "id",
                        "$filter": f"receivedDateTime ge {midnight}"},
            )
            if resp.status_code == 200:
                return int(resp.json().get("@odata.count", 0) or 0)
        except Exception:
            pass
        return 0

    async def read_email(self, ctx: Context, acc: dict, message_id: str) -> dict:
        email_addr = acc.get("email", "")
        resp = await _graph_get(ctx, f"/me/messages/{message_id}", acc, params={
            "$select": "id,subject,from,toRecipients,ccRecipients,receivedDateTime,isRead,body,conversationId,hasAttachments",
            "$expand": "attachments($select=id,name,size,contentType)",
        })
        if resp.status_code == 404:
            return self.err(f"Message {message_id} not found.")
        resp.raise_for_status()
        msg       = resp.json()
        from_data = msg.get("from", {}).get("emailAddress", {})
        to_list   = msg.get("toRecipients", [])
        to_addr   = ", ".join(
            r.get("emailAddress", {}).get("address", "")
            for r in to_list if r.get("emailAddress", {}).get("address")
        )
        cc_list = msg.get("ccRecipients", [])
        cc_addr = ", ".join(
            r.get("emailAddress", {}).get("address", "")
            for r in cc_list if r.get("emailAddress", {}).get("address")
        )
        body_obj  = msg.get("body", {})
        body      = body_obj.get("content", "")
        body_type = "html" if body_obj.get("contentType", "text").lower() == "html" else "text"

        attachments = []
        for att in msg.get("attachments", []):
            if att.get("@odata.type") == "#microsoft.graph.fileAttachment":
                attachments.append({
                    "id": att.get("id", ""), "filename": att.get("name", ""),
                    "size_kb": round(att.get("size", 0) / 1024, 1),
                    "mime_type": att.get("contentType", "application/octet-stream"),
                })

        try:
            await _graph_patch(ctx, f"/me/messages/{message_id}", acc, json={"isRead": True})
            await _update_read_in_cache(ctx, email_addr, message_id, is_read=True)
        except Exception:
            pass

        await _save_last_read(ctx, message_id, msg.get("subject", ""),
                              from_data.get("address", ""), "", msg.get("conversationId", ""),
                              account=email_addr)

        result: dict = {
            "message_id": message_id,
            "subject":    msg.get("subject") or "(no subject)",
            "from":       from_data.get("address", "unknown"),
            "to":         to_addr,
            "cc":         cc_addr,
            "date":       msg.get("receivedDateTime", ""),
            "body":       body,
            "thread_id":  msg.get("conversationId", ""),
            "body_type":  body_type,
        }
        if attachments: result["attachments"] = attachments
        return self.ok(**result)

    async def search(self, ctx: Context, acc: dict, query: str, max_results: int = 10) -> dict:
        email_addr = acc.get("email", "")
        acc = await _refresh_token_if_needed(ctx, acc)
        # ConsistencyLevel: eventual is required for $count with $search in Graph API
        resp = await ctx.http.get(
            f"{MS_GRAPH_BASE}/me/messages",
            headers={
                "Authorization": f"Bearer {acc['access_token']}",
                "ConsistencyLevel": "eventual",
            },
            params={
                "$search": f'"{query}"',
                "$top": min(max_results, 250),
                "$count": "true",
                "$select": "id,subject,from,receivedDateTime,isRead",
            },
        )
        resp.raise_for_status()
        data = resp.json()
        results = [_norm_graph_msg(m) for m in data.get("value", [])]
        total = data.get("@odata.count", len(results))
        return self.ok(query=query, email=email_addr, results=results, total=total)

    async def folder(self, ctx: Context, acc: dict, folder_name: str, max_results: int = 20) -> dict:
        email_addr = acc.get("email", "")
        ms_folder  = _MS_PAGE_FOLDERS.get(folder_name.lower(), "inbox")
        params: dict = {
            "$top": min(max_results, 50), "$orderby": "receivedDateTime desc",
            "$select": "id,subject,from,receivedDateTime,isRead",
        }
        if folder_name.lower() == "unread":  params["$filter"] = "isRead eq false"
        if folder_name.lower() == "starred": params["$filter"] = "flag/flagStatus eq 'flagged'"
        resp = await _graph_get(ctx, f"/me/mailFolders/{ms_folder}/messages", acc, params=params)
        resp.raise_for_status()
        messages = [_norm_graph_msg(m) for m in resp.json().get("value", [])]
        return self.ok(folder=folder_name, email=email_addr, messages=messages, total=len(messages))

    async def get_thread(self, ctx: Context, acc: dict, thread_id: str) -> dict:
        email_addr = acc.get("email", "")
        resp = await _graph_get(ctx, "/me/messages", acc, params={
            "$filter": f"conversationId eq '{thread_id}'",
            "$orderby": "receivedDateTime asc",
            "$select": "id,subject,from,receivedDateTime,isRead,body",
            "$top": 50,
        })
        resp.raise_for_status()
        messages = []
        for m in resp.json().get("value", []):
            from_data = m.get("from", {}).get("emailAddress", {})
            body_obj  = m.get("body", {})
            body      = body_obj.get("content", "")
            if body_obj.get("contentType", "text").lower() == "html": body = _strip_html(body)
            messages.append({
                "id":      m.get("id", ""),
                "subject": m.get("subject") or "(no subject)",
                "from":    from_data.get("address", "unknown"),
                "date":    m.get("receivedDateTime", ""),
                "unread":  not m.get("isRead", True),
                "body":    body[:2000],
            })
        return self.ok(thread_id=thread_id, email=email_addr, messages=messages, total=len(messages))

