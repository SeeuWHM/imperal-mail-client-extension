"""Mail Client · Connect & account handlers."""
from __future__ import annotations

import asyncio
import base64
import json
import time

from urllib.parse import urlencode

from pydantic import BaseModel, Field

from app import chat, ActionResult, _get_acc, _no_account_error, ext

from providers import get_provider
from providers.helpers import (
    _all_accounts,
    COLLECTION, SKELETON_INBOX, INBOX_FETCH_SIZE,
    GMAIL_CLIENT_ID, GMAIL_REDIRECT_URI, GOOGLE_AUTH_URL, GMAIL_SCOPE,
    MS_CLIENT_ID, MS_REDIRECT_URI, MS_AUTH_URL, MS_SCOPE,
    YAHOO_CLIENT_ID, YAHOO_REDIRECT_URI, YAHOO_AUTH_URL, YAHOO_SCOPE,
    _encrypt_password, _detect_imap_settings,
)
from providers.imap import _sync_imap_test


# ─── Models ───────────────────────────────────────────────────────────── #

class ConnectImapParams(BaseModel):
    """Connect via IMAP/SMTP with credentials."""
    email_addr: str = Field(description="Email address")
    password: str   = Field(description="Email password or app-specific password")
    imap_host: str  = Field(default="", description="IMAP server hostname")
    smtp_host: str  = Field(default="", description="SMTP server hostname")
    imap_port: int  = Field(default=0, description="IMAP port")
    smtp_port: int  = Field(default=0, description="SMTP port")


class AccountParams(BaseModel):
    """Target a specific account."""
    account: str = Field(description="Email address or account ID")


# ─── Internal ─────────────────────────────────────────────────────────── #

def _oauth_state(ctx, provider: str) -> str:
    return base64.urlsafe_b64encode(
        json.dumps({"user_id": str(ctx.user.id), "tenant_id": getattr(ctx.user, "tenant_id", "default"),
                     "provider": provider}).encode()
    ).decode()


# ─── Connect Handlers ─────────────────────────────────────────────────── #

@chat.function("connect", action_type="write", event="account_connected",
               description="Connect a Google account via OAuth.")
async def fn_connect(ctx) -> ActionResult:
    accounts = await _all_accounts(ctx)
    oauth = [a for a in accounts if a.get("provider", "oauth") == "oauth"]
    if oauth:
        active = next((a for a in oauth if a.get("is_active")), oauth[0])
        return ActionResult.success(data={"already_connected": True, "email": active.get("email"), "total": len(accounts)},
                                    summary=f"Google {active.get('email')} already connected ({len(accounts)} total)")
    if not GMAIL_CLIENT_ID:
        return ActionResult.error("Google OAuth not configured.")
    url = GOOGLE_AUTH_URL + "?" + urlencode({
        "client_id": GMAIL_CLIENT_ID, "redirect_uri": GMAIL_REDIRECT_URI,
        "response_type": "code", "scope": GMAIL_SCOPE,
        "access_type": "offline", "prompt": "consent", "state": _oauth_state(ctx, "oauth"),
    })
    return ActionResult.success(data={"auth_url": url, "instruction": "Open link to authorise Google."},
                                summary="Google OAuth URL generated")


@chat.function("connect_microsoft", action_type="write", event="account_connected",
               description="Connect a Microsoft Outlook / Office 365 account via OAuth.")
async def fn_connect_microsoft(ctx) -> ActionResult:
    accounts = await _all_accounts(ctx)
    ms = [a for a in accounts if a.get("provider") == "microsoft"]
    if ms:
        active = next((a for a in ms if a.get("is_active")), ms[0])
        return ActionResult.success(data={"already_connected": True, "email": active.get("email")},
                                    summary=f"Microsoft {active.get('email')} already connected")
    if not MS_CLIENT_ID:
        return ActionResult.error("Microsoft OAuth not configured.")
    url = MS_AUTH_URL + "?" + urlencode({
        "client_id": MS_CLIENT_ID, "response_type": "code", "redirect_uri": MS_REDIRECT_URI,
        "scope": MS_SCOPE, "response_mode": "query", "state": _oauth_state(ctx, "microsoft"),
    })
    return ActionResult.success(data={"auth_url": url, "instruction": "Open link to authorise Microsoft."},
                                summary="Microsoft OAuth URL generated")


@chat.function("connect_yahoo", action_type="write", event="account_connected",
               description="Connect a Yahoo / AOL account via OAuth.")
async def fn_connect_yahoo(ctx) -> ActionResult:
    accounts = await _all_accounts(ctx)
    yahoo = [a for a in accounts if a.get("provider") == "yahoo"]
    if yahoo:
        active = next((a for a in yahoo if a.get("is_active")), yahoo[0])
        return ActionResult.success(data={"already_connected": True, "email": active.get("email")},
                                    summary=f"Yahoo {active.get('email')} already connected")
    if not YAHOO_CLIENT_ID:
        return ActionResult.error("Yahoo OAuth not configured.")
    url = YAHOO_AUTH_URL + "?" + urlencode({
        "client_id": YAHOO_CLIENT_ID, "redirect_uri": YAHOO_REDIRECT_URI,
        "response_type": "code", "scope": YAHOO_SCOPE, "state": _oauth_state(ctx, "yahoo"),
    })
    return ActionResult.success(data={"auth_url": url, "instruction": "Open link to authorise Yahoo/AOL."},
                                summary="Yahoo/AOL OAuth URL generated")


