"""Google Mail Provider — write/action operations (send, reply, forward, manage)."""
from __future__ import annotations

from imperal_sdk import Context

from .helpers import (
    GMAIL_API,
    _api_get, _api_post,
    _refresh_token_if_needed,
    _remove_from_cache, _update_read_in_cache,
    _build_message, _decode_body, _header, _short_sender,
)


class GoogleWriteMixin:

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
        if thread_id:
            payload["threadId"] = thread_id
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
            data      = resp.json()
            headers   = data.get("payload", {}).get("headers", [])
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
        return self.ok(deleted=True, message_id=message_id,
                       note="Can be restored from Trash within 30 days.")

    async def mark_read(self, ctx: Context, acc: dict, message_id: str, read: bool = True) -> dict:
        email_addr = acc.get("email", "")
        payload = {"removeLabelIds": ["UNREAD"]} if read else {"addLabelIds": ["UNREAD"]}
        resp = await _api_post(ctx, f"messages/{message_id}/modify", acc, json=payload)
        if resp.status_code == 200:
            await _update_read_in_cache(ctx, email_addr, message_id, is_read=read)
            return self.ok(marked="read" if read else "unread", message_id=message_id)
        return self.err(f"Mark failed {resp.status_code}")

    async def star(self, ctx: Context, acc: dict, message_id: str, starred: bool = True) -> dict:
        payload = {"addLabelIds": ["STARRED"]} if starred else {"removeLabelIds": ["STARRED"]}
        resp = await _api_post(ctx, f"messages/{message_id}/modify", acc, json=payload)
        if resp.status_code == 200:
            return self.ok(**{"starred" if starred else "unstarred": True, "message_id": message_id})
        return self.err(f"Star failed {resp.status_code}")

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

    async def create_folder(self, ctx: Context, acc: dict, folder_name: str) -> dict:
        """Create a Gmail label (labels are Gmail's folder equivalent)."""
        try:
            resp = await _api_post(ctx, "labels", acc, json={
                "name": folder_name,
                "labelListVisibility": "labelShow",
                "messageListVisibility": "show",
            })
            if resp.status_code in (200, 201):
                d = resp.json()
                return self.ok(created=True, folder_id=d.get("id"),
                               folder_name=d.get("name", folder_name))
            if resp.status_code == 409:
                return self.err(f"Gmail label '{folder_name}' already exists.")
            return self.err(f"Create label failed {resp.status_code}: {resp.text[:200]}")
        except Exception as e:
            return self.err(f"Gmail create_folder failed: {e}")

    async def delete_folder(self, ctx: Context, acc: dict, folder_name: str) -> dict:
        """Delete a Gmail label by name (emails inside are NOT deleted)."""
        try:
            acc = await _refresh_token_if_needed(ctx, acc)
            # List all labels to find the ID by name
            list_resp = await ctx.http.get(
                f"{GMAIL_API}/labels",
                headers={"Authorization": f"Bearer {acc['access_token']}"},
            )
            if list_resp.status_code != 200:
                return self.err(f"Could not list labels: {list_resp.status_code}")
            labels = list_resp.json().get("labels", [])
            label = next(
                (l for l in labels if l.get("name", "").lower() == folder_name.lower()),
                None,
            )
            if not label:
                return self.err(f"Gmail label '{folder_name}' not found.")
            # Prevent deleting system labels
            if label.get("type") == "system":
                return self.err(
                    f"Cannot delete system label '{folder_name}' (INBOX, Sent, Trash, etc.)."
                )
            del_resp = await ctx.http.delete(
                f"{GMAIL_API}/labels/{label['id']}",
                headers={"Authorization": f"Bearer {acc['access_token']}"},
            )
            if del_resp.status_code in (200, 204, 404):
                return self.ok(deleted=True, folder_name=folder_name)
            return self.err(f"Delete label failed {del_resp.status_code}: {del_resp.text[:200]}")
        except Exception as e:
            return self.err(f"Gmail delete_folder failed: {e}")
