"""Mail Client · Contact handlers."""
from __future__ import annotations

import logging
import re
import time as _time

from app import chat
from imperal_sdk.chat import TaskCancelled
from imperal_sdk.chat.action_result import ActionResult
from ctx_helpers import _get_acc

from providers import get_provider
from providers.helpers import (
    CONTACTS_COLLECTION, PEOPLE_API, INBOX_FETCH_SIZE,
    _refresh_token_if_needed, _graph_get,
)

from schemas import (
    ContactAdded, ContactDeleted, ContactEntry, ContactsList, ContactsSyncResult,
    ContactsParams, AddContactParams, DeleteContactParams, AccountParam,
)

log = logging.getLogger("mail")


# ─── Internal ─────────────────────────────────────────────────────────── #


def _parse_email_addr(raw: str) -> tuple[str, str]:
    raw = raw.strip()
    m = re.match(r'\s*(.+?)\s*<([^>]+)>\s*', raw)
    if m:
        return m.group(1).strip().strip("\"'"), m.group(2).strip().lower()
    return ("", raw.lower()) if "@" in raw else ("", "")


# ─── impl_* business logic ────────────────────────────────────────────── #


async def impl_contacts(ctx, search: str = "", limit: int = 50) -> ContactsList:
    docs = await ctx.store.query(CONTACTS_COLLECTION, limit=min(limit, 200))
    sq = search.lower() if search else ""
    contacts = [
        ContactEntry(email=d.get("email", ""), name=d.get("name", ""), source=d.get("source", "manual"))
        for d in docs
        if not sq or sq in d.get("email", "").lower() or sq in d.get("name", "").lower()
    ]
    contacts.sort(key=lambda c: (c.name or c.email))
    return ContactsList(contacts=contacts, total=len(contacts))


async def impl_add_contact(ctx, email: str, name: str = "") -> ContactAdded:
    email_l = email.lower().strip()
    if "@" not in email_l:
        raise RuntimeError("Valid email address is required.")
    existing = await ctx.store.query(CONTACTS_COLLECTION, where={"email": email_l})
    if existing:
        raise RuntimeError(f"Contact {email_l} already exists.")
    now = int(_time.time())
    await ctx.store.create(CONTACTS_COLLECTION,
                           {"email": email_l, "name": name.strip(), "source": "manual",
                            "account": "", "added_at": now, "last_seen": now})
    return ContactAdded(added=True, email=email_l, name=name)


async def impl_sync_contacts(ctx, account: str = "") -> ContactsSyncResult:
    if account:
        acc_single, _ = await _get_acc(ctx, account)
        if not acc_single:
            raise RuntimeError("No email account connected. Connect one first.")
        target_accs = [acc_single]
    else:
        from providers.helpers import _all_accounts
        target_accs = await _all_accounts(ctx)
        if not target_accs:
            raise RuntimeError("No email account connected. Connect one first.")

    await ctx.progress(percent=0, message=f"Preparing to sync {len(target_accs)} account(s)…")

    # All own emails — never add self as a contact regardless of which account found them
    own_emails = {a.get("email", "").lower() for a in target_accs if a.get("email")}

    found: list[dict] = []
    notes: list[str] = []

    for acc_raw in target_accs:
        try:
            acc = await _refresh_token_if_needed(ctx, acc_raw)
        except Exception:
            acc = acc_raw
        prov_type = acc.get("provider", "oauth")
        own = acc.get("email", "")

        if prov_type == "oauth":
            try:
                resp = await ctx.http.get(
                    f"{PEOPLE_API}/people/me/connections?personFields=names,emailAddresses&pageSize=1000",
                    headers={"Authorization": f"Bearer {acc['access_token']}"},
                )
                if resp.status_code == 200:
                    for p in resp.json().get("connections", []):
                        nm = p.get("names", [])
                        pname = nm[0].get("displayName", "") if nm else ""
                        for em in p.get("emailAddresses", []):
                            val = em.get("value", "").lower()
                            if val and val not in own_emails:
                                found.append({"email": val, "name": pname, "source": "google", "account": own})
                elif resp.status_code == 403:
                    notes.append(f"Google Contacts scope not granted for {own} — reconnect.")
            except Exception as e:
                notes.append(f"People API error ({own}): {e}")
        elif prov_type == "microsoft":
            try:
                resp = await _graph_get(ctx, "/me/contacts?$select=displayName,emailAddresses&$top=500", acc)
                if resp.status_code == 200:
                    for c in resp.json().get("value", []):
                        pname = c.get("displayName", "")
                        for em in c.get("emailAddresses", []):
                            val = em.get("address", "").lower()
                            if val and val not in own_emails:
                                found.append({"email": val, "name": pname, "source": "outlook", "account": own})
                elif resp.status_code == 403:
                    notes.append(f"Outlook Contacts scope not granted for {own} — reconnect.")
            except Exception as e:
                notes.append(f"Graph contacts error ({own}): {e}")

        try:
            inbox = await get_provider(acc).fetch_inbox(ctx, acc, INBOX_FETCH_SIZE)
            for msg in inbox.get("messages", []) or []:
                for field in ("from", "to", "cc"):
                    for part in (msg.get(field) or "").split(","):
                        pname, pemail = _parse_email_addr(part)
                        if pemail and pemail not in own_emails:
                            found.append({"email": pemail, "name": pname, "source": "extracted", "account": own})
        except Exception as e:
            notes.append(f"Header harvest skipped ({own}): {str(e)[:80]}")

    await ctx.progress(percent=65, message=f"Deduplicating {len(found)} contacts…")
    seen: set[str] = set()
    deduped: list[dict] = []
    for c in found:
        if c["email"] not in seen:
            seen.add(c["email"])
            deduped.append(c)
    await ctx.progress(percent=75, message=f"Saving {len(deduped)} contacts to address book…")
    added, now = 0, int(_time.time())
    for c in deduped:
        exists = await ctx.store.query(CONTACTS_COLLECTION, where={"email": c["email"]})
        if exists.data:
            d = exists.data[0]
            updates = {"last_seen": now}
            if c.get("name") and not d.get("name"):
                updates["name"] = c["name"]
            await ctx.store.update(CONTACTS_COLLECTION, d.id, {**d.data, **updates})
        else:
            await ctx.store.create(CONTACTS_COLLECTION,
                                   {"email": c["email"], "name": c.get("name", ""),
                                    "source": c.get("source", "extracted"),
                                    "account": c.get("account", ""),
                                    "added_at": now, "last_seen": now})
            added += 1
    total = await ctx.store.count(CONTACTS_COLLECTION)
    await ctx.progress(percent=100, message=f"Done — {added} added, {int(total)} total.")
    return ContactsSyncResult(found=len(deduped), added=added, total=int(total), notes=notes)


