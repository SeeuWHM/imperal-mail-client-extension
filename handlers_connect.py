"""Mail Client · Connect & account handlers."""
from __future__ import annotations

import asyncio
import base64
import json
import logging

from urllib.parse import urlencode

from app import chat
from imperal_sdk.chat.action_result import ActionResult
from ctx_helpers import _get_acc

from providers import get_provider  # noqa: F401
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

_ALL_FOLDER_KEYS = ["INBOX", "sent", "drafts", "spam", "trash", "starred", "archive"]
from providers.imap import _sync_imap_test
from cache_model_defs import UnreadSummary

from schemas import (
    AccountDisconnected, AccountSwitched, AccountsStatus, ConnectImapResult,
    ConnectOAuthResult, MailAccount,
    AccountParam, ConnectImapParams, EmptyParams,
)

log = logging.getLogger("mail")


# ─── Internal ─────────────────────────────────────────────────────────── #


def _oauth_state(ctx, provider: str) -> str:
    return base64.urlsafe_b64encode(
        json.dumps({"user_id": str(ctx.user.imperal_id),
                    "tenant_id": getattr(ctx.user, "tenant_id", "default"),
                    "provider": provider}).encode()
    ).decode()


# ─── impl_* business logic ────────────────────────────────────────────── #


async def impl_connect(ctx) -> ConnectOAuthResult:
    accounts = await _all_accounts(ctx)
    existing = [a for a in accounts if a.get("provider") == "oauth"]
    if existing:
        active = next((a for a in existing if a.get("is_active")), existing[0])
        return ConnectOAuthResult(already_connected=True, email=active.get("email"),
                                  total=len(existing))
    if not GMAIL_CLIENT_ID:
        raise RuntimeError("Google OAuth not configured.")
    url = GOOGLE_AUTH_URL + "?" + urlencode({
        "client_id": GMAIL_CLIENT_ID, "redirect_uri": GMAIL_REDIRECT_URI,
        "response_type": "code", "scope": GMAIL_SCOPE,
        "access_type": "offline", "prompt": "consent", "state": _oauth_state(ctx, "oauth"),
    })
    return ConnectOAuthResult(auth_url=url, instruction="Open link to authorise Google.")


async def impl_connect_microsoft(ctx) -> ConnectOAuthResult:
    accounts = await _all_accounts(ctx)
    existing = [a for a in accounts if a.get("provider") == "microsoft"]
    if existing:
        active = next((a for a in existing if a.get("is_active")), existing[0])
        return ConnectOAuthResult(already_connected=True, email=active.get("email"),
                                  total=len(existing))
    if not MS_CLIENT_ID:
        raise RuntimeError("Microsoft OAuth not configured.")
    url = MS_AUTH_URL + "?" + urlencode({
        "client_id": MS_CLIENT_ID, "response_type": "code", "redirect_uri": MS_REDIRECT_URI,
        "scope": MS_SCOPE, "response_mode": "query", "state": _oauth_state(ctx, "microsoft"),
    })
    return ConnectOAuthResult(auth_url=url, instruction="Open link to authorise Microsoft.")


async def impl_connect_yahoo(ctx) -> ConnectOAuthResult:
    accounts = await _all_accounts(ctx)
    yahoo = [a for a in accounts if a.get("provider") == "yahoo"]
    if yahoo:
        active = next((a for a in yahoo if a.get("is_active")), yahoo[0])
        return ConnectOAuthResult(already_connected=True, email=active.get("email"))
    if not YAHOO_CLIENT_ID:
        raise RuntimeError("Yahoo OAuth not configured.")
    url = YAHOO_AUTH_URL + "?" + urlencode({
        "client_id": YAHOO_CLIENT_ID, "redirect_uri": YAHOO_REDIRECT_URI,
        "response_type": "code", "scope": YAHOO_SCOPE, "state": _oauth_state(ctx, "yahoo"),
    })
    return ConnectOAuthResult(auth_url=url, instruction="Open link to authorise Yahoo/AOL.")


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
            clean = {k: v for k, v in _data.items() if k != "doc_id"}
            await ctx.store.update(COLLECTION, _id, {**clean, "is_active": False})
    return ConnectImapResult(connected=True, email=email_addr, imap_server=imap_h)