@chat.function("connect_imap", action_type="write", event="account_connected",
               description="Connect any email via IMAP/SMTP (iCloud, Zoho, custom domains).")
async def fn_connect_imap(ctx, params: ConnectImapParams) -> ActionResult:
    detected = _detect_imap_settings(params.email_addr)
    imap_h = params.imap_host or detected["imap_host"]
    imap_p = params.imap_port or detected["imap_port"]
    smtp_h = params.smtp_host or detected["smtp_host"]
    smtp_p = params.smtp_port or detected["smtp_port"]
    ok, err = await asyncio.to_thread(_sync_imap_test, params.email_addr, params.password, imap_h, imap_p)
    if not ok:
        return ActionResult.error(f"IMAP failed: {err}", retryable="timeout" in str(err).lower())
    accounts = await _all_accounts(ctx)
    for d in accounts:
        await ctx.store.update(COLLECTION, d["doc_id"], {**d, "is_active": False})
    await ctx.store.create(COLLECTION, {
        "email": params.email_addr, "provider": "imap", "is_active": True,
        "imap_host": imap_h, "imap_port": imap_p, "smtp_host": smtp_h, "smtp_port": smtp_p,
        "password": _encrypt_password(params.password), "password_encrypted": True,
    })
    try:
        seed = {"email": params.email_addr, "provider": "imap", "imap_host": imap_h, "imap_port": imap_p,
                "password": params.password, "password_encrypted": False}
        res = await get_provider(seed).fetch_inbox(ctx, seed, INBOX_FETCH_SIZE)
        if res.get("messages"):
            cache = dict(ctx.skeleton_data.get(SKELETON_INBOX, {})) if hasattr(ctx, "skeleton_data") else {}
            cache[params.email_addr] = {"messages": res["messages"], "unread_count": res.get("unread_count", 0), "last_fetched": int(time.time())}
            await ctx.skeleton.update(SKELETON_INBOX, cache)
    except Exception:
        pass
    return ActionResult.success(data={"connected": True, "email": params.email_addr, "imap_server": imap_h},
                                summary=f"IMAP {params.email_addr} connected via {imap_h}")


# ─── Account Handlers ─────────────────────────────────────────────────── #

@chat.function("status", action_type="read",
               description="Show all connected email accounts with provider and unread count.")
async def fn_status(ctx) -> ActionResult:
    accounts = await _all_accounts(ctx)
    if not accounts:
        return ActionResult.success(data={"connected": False, "accounts": [], "total": 0}, summary="No accounts connected")
    labels = {"oauth": "Google", "microsoft": "Microsoft", "yahoo": "Yahoo / AOL", "imap": "IMAP"}
    cache = ctx.skeleton_data.get(SKELETON_INBOX, {}) if hasattr(ctx, "skeleton_data") else {}
    result = [{"email": a.get("email", "?"), "provider": labels.get(a.get("provider", "oauth"), "Unknown"),
               "is_active": a.get("is_active", False), "unread_count": cache.get(a.get("email", ""), {}).get("unread_count", 0)}
              for a in accounts]
    return ActionResult.success(data={"connected": True, "accounts": result, "total": len(result)},
                                summary=f"{len(result)} email account(s) connected")


@chat.function("switch_account", action_type="write", event="account_switched",
               description="Switch the active email account.")
async def fn_switch_account(ctx, params: AccountParams) -> ActionResult:
    docs = await ctx.store.query(COLLECTION)
    if not docs:
        return _no_account_error()
    target = next((d for d in docs if d.id == params.account or d.get("email") == params.account), None)
    if not target:
        return ActionResult.error(f"Account not found. Available: {[d.get('email') for d in docs]}")
    for d in docs:
        new_active = d.id == target.id
        if d.get("is_active") != new_active:
            await ctx.store.update(COLLECTION, d.id, {**d.data, "is_active": new_active})
    return ActionResult.success(data={"switched": True, "active_account": target.get("email")},
                                summary=f"Switched to {target.get('email')}")


@chat.function("disconnect", action_type="destructive", event="account_disconnected",
               description="Remove a connected email account.")
async def fn_disconnect(ctx, params: AccountParams) -> ActionResult:
    from providers.helpers import _remove_from_cache
    docs = await ctx.store.query(COLLECTION)
    target = next((d for d in docs if d.id == params.account or d.get("email") == params.account), None)
    if not target:
        return ActionResult.error("Account not found.")
    email = target.get("email", "")
    await ctx.store.delete(COLLECTION, target.id)
    await _remove_from_cache(ctx, email, "__all__")
    return ActionResult.success(data={"disconnected": True, "email": email, "remaining": len(docs) - 1},
                                summary=f"Disconnected {email}")
