"""Mail Client · Connect & account handlers (SDK v2.0.0)."""
from __future__ import annotations

import asyncio
import base64
import json
import logging

from urllib.parse import urlencode

from ctx_helpers import _get_acc

from providers import get_provider  # noqa: F401  — used by sync_contacts path
from providers.helpers import (
    _all_accounts,
    COLLECTION,
    GMAIL_CLIENT_ID, GMAIL_REDIRECT_URI, GOOGLE_AUTH_URL, GMAIL_SCOPE,
    MS_CLIENT_ID, MS_REDIRECT_URI, MS_AUTH_URL, MS_SCOPE,
    YAHOO_CLIENT_ID, YAHOO_REDIRECT_URI, YAHOO_AUTH_URL, YAHOO_SCOPE,
    _encrypt_password, _detect_imap_settings,
    _invalidate_first_page,
    _unread_summary_key,
)
from providers.imap import _sync_imap_test
from cache_model_defs import UnreadSummary

from schemas import (
    AccountDisconnected, AccountSwitched, AccountsStatus, ConnectImapResult,
    ConnectOAuthResult, MailAccount,
)

log = logging.getLogger("mail")


# ─── Internal ─────────────────────────────────────────────────────────── #


def _oauth_state(ctx, provider: str) -> str:
    return base64.urlsafe_b64encode(
        json.dumps({"user_id": str(ctx.user.id),
                    "tenant_id": getattr(ctx.user, "tenant_id", "default"),
                    "provider": provider}).encode()
    ).decode()


# ─── Connect Handlers ─────────────────────────────────────────────────── #


async def impl_connect(ctx) -> ConnectOAuthResult:
    accounts = await _all_accounts(ctx)
    oauth = [a for a in accounts if a.get("provider", "oauth") == "oauth"]
    if oauth:
        active = next((a for a in oauth if a.get("is_active")), oauth[0])
        return ConnectOAuthResult(
            already_connected=True,
            email=active.get("email"),
            total=len(accounts),
        )
    if not GMAIL_CLIENT_ID:
        raise RuntimeError("Google OAuth not configured.")
    url = GOOGLE_AUTH_URL + "?" + urlencode({
        "client_id": GMAIL_CLIENT_ID, "redirect_uri": GMAIL_REDIRECT_URI,
        "response_type": "code", "scope": GMAIL_SCOPE,
        "access_type": "offline", "prompt": "consent", "state": _oauth_state(ctx, "oauth"),
    })
    return ConnectOAuthResult(
        auth_url=url,
        instruction="Open link to authorise Google.",
    )


async def impl_connect_microsoft(ctx) -> ConnectOAuthResult:
    accounts = await _all_accounts(ctx)
    ms = [a for a in accounts if a.get("provider") == "microsoft"]
    if ms:
        active = next((a for a in ms if a.get("is_active")), ms[0])
        return ConnectOAuthResult(
            already_connected=True,
            email=active.get("email"),
        )
    if not MS_CLIENT_ID:
        raise RuntimeError("Microsoft OAuth not configured.")
    url = MS_AUTH_URL + "?" + urlencode({
        "client_id": MS_CLIENT_ID, "response_type": "code", "redirect_uri": MS_REDIRECT_URI,
        "scope": MS_SCOPE, "response_mode": "query", "state": _oauth_state(ctx, "microsoft"),
    })
    return ConnectOAuthResult(
        auth_url=url,
        instruction="Open link to authorise Microsoft.",
    )


async def impl_connect_yahoo(ctx) -> ConnectOAuthResult:
    accounts = await _all_accounts(ctx)
    yahoo = [a for a in accounts if a.get("provider") == "yahoo"]
    if yahoo:
        active = next((a for a in yahoo if a.get("is_active")), yahoo[0])
        return ConnectOAuthResult(
            already_connected=True,
            email=active.get("email"),
        )
    if not YAHOO_CLIENT_ID:
        raise RuntimeError("Yahoo OAuth not configured.")
    url = YAHOO_AUTH_URL + "?" + urlencode({
        "client_id": YAHOO_CLIENT_ID, "redirect_uri": YAHOO_REDIRECT_URI,
        "response_type": "code", "scope": YAHOO_SCOPE, "state": _oauth_state(ctx, "yahoo"),
    })
    return ConnectOAuthResult(
        auth_url=url,
        instruction="Open link to authorise Yahoo/AOL.",
    )


