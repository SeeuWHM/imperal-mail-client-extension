"""Microsoft Mail Provider — Microsoft Graph API (OAuth2)."""
from __future__ import annotations

import logging

from imperal_sdk import Context

from .base import BaseMailProvider
from .helpers import (
    MS_GRAPH_BASE,
    _graph_get, _graph_post, _graph_patch,
    _refresh_token_if_needed,
    _remove_from_cache, _update_read_in_cache, _save_last_read,
    _strip_html, _norm_graph_msg, _short_sender,
)

log = logging.getLogger(__name__)

MS_FOLDER_MAP: dict = {
    "sent":    "sentitems", "spam":    "junkemail",
    "trash":   "deleteditems", "drafts": "drafts", "draft": "drafts",
    "all":     "inbox",    "archive": "archive",
    "unread":  "inbox",    "starred": "inbox",
}

_MS_PAGE_FOLDERS: dict = {
    "inbox": "inbox", "sent": "sentitems", "spam": "junkemail",
    "trash": "deleteditems", "drafts": "drafts", "archive": "archive",
}


class MicrosoftMailProvider(BaseMailProvider):

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
        folder_lc = folder.lower()
        ms_folder = _MS_PAGE_FOLDERS.get(folder_lc, "inbox")
        params: dict = {
            "$top": limit, "$skip": skip,
            "$orderby": "receivedDateTime desc",
            "$select": "id,conversationId,from,subject,bodyPreview,"
                       "receivedDateTime,isRead,flag,hasAttachments",
        }
        # Outlook has no dedicated "starred" or "unread" mailFolder —
        # filter flagged/unread messages inside the inbox folder.
        if folder_lc == "starred":
            params["$filter"] = "flag/flagStatus eq 'flagged'"
        elif folder_lc == "unread":
            params["$filter"] = "isRead eq false"
        resp = await _graph_get(ctx, f"/me/mailFolders/{ms_folder}/messages", acc, params=params)
        resp.raise_for_status()
        data = resp.json()
        raw_msgs = data.get("value", [])
        messages = [_norm_graph_msg(m) for m in raw_msgs]
        has_more = "@odata.nextLink" in data or len(raw_msgs) == limit
        next_cursor = {"skip": skip + limit} if has_more else None
        return messages, next_cursor, has_more

    async def get_unread_count(self, ctx: Context, acc: dict, folder: str = "inbox") -> int:
        ms_folder = _MS_PAGE_FOLDERS.get(folder.lower(), "inbox")
        try:
            resp = await _graph_get(ctx, f"/me/mailFolders/{ms_folder}", acc)
            resp.raise_for_status()
            return resp.json().get("unreadItemCount", 0)
        except Exception:
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
        to_addr   = to_list[0].get("emailAddress", {}).get("address", "") if to_list else ""
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
                              from_data.get("address", ""), "", msg.get("conversationId", ""))

        result: dict = {
            "message_id": message_id,
            "subject":    msg.get("subject") or "(no subject)",
            "from":       from_data.get("address", "unknown"),
            "to":         to_addr,
            "date":       msg.get("receivedDateTime", ""),
            "body":       body[:4000],
            "thread_id":  msg.get("conversationId", ""),
            "body_type":  body_type,
        }
        if attachments: result["attachments"] = attachments
        return self.ok(**result)

    async def send(self, ctx: Context, acc: dict, to: str, subject: str, body: str,
                   cc: str = "", bcc: str = "") -> dict:
        email_addr = acc.get("email", "")
        def _recips(s: str): return [{"emailAddress": {"address": a.strip()}} for a in s.split(",") if a.strip()]
        payload: dict = {
            "message": {
                "subject": subject, "body": {"contentType": "Text", "content": body},
                "toRecipients": _recips(to),
            }
        }
        if cc:  payload["message"]["ccRecipients"]  = _recips(cc)
        if bcc: payload["message"]["bccRecipients"] = _recips(bcc)
        resp = await _graph_post(ctx, "/me/sendMail", acc, json=payload)
        if resp.status_code == 202:
            return self.ok(sent=True, to=to, subject=subject, from_=email_addr)
        return self.err(f"Send failed {resp.status_code}: {resp.text[:200]}")

    async def reply(self, ctx: Context, acc: dict, message_id: str, body: str,
                    to: str = "", cc: str = "", bcc: str = "") -> dict:
        email_addr = acc.get("email", "")
        def _recips(s: str): return [{"emailAddress": {"address": a.strip()}} for a in s.split(",") if a.strip()]
        payload: dict = {"message": {"body": {"contentType": "Text", "content": body}}}
        if to:  payload["message"]["toRecipients"]  = _recips(to)
        if cc:  payload["message"]["ccRecipients"]  = _recips(cc)
        if bcc: payload["message"]["bccRecipients"] = _recips(bcc)
        resp = await _graph_post(ctx, f"/me/messages/{message_id}/reply", acc, json=payload)
        if resp.status_code == 202:
            return self.ok(sent=True, to=to or "original sender",
                           bcc=bcc if bcc else None, in_reply_to=message_id, from_=email_addr)
        return self.err(f"Reply failed {resp.status_code}: {resp.text[:200]}")

    async def forward(self, ctx: Context, acc: dict, message_id: str,
                      to: str, comment: str = "") -> dict:
        def _recips(s: str): return [{"emailAddress": {"address": a.strip()}} for a in s.split(",") if a.strip()]
        payload: dict = {"toRecipients": _recips(to)}
        if comment: payload["comment"] = comment
        resp = await _graph_post(ctx, f"/me/messages/{message_id}/forward", acc, json=payload)
        if resp.status_code == 202:
            return self.ok(forwarded=True, to=to, message_id=message_id)
        return self.err(f"Forward failed {resp.status_code}: {resp.text[:200]}")

    async def archive(self, ctx: Context, acc: dict, message_id: str) -> dict:
        email_addr = acc.get("email", "")
        resp = await _graph_post(ctx, f"/me/messages/{message_id}/move", acc,
                                 json={"destinationId": "archive"})
        if resp.status_code == 201:
            await _remove_from_cache(ctx, email_addr, message_id)
            return self.ok(archived=True, message_id=message_id, folder="Archive")
        if resp.status_code not in (404, 400):
            return self.err(f"Archive failed {resp.status_code}: {resp.text[:200]}")
        resp2 = await _graph_post(ctx, f"/me/messages/{message_id}/move", acc,
                                  json={"destinationId": "deleteditems"})
        if resp2.status_code == 201:
            await _remove_from_cache(ctx, email_addr, message_id)
            return self.ok(archived=True, message_id=message_id, folder="Deleted Items",
                           note="Your Outlook account has no Archive folder. Email moved to Deleted Items instead.")
        return self.err(f"Could not archive: Archive {resp.status_code}, Deleted Items {resp2.status_code}.")

    async def delete(self, ctx: Context, acc: dict, message_id: str) -> dict:
        email_addr = acc.get("email", "")
        resp = await _graph_post(ctx, f"/me/messages/{message_id}/move", acc,
                                 json={"destinationId": "deleteditems"})
        if resp.status_code == 201:
            await _remove_from_cache(ctx, email_addr, message_id)
            return self.ok(deleted=True, message_id=message_id)
        return self.err(f"Delete failed {resp.status_code}: {resp.text[:200]}")

    async def mark_read(self, ctx: Context, acc: dict, message_id: str, read: bool = True) -> dict:
        email_addr = acc.get("email", "")
        resp = await _graph_patch(ctx, f"/me/messages/{message_id}", acc, json={"isRead": read})
        if resp.status_code in (200, 204):
            await _update_read_in_cache(ctx, email_addr, message_id, is_read=read)
            return self.ok(marked="read" if read else "unread", message_id=message_id)
        return self.err(f"Mark failed {resp.status_code}")

    async def star(self, ctx: Context, acc: dict, message_id: str, starred: bool = True) -> dict:
        flag_status = "flagged" if starred else "notFlagged"
        resp = await _graph_patch(ctx, f"/me/messages/{message_id}", acc,
                                  json={"flag": {"flagStatus": flag_status}})
        if resp.status_code in (200, 204):
            return self.ok(**{"starred" if starred else "unstarred": True, "message_id": message_id})
        return self.err(f"Star failed {resp.status_code}")

    async def search(self, ctx: Context, acc: dict, query: str, max_results: int = 10) -> dict:
        email_addr = acc.get("email", "")
        resp = await _graph_get(ctx, "/me/messages", acc, params={
            "$search": f'"{query}"', "$top": min(max_results, 20),
            "$select": "id,subject,from,receivedDateTime,isRead",
        })
        resp.raise_for_status()
        results = [_norm_graph_msg(m) for m in resp.json().get("value", [])]
        return self.ok(query=query, email=email_addr, results=results, total=len(results))

    async def folder(self, ctx: Context, acc: dict, folder_name: str, max_results: int = 20) -> dict:
        email_addr = acc.get("email", "")
        ms_folder  = MS_FOLDER_MAP.get(folder_name.lower(), "inbox")
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

    async def move(self, ctx: Context, acc: dict, message_id: str,
                   from_folder: str = "INBOX", to_folder: str = "INBOX") -> dict:
        DEST_MAP = {
            "inbox": "inbox", "spam": "junkemail", "junk": "junkemail",
            "trash": "deleteditems", "deleted": "deleteditems",
            "archive": "archive", "sent": "sentitems", "drafts": "drafts", "draft": "drafts",
        }
        dest_id = DEST_MAP.get(to_folder.lower(), to_folder)
        try:
            resp = await _graph_post(ctx, f"/me/messages/{message_id}/move", acc,
                                     json={"destinationId": dest_id})
            if resp.status_code in (200, 201):
                return self.ok(moved=True, message_id=message_id,
                               from_folder=from_folder, to_folder=to_folder)
            return self.err(f"Outlook move failed ({resp.status_code}): {resp.text[:200]}")
        except Exception as e:
            return self.err(f"Outlook move failed: {e}")

    async def purge(self, ctx: Context, acc: dict, message_id: str,
                    from_folder: str = "DeletedItems") -> dict:
        try:
            acc  = await _refresh_token_if_needed(ctx, acc)
            resp = await ctx.http.delete(
                f"{MS_GRAPH_BASE}/me/messages/{message_id}",
                headers={"Authorization": f"Bearer {acc['access_token']}"},
            )
            if resp.status_code in (204, 404):
                return self.ok(purged=True, message_id=message_id)
            return self.err(f"Outlook permanent delete failed ({resp.status_code}): {resp.text[:200]}")
        except Exception as e:
            return self.err(f"Outlook purge failed: {e}")
