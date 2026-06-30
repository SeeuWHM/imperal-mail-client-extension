"""Microsoft Mail Provider — write/mutate operations (mixin)."""
from __future__ import annotations

import logging

from imperal_sdk import Context

from .helpers import (
    MS_GRAPH_BASE,
    _graph_post, _graph_patch,
    _refresh_token_if_needed,
    _remove_from_cache, _update_read_in_cache, _save_last_read,
)

_MS_BATCH_URL = f"{MS_GRAPH_BASE}/$batch"
_MS_BATCH_SIZE = 20  # Graph JSON batching limit

log = logging.getLogger(__name__)

_MS_DEST_MAP: dict = {
    "inbox": "inbox", "spam": "junkemail", "junk": "junkemail",
    "trash": "deleteditems", "deleted": "deleteditems",
    "archive": "archive", "sent": "sentitems", "drafts": "drafts", "draft": "drafts",
}


def _recips(s: str) -> list[dict]:
    return [{"emailAddress": {"address": a.strip()}} for a in s.split(",") if a.strip()]


class MicrosoftWriteMixin:

    async def send(self, ctx: Context, acc: dict, to: str, subject: str, body: str,
                   cc: str = "", bcc: str = "") -> dict:
        email_addr = acc.get("email", "")
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
                           note="No Archive folder — moved to Deleted Items.")
        return self.err(f"Archive {resp.status_code}, Deleted Items {resp2.status_code}.")

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

    async def _find_folder_id(self, ctx: Context, acc: dict, name: str) -> str | None:
        """Look up a mail folder ID by display name."""
        try:
            acc = await _refresh_token_if_needed(ctx, acc)
            resp = await ctx.http.get(
                f"{MS_GRAPH_BASE}/me/mailFolders",
                headers={"Authorization": f"Bearer {acc['access_token']}"},
                params={"$select": "id,displayName", "$top": "100"},
            )
            if resp.status_code == 200:
                for folder in resp.json().get("value", []):
                    if folder.get("displayName", "").lower() == name.lower():
                        return folder.get("id")
        except Exception:
            pass
        return None

    async def move(self, ctx: Context, acc: dict, message_id: str,
                   from_folder: str = "INBOX", to_folder: str = "INBOX") -> dict:
        dest_id = _MS_DEST_MAP.get(to_folder.lower())
        if not dest_id:
            dest_id = await self._find_folder_id(ctx, acc, to_folder)
            if not dest_id:
                return self.err(
                    f"Outlook folder '{to_folder}' not found. "
                    "Check the exact name or create it first."
                )
        try:
            resp = await _graph_post(ctx, f"/me/messages/{message_id}/move", acc,
                                     json={"destinationId": dest_id})
            if resp.status_code in (200, 201):
                return self.ok(moved=True, message_id=message_id,
                               from_folder=from_folder, to_folder=to_folder)
            return self.err(f"Move failed ({resp.status_code}): {resp.text[:200]}")
        except Exception as e:
            return self.err(f"Move failed: {e}")

    async def bulk_apply_label(self, ctx: Context, acc: dict,
                                message_ids: list, label_name: str) -> dict:
        """Move multiple messages to a custom Outlook folder — one Graph $batch call per 20."""
        folder_id = _MS_DEST_MAP.get(label_name.lower()) or await self._find_folder_id(ctx, acc, label_name)
        if not folder_id:
            return self.err(f"Outlook folder '{label_name}' not found.")
        reqs = [{"method": "POST", "url": f"/me/messages/{mid}/move",
                 "headers": {"Content-Type": "application/json"},
                 "body": {"destinationId": folder_id}} for mid in message_ids]
        responses = await self._ms_batch(ctx, acc, reqs)
        ok = sum(1 for r in responses if r.get("status") in (200, 201))
        return self.ok(succeeded=ok, total=len(message_ids))

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
            return self.err(f"Purge failed ({resp.status_code}): {resp.text[:200]}")
        except Exception as e:
            return self.err(f"Purge failed: {e}")

    # ── Microsoft Graph JSON Batching (up to 20 requests per call) ──────────

    async def _ms_batch(self, ctx: Context, acc: dict, requests: list) -> list:
        """Send requests in chunks of 20 via Graph $batch. Returns all responses."""
        acc = await _refresh_token_if_needed(ctx, acc)
        responses = []
        for i in range(0, len(requests), _MS_BATCH_SIZE):
            chunk = requests[i:i + _MS_BATCH_SIZE]
            batch_body = {"requests": [{"id": str(j), **r} for j, r in enumerate(chunk)]}
            try:
                resp = await ctx.http.post(
                    _MS_BATCH_URL,
                    headers={"Authorization": f"Bearer {acc['access_token']}",
                             "Content-Type": "application/json"},
                    json=batch_body,
                )
                if resp.status_code == 200:
                    responses.extend(resp.json().get("responses", []))
            except Exception as e:
                log.warning("ms_batch chunk failed: %s", e)
        return responses

    async def bulk_mark_read(self, ctx: Context, acc: dict,
                              message_ids: list, read: bool = True) -> dict:
        reqs = [{"method": "PATCH", "url": f"/me/messages/{mid}",
                 "headers": {"Content-Type": "application/json"},
                 "body": {"isRead": read}} for mid in message_ids]
        responses = await self._ms_batch(ctx, acc, reqs)
        ok = sum(1 for r in responses if r.get("status") in (200, 204))
        return self.ok(succeeded=ok, total=len(message_ids))

    async def bulk_archive_messages(self, ctx: Context, acc: dict,
                                     message_ids: list) -> dict:
        reqs = [{"method": "POST", "url": f"/me/messages/{mid}/move",
                 "headers": {"Content-Type": "application/json"},
                 "body": {"destinationId": "archive"}} for mid in message_ids]
        responses = await self._ms_batch(ctx, acc, reqs)
        ok = sum(1 for r in responses if r.get("status") in (200, 201))
        return self.ok(succeeded=ok, total=len(message_ids))

    async def bulk_trash_messages(self, ctx: Context, acc: dict,
                                   message_ids: list) -> dict:
        reqs = [{"method": "POST", "url": f"/me/messages/{mid}/move",
                 "headers": {"Content-Type": "application/json"},
                 "body": {"destinationId": "deleteditems"}} for mid in message_ids]
        responses = await self._ms_batch(ctx, acc, reqs)
        ok = sum(1 for r in responses if r.get("status") in (200, 201))
        return self.ok(succeeded=ok, total=len(message_ids))

    async def bulk_star_messages(self, ctx: Context, acc: dict,
                                  message_ids: list, starred: bool = True) -> dict:
        flag_status = "flagged" if starred else "notFlagged"
        reqs = [{"method": "PATCH", "url": f"/me/messages/{mid}",
                 "headers": {"Content-Type": "application/json"},
                 "body": {"flag": {"flagStatus": flag_status}}} for mid in message_ids]
        responses = await self._ms_batch(ctx, acc, reqs)
        ok = sum(1 for r in responses if r.get("status") in (200, 204))
        return self.ok(succeeded=ok, total=len(message_ids))

    async def bulk_read_and_archive(self, ctx: Context, acc: dict,
                                     message_ids: list) -> dict:
        # Mark read then archive — two rounds of batching
        read_reqs = [{"method": "PATCH", "url": f"/me/messages/{mid}",
                      "headers": {"Content-Type": "application/json"},
                      "body": {"isRead": True}} for mid in message_ids]
        await self._ms_batch(ctx, acc, read_reqs)
        arch_reqs = [{"method": "POST", "url": f"/me/messages/{mid}/move",
                      "headers": {"Content-Type": "application/json"},
                      "body": {"destinationId": "archive"}} for mid in message_ids]
        responses = await self._ms_batch(ctx, acc, arch_reqs)
        ok = sum(1 for r in responses if r.get("status") in (200, 201))
        return self.ok(succeeded=ok, total=len(message_ids))

    async def bulk_purge_messages(self, ctx: Context, acc: dict,
                                   message_ids: list) -> dict:
        acc = await _refresh_token_if_needed(ctx, acc)
        reqs = [{"method": "DELETE", "url": f"/me/messages/{mid}"} for mid in message_ids]
        responses = await self._ms_batch(ctx, acc, reqs)
        ok = sum(1 for r in responses if r.get("status") in (204, 404))
        return self.ok(succeeded=ok, total=len(message_ids))
