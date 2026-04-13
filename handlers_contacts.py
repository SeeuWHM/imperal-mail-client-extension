"""Mail Client · Contact handlers."""
from __future__ import annotations

import logging
import re
import time as _time

from pydantic import BaseModel, Field

from app import chat, ActionResult, _get_acc, _no_account_error

from providers.helpers import CONTACTS_COLLECTION, SKELETON_INBOX, PEOPLE_API, _refresh_token_if_needed, _graph_get

log = logging.getLogger("mail")


# ─── Models ───────────────────────────────────────────────────────────── #

class ContactsListParams(BaseModel):
    """List contacts with optional search."""
    search: str = Field(default="", description="Filter by name or email")
    limit: int  = Field(default=50, description="Max contacts")


class AddContactParams(BaseModel):
    """Add a contact manually."""
    email: str = Field(description="Contact email address")
    name: str  = Field(default="", description="Contact name")


class DeleteContactParams(BaseModel):
    """Remove a contact."""
    email: str = Field(description="Contact email to delete")


class SyncContactsParams(BaseModel):
    """Sync contacts from a connected account."""
    account: str = Field(default="", description="Sync from this account")


# ─── Internal ─────────────────────────────────────────────────────────── #

def _parse_email_addr(raw: str) -> tuple[str, str]:
    raw = raw.strip()
    m = re.match(r'\s*(.+?)\s*<([^>]+)>\s*', raw)
    if m:
        return m.group(1).strip().strip("\"'"), m.group(2).strip().lower()
    return ("", raw.lower()) if "@" in raw else ("", "")


# ─── Handlers ─────────────────────────────────────────────────────────── #

@chat.function("contacts", action_type="read", description="Show email contacts.")
async def fn_contacts(ctx, params: ContactsListParams) -> ActionResult:
    docs = await ctx.store.query(CONTACTS_COLLECTION, limit=min(params.limit, 200))
    sq = params.search.lower() if params.search else ""
    contacts = [{"email": d.get("email", ""), "name": d.get("name", ""), "source": d.get("source", "manual")}
                for d in docs if not sq or sq in d.get("email", "").lower() or sq in d.get("name", "").lower()]
    contacts.sort(key=lambda c: c.get("name") or c["email"])
    return ActionResult.success(
        data={"contacts": contacts, "total": len(contacts)},
        summary=f"{len(contacts)} contacts" + (f" matching '{params.search}'" if params.search else ""),
    )


@chat.function("add_contact", action_type="write", description="Add a contact manually.")
async def fn_add_contact(ctx, params: AddContactParams) -> ActionResult:
    email = params.email.lower().strip()
    if "@" not in email:
        return ActionResult.error("Valid email address is required.")
    existing = await ctx.store.query(CONTACTS_COLLECTION, where={"email": email})
    if existing:
        return ActionResult.error(f"Contact {email} already exists.")
    now = int(_time.time())
    await ctx.store.create(CONTACTS_COLLECTION, {"email": email, "name": params.name.strip(), "source": "manual",
                                                  "account": "", "added_at": now, "last_seen": now})
    return ActionResult.success(data={"added": True, "email": email, "name": params.name}, summary=f"Contact {email} added")


@chat.function("sync_contacts", action_type="write",
               description="Import contacts from connected email — Google People, Outlook address book, or email history.")
async def fn_sync_contacts(ctx, params: SyncContactsParams) -> ActionResult:
    acc, _ = await _get_acc(ctx, params.account)
    if not acc:
        return _no_account_error()
    acc = await _refresh_token_if_needed(ctx, acc)
    provider, own = acc.get("provider", "oauth"), acc.get("email", "")
    found: list[dict] = []
    notes: list[str] = []

    if provider == "oauth":
        try:
            resp = await ctx.http.get(f"{PEOPLE_API}/people/me/connections?personFields=names,emailAddresses&pageSize=1000",
                                      headers={"Authorization": f"Bearer {acc['access_token']}"})
            if resp.status_code == 200:
                for p in resp.json().get("connections", []):
                    nm = p.get("names", [])
                    pname = nm[0].get("displayName", "") if nm else ""
                    for em in p.get("emailAddresses", []):
                        val = em.get("value", "").lower()
                        if val and val != own:
                            found.append({"email": val, "name": pname, "source": "google"})
            elif resp.status_code == 403:
                notes.append("Google Contacts scope not granted — reconnect. Falling back to history.")
        except Exception as e:
            notes.append(f"People API error: {e}")
    elif provider == "microsoft":
        try:
            resp = await _graph_get(ctx, "/me/contacts?$select=displayName,emailAddresses&$top=500", acc)
            if resp.status_code == 200:
                for c in resp.json().get("value", []):
                    pname = c.get("displayName", "")
                    for em in c.get("emailAddresses", []):
                        val = em.get("address", "").lower()
                        if val and val != own:
                            found.append({"email": val, "name": pname, "source": "outlook"})
            elif resp.status_code == 403:
                notes.append("Outlook Contacts scope not granted — reconnect. Falling back to history.")
        except Exception as e:
            notes.append(f"Graph contacts error: {e}")

    cache = ctx.skeleton_data.get(SKELETON_INBOX, {}) if hasattr(ctx, "skeleton_data") else {}
    for msg in cache.get(own, {}).get("messages", []):
        for field in ("from", "to", "cc"):
            for part in msg.get(field, "").split(","):
                pname, pemail = _parse_email_addr(part)
                if pemail and pemail != own:
                    found.append({"email": pemail, "name": pname, "source": "extracted"})

    seen: set[str] = set()
    deduped = [c for c in found if not (c["email"] in seen or seen.add(c["email"]))]  # type: ignore[func-returns-value]
    added, now = 0, int(_time.time())
    for c in deduped:
        exists = await ctx.store.query(CONTACTS_COLLECTION, where={"email": c["email"]})
        if exists:
            d = exists[0]
            updates = {"last_seen": now}
            if c.get("name") and not d.get("name"):
                updates["name"] = c["name"]
            await ctx.store.update(CONTACTS_COLLECTION, d.id, {**d.data, **updates})
        else:
            await ctx.store.create(CONTACTS_COLLECTION, {
                "email": c["email"], "name": c.get("name", ""), "source": c.get("source", "extracted"),
                "account": own, "added_at": now, "last_seen": now,
            })
            added += 1
    total = await ctx.store.count(CONTACTS_COLLECTION)
    data: dict = {"found": len(deduped), "added": added, "total": total}
    if notes:
        data["notes"] = notes
    return ActionResult.success(data=data, summary=f"Synced: {len(deduped)} found, {added} new, {total} total")


@chat.function("delete_contact", action_type="destructive", description="Remove a contact.")
async def fn_delete_contact(ctx, params: DeleteContactParams) -> ActionResult:
    email = params.email.lower().strip()
    docs = await ctx.store.query(CONTACTS_COLLECTION, where={"email": email})
    if not docs:
        return ActionResult.error(f"Contact {email} not found.")
    await ctx.store.delete(CONTACTS_COLLECTION, docs[0].id)
    return ActionResult.success(data={"deleted": True, "email": email}, summary=f"Contact {email} deleted")
