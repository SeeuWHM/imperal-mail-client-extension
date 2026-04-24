"""Mail Client · Contact handlers (SDK v2.0.0)."""
from __future__ import annotations

import logging
import re
import time as _time

from ctx_helpers import _get_acc

from providers import get_provider
from providers.helpers import (
    CONTACTS_COLLECTION, PEOPLE_API, INBOX_FETCH_SIZE,
    _refresh_token_if_needed, _graph_get,
)

from schemas import (
    ContactAdded, ContactDeleted, ContactEntry, ContactsList,
    ContactsSyncResult,
)

log = logging.getLogger("mail")


# ─── Internal ─────────────────────────────────────────────────────────── #


def _parse_email_addr(raw: str) -> tuple[str, str]:
    raw = raw.strip()
    m = re.match(r'\s*(.+?)\s*<([^>]+)>\s*', raw)
    if m:
        return m.group(1).strip().strip("\"'"), m.group(2).strip().lower()
    return ("", raw.lower()) if "@" in raw else ("", "")


# ─── Handlers ─────────────────────────────────────────────────────────── #


async def impl_contacts(
    ctx, search: str = "", limit: int = 50,
) -> ContactsList:
    docs = await ctx.store.query(CONTACTS_COLLECTION, limit=min(limit, 200))
    sq = search.lower() if search else ""
    contacts = [
        ContactEntry(
            email=d.get("email", ""),
            name=d.get("name", ""),
            source=d.get("source", "manual"),
        )
        for d in docs
        if not sq or sq in d.get("email", "").lower() or sq in d.get("name", "").lower()
    ]
    contacts.sort(key=lambda c: (c.name or c.email))
    return ContactsList(contacts=contacts, total=len(contacts))


async def impl_add_contact(
    ctx, email: str, name: str = "",
) -> ContactAdded:
    email_l = email.lower().strip()
    if "@" not in email_l:
        raise RuntimeError("Valid email address is required.")
    existing = await ctx.store.query(CONTACTS_COLLECTION, where={"email": email_l})
    if existing:
        raise RuntimeError(f"Contact {email_l} already exists.")
    now = int(_time.time())
    await ctx.store.create(
        CONTACTS_COLLECTION,
        {"email": email_l, "name": name.strip(), "source": "manual",
         "account": "", "added_at": now, "last_seen": now},
    )
    return ContactAdded(added=True, email=email_l, name=name)


async def impl_sync_contacts(
    ctx, account: str = "",
) -> ContactsSyncResult:
    acc, _ = await _get_acc(ctx, account)
    if not acc:
        raise RuntimeError("No email account connected. Connect one first.")
    acc = await _refresh_token_if_needed(ctx, acc)
    provider, own = acc.get("provider", "oauth"), acc.get("email", "")
    found: list[dict] = []
    notes: list[str] = []

    if provider == "oauth":
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
                        if val and val != own:
                            found.append({"email": val, "name": pname, "source": "google"})
            elif resp.status_code == 403:
                notes.append("Google Contacts scope not granted — reconnect. Falling back to history.")
        except Exception as e:
            notes.append(f"People API error: {e}")
    elif provider == "microsoft":
        try:
            resp = await _graph_get(
                ctx, "/me/contacts?$select=displayName,emailAddresses&$top=500", acc,
            )
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

    # Harvest addresses from recent inbox headers via a live fetch. Post SDK
    # v1.6.0 migration the skeleton no longer caches message bodies; we do one
    # fetch_inbox here to preserve the "from history" fallback. Bounded to
    # INBOX_FETCH_SIZE (20 msgs), errors are swallowed so the primary sync path
    # still succeeds.
    try:
        inbox = await get_provider(acc).fetch_inbox(ctx, acc, INBOX_FETCH_SIZE)
        for msg in inbox.get("messages", []) or []:
            for field in ("from", "to", "cc"):
                for part in (msg.get(field) or "").split(","):
                    pname, pemail = _parse_email_addr(part)
                    if pemail and pemail != own:
                        found.append({"email": pemail, "name": pname, "source": "extracted"})
    except Exception as e:
        notes.append(f"Header harvest skipped: {str(e)[:120]}")

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
                "email": c["email"], "name": c.get("name", ""),
                "source": c.get("source", "extracted"),
                "account": own, "added_at": now, "last_seen": now,
            })
            added += 1
    total = await ctx.store.count(CONTACTS_COLLECTION)
    return ContactsSyncResult(
        found=len(deduped),
        added=added,
        total=int(total),
        notes=notes,
    )


async def impl_delete_contact(ctx, email: str) -> ContactDeleted:
    email_l = email.lower().strip()
    docs = await ctx.store.query(CONTACTS_COLLECTION, where={"email": email_l})
    if not docs:
        raise RuntimeError(f"Contact {email_l} not found.")
    await ctx.store.delete(CONTACTS_COLLECTION, docs[0].id)
    return ContactDeleted(deleted=True, email=email_l)