async def impl_connect_imap(
    ctx, email_addr: str, password: str, imap_host: str = "",
    smtp_host: str = "", imap_port: int = 0, smtp_port: int = 0,
) -> ConnectImapResult:
    detected = _detect_imap_settings(email_addr)
    imap_h = imap_host or detected["imap_host"]
    imap_p = imap_port or detected["imap_port"]
    smtp_h = smtp_host or detected["smtp_host"]
    smtp_p = smtp_port or detected["smtp_port"]
    ok, err = await asyncio.to_thread(_sync_imap_test, email_addr, password, imap_h, imap_p)
    if not ok:
        raise RuntimeError(f"IMAP failed: {err}")
    # Create the new account FIRST, then deactivate others.
    # If create fails, the user still has their existing active account.
    await ctx.store.create(COLLECTION, {
        "email": email_addr, "provider": "imap", "is_active": True,
        "imap_host": imap_h, "imap_port": imap_p, "smtp_host": smtp_h, "smtp_port": smtp_p,
        "password": _encrypt_password(password), "password_encrypted": True,
    })
    accounts = await _all_accounts(ctx)
    for d in accounts:
        _data = d.data if hasattr(d, "data") else d
        _id = d.id if hasattr(d, "id") else d["doc_id"]
        if _data.get("email") != email_addr:
            await ctx.store.update(COLLECTION, _id, {**_data, "is_active": False})
    return ConnectImapResult(
        connected=True,
        email=email_addr,
        imap_server=imap_h,
    )


# ─── Account Handlers ─────────────────────────────────────────────────── #


async def impl_status(ctx) -> AccountsStatus:
    accounts = await _all_accounts(ctx)
    if not accounts:
        return AccountsStatus(connected=False, accounts=[], total=0)

    labels = {"oauth": "Google", "microsoft": "Microsoft",
              "yahoo": "Yahoo / AOL", "imap": "IMAP"}
    result: list[MailAccount] = []
    for a in accounts:
        email = a.get("email", "?")
        unread = 0
        # Prefer ctx.cache-backed summary; fall back to store-persisted unread_count
        # (skeleton_refresh writes that field every ttl=60s).
        try:
            summary = await ctx.cache.get(_unread_summary_key(email, "INBOX"), UnreadSummary)
            if summary:
                unread = summary.unread_count
            else:
                unread = int(a.get("unread_count", 0) or 0)
        except Exception:
            unread = int(a.get("unread_count", 0) or 0)

        result.append(MailAccount(
            email=email,
            provider=labels.get(a.get("provider", "oauth"), "Unknown"),
            is_active=bool(a.get("is_active", False)),
            unread_count=unread,
        ))
    return AccountsStatus(connected=True, accounts=result, total=len(result))


async def impl_switch_account(ctx, account: str) -> AccountSwitched:
    docs = await ctx.store.query(COLLECTION)
    if not docs:
        raise RuntimeError("No email account connected.")
    target = next((d for d in docs if d.id == account or d.get("email") == account), None)
    if not target:
        raise RuntimeError(f"Account not found. Available: {[d.get('email') for d in docs]}")
    for d in docs:
        new_active = d.id == target.id
        if d.get("is_active") != new_active:
            await ctx.store.update(COLLECTION, d.id, {**d.data, "is_active": new_active})
    return AccountSwitched(switched=True, active_account=target.get("email"))


async def impl_disconnect(ctx, account: str) -> AccountDisconnected:
    docs = await ctx.store.query(COLLECTION)
    target = next((d for d in docs if d.id == account or d.get("email") == account), None)
    if not target:
        raise RuntimeError("Account not found.")
    email = target.get("email", "")
    await ctx.store.delete(COLLECTION, target.id)
    await _invalidate_first_page(ctx, email, "INBOX")
    return AccountDisconnected(
        disconnected=True,
        email=email,
        remaining=len(docs) - 1,
    )