async def impl_delete_contact(ctx, email: str) -> ContactDeleted:
    email_l = email.lower().strip()
    docs = await ctx.store.query(CONTACTS_COLLECTION, where={"email": email_l})
    if not docs.data:
        raise RuntimeError(f"Contact {email_l} not found.")
    await ctx.store.delete(CONTACTS_COLLECTION, docs.data[0].id)
    return ContactDeleted(deleted=True, email=email_l)


# ─── @chat.function wrappers ──────────────────────────────────────────── #


@chat.function("contacts", action_type="read",
               description="List address book contacts, optionally filtered by name or email fragment. Results sorted by name.")
async def fn_contacts(ctx, params: ContactsParams) -> ActionResult:
    try:
        r = await impl_contacts(ctx, search=params.search, limit=params.limit)
        return ActionResult.success(data=r.model_dump(), summary=f"{r.total} contact(s).")
    except RuntimeError as e:
        return ActionResult.error(str(e), retryable=False)


@chat.function("add_contact", action_type="write", event="contact.added",
               effects=["create:contact"],
               description="Save a new contact to the address book manually. Email is required; display name is optional.")
async def fn_add_contact(ctx, params: AddContactParams) -> ActionResult:
    try:
        r = await impl_add_contact(ctx, email=params.email, name=params.name)
        return ActionResult.success(data=r.model_dump(), summary=f"Added contact {r.email}.")
    except RuntimeError as e:
        return ActionResult.error(str(e), retryable=False)


@chat.function("sync_contacts", action_type="write", event="contacts.synced",
               effects=["create:contact", "update:contact"],
               description="Import contacts from the connected email account — Google People API, Microsoft Graph, or sender/CC header harvest from recent messages.")
async def fn_sync_contacts(ctx, params: AccountParam) -> ActionResult:
    try:
        r = await impl_sync_contacts(ctx, account=params.account)
        return ActionResult.success(data=r.model_dump(),
                                    summary=f"Synced contacts: {r.added} added, {r.total} total.")
    except TaskCancelled:
        return ActionResult.error("Sync cancelled.", retryable=True)
    except RuntimeError as e:
        return ActionResult.error(str(e), retryable=True)


@chat.function("delete_contact", action_type="destructive", event="contact.deleted",
               effects=["delete:contact"],
               description="Remove a contact from the address book by their exact email address.")
async def fn_delete_contact(ctx, params: DeleteContactParams) -> ActionResult:
    try:
        r = await impl_delete_contact(ctx, email=params.email)
        return ActionResult.success(data=r.model_dump(), summary=f"Deleted contact {r.email}.")
    except RuntimeError as e:
        return ActionResult.error(str(e), retryable=False)