async def impl_status(ctx) -> AccountsStatus:
    accounts = await _all_accounts(ctx)
    if not accounts:
        return AccountsStatus(connected=False, accounts=[], total=0)
    labels = {"oauth": "Google", "microsoft": "Microsoft", "yahoo": "Yahoo / AOL", "imap": "IMAP"}
    result: list[MailAccount] = []
    for a in accounts:
        email = a.get("email", "?")
        unread = 0
        try:
            summary = await ctx.cache.get(_unread_summary_key(email, "INBOX"), UnreadSummary)
            unread = summary.unread_count if summary else int(a.get("unread_count", 0) or 0)
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
    target_email = target.get("email", "")
    if target_email:
        for fkey in _ALL_FOLDER_KEYS:
            await _invalidate_first_page(ctx, target_email, fkey)
    return AccountSwitched(switched=True, active_account=target_email)


async def impl_disconnect(ctx, account: str) -> AccountDisconnected:
    docs = await ctx.store.query(COLLECTION)
    target = next((d for d in docs if d.id == account or d.get("email") == account), None)
    if not target:
        raise RuntimeError("Account not found.")
    email = target.get("email", "")
    await ctx.store.delete(COLLECTION, target.id)
    await _invalidate_first_page(ctx, email, "INBOX")
    return AccountDisconnected(disconnected=True, email=email, remaining=len(docs) - 1)


# ─── @chat.function wrappers ──────────────────────────────────────────── #


@chat.function("connect", action_type="read",
               description="Connect a Google/Gmail account via OAuth. Checks if already connected.")
async def fn_connect(ctx, params: EmptyParams) -> ActionResult:
    try:
        r = await impl_connect(ctx)
        return ActionResult.success(data=r.model_dump(),
                                    summary="Already connected." if r.already_connected else "OAuth URL ready.")
    except RuntimeError as e:
        return ActionResult.error(str(e), retryable=False)


@chat.function("connect_microsoft", action_type="read",
               description="Connect a Microsoft Outlook/Office 365 account via OAuth.")
async def fn_connect_microsoft(ctx, params: EmptyParams) -> ActionResult:
    try:
        r = await impl_connect_microsoft(ctx)
        return ActionResult.success(data=r.model_dump(),
                                    summary="Already connected." if r.already_connected else "OAuth URL ready.")
    except RuntimeError as e:
        return ActionResult.error(str(e), retryable=False)


@chat.function("connect_yahoo", action_type="read",
               description="Connect a Yahoo/AOL account via OAuth.")
async def fn_connect_yahoo(ctx, params: EmptyParams) -> ActionResult:
    try:
        r = await impl_connect_yahoo(ctx)
        return ActionResult.success(data=r.model_dump(),
                                    summary="Already connected." if r.already_connected else "OAuth URL ready.")
    except RuntimeError as e:
        return ActionResult.error(str(e), retryable=False)


@chat.function("connect_imap", action_type="write", event="account.connected",
               effects=["create:account"],
               description="Connect any email account via IMAP/SMTP (iCloud, Zoho, custom domains).")
async def fn_connect_imap(ctx, params: ConnectImapParams) -> ActionResult:
    try:
        r = await impl_connect_imap(ctx, email_addr=params.email_addr, password=params.password,
                                    imap_host=params.imap_host, smtp_host=params.smtp_host,
                                    imap_port=params.imap_port, smtp_port=params.smtp_port)
        return ActionResult.success(data=r.model_dump(),
                                    summary=f"Connected {r.email} via IMAP ({r.imap_server}).")
    except RuntimeError as e:
        return ActionResult.error(str(e), retryable=False)


@chat.function("status", action_type="read",
               description="Show all connected email accounts with provider, active flag, and unread count.")
async def fn_status(ctx, params: EmptyParams) -> ActionResult:
    try:
        r = await impl_status(ctx)
        return ActionResult.success(data=r.model_dump(),
                                    summary=f"{r.total} account(s) connected." if r.connected else "No accounts connected.")
    except RuntimeError as e:
        return ActionResult.error(str(e), retryable=False)


@chat.function("switch_account", action_type="write", event="account.switched",
               effects=["update:account"],
               description="Switch the active email account.")
async def fn_switch_account(ctx, params: AccountParam) -> ActionResult:
    try:
        r = await impl_switch_account(ctx, account=params.account)
        return ActionResult.success(data=r.model_dump(),
                                    summary=f"Switched to {r.active_account}.")
    except RuntimeError as e:
        return ActionResult.error(str(e), retryable=False)


@chat.function("disconnect", action_type="destructive", event="account.disconnected",
               effects=["delete:account"],
               description="Remove a connected email account and purge its credentials.")
async def fn_disconnect(ctx, params: AccountParam) -> ActionResult:
    try:
        r = await impl_disconnect(ctx, account=params.account)
        return ActionResult.success(data=r.model_dump(),
                                    summary=f"Disconnected {r.email}. {r.remaining} account(s) remaining.")
    except RuntimeError as e:
        return ActionResult.error(str(e), retryable=False)
