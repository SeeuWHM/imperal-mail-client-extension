"""Mail Client · Panel action handlers — archive/delete/spam/mark/counts/oauth/imap."""
from __future__ import annotations

import asyncio
import logging
from urllib.parse import urlencode

from app import chat
from imperal_sdk.chat.action_result import ActionResult
from ctx_helpers import _get_acc, _oauth_state
from providers import get_provider
from providers.helpers import _invalidate_first_page
from providers.helpers import (
    _all_accounts, COLLECTION,
    GMAIL_CLIENT_ID, GMAIL_REDIRECT_URI, GOOGLE_AUTH_URL, GMAIL_SCOPE,
    MS_CLIENT_ID, MS_REDIRECT_URI, MS_AUTH_URL, MS_SCOPE,
    _encrypt_password, _detect_imap_settings,
)
from providers.imap import _sync_imap_test

from schemas import (
    ConnectImapResult, FolderCountsResult, MailActionResult, OAuthUrlResult,
    MailActionParams, AccountParam, OAuthParams, AddImapParams,
)

log = logging.getLogger(__name__)


# ─── impl_* business logic ────────────────────────────────────────────── #


async def impl_mail_action(ctx, action: str, message_id: str = "",
                           message_ids: list[str] | None = None, account: str = "") -> MailActionResult:
    acc, provider = await _get_acc(ctx, account)
    if not acc:
        raise RuntimeError("No email account connected. Connect one first.")
    ids = list(message_ids or []) or ([message_id] if message_id else [])
    if not ids:
        raise RuntimeError("No message ID provided.")
    action_map = {
        "archive":     lambda mid: provider.archive(ctx, acc, mid),
        "delete":      lambda mid: provider.delete(ctx, acc, mid),
        "spam":        lambda mid: provider.move(ctx, acc, mid, "INBOX", "spam"),
        "mark_read":   lambda mid: provider.mark_read(ctx, acc, mid, read=True),
        "mark_unread": lambda mid: provider.mark_read(ctx, acc, mid, read=False),
        "star":        lambda mid: provider.star(ctx, acc, mid, starred=True),
        "unstar":      lambda mid: provider.star(ctx, acc, mid, starred=False),
        "unspam":      lambda mid: provider.move(ctx, acc, mid, "spam",    "INBOX"),
        "unarchive":   lambda mid: provider.move(ctx, acc, mid, "archive", "INBOX"),
        "restore":     lambda mid: provider.move(ctx, acc, mid, "trash",   "INBOX"),
    }
    fn = action_map.get(action)
    if not fn:
        raise RuntimeError(f"Unknown action: {action}")
    errors = []
    for mid in ids:
        try:
            result = await fn(mid)
            if isinstance(result, dict) and result.get("RESULT") == "ERROR":
                errors.append(f"{mid}: {result.get('error', '?')}")
        except Exception as e:
            errors.append(f"{mid}: {e}")
    if errors:
        raise RuntimeError(f"Some actions failed: {'; '.join(errors)}")
    await _invalidate_first_page(ctx, acc.get("email", ""), "INBOX")
    return MailActionResult(action=action, count=len(ids))


FOLDER_KEYS = ["INBOX", "sent", "drafts", "spam", "trash", "starred", "archive"]


async def impl_folder_counts(ctx, account: str = "") -> FolderCountsResult:
    if account:
        acc, prov = await _get_acc(ctx, account)
        if not acc:
            raise RuntimeError("No email account connected.")
        accs = [(acc, prov)]
    else:
        all_accs = await _all_accounts(ctx)
        if not all_accs:
            raise RuntimeError("No email account connected.")
        accs = [(a, get_provider(a)) for a in all_accs]

    async def _count(acc, prov, folder: str) -> int:
        try:
            return int(await prov.get_unread_count(ctx, acc, folder))
        except Exception:
            return 0

    totals = {f: 0 for f in FOLDER_KEYS}
    for acc, prov in accs:
        results = await asyncio.gather(*[_count(acc, prov, f) for f in FOLDER_KEYS])
        for folder, n in zip(FOLDER_KEYS, results):
            totals[folder] += n
    return FolderCountsResult(counts=totals)


async def impl_get_oauth_url(ctx, provider: str) -> OAuthUrlResult:
    if provider == "google":
        if not GMAIL_CLIENT_ID:
            raise RuntimeError("Google OAuth not configured on this instance.")
        url = GOOGLE_AUTH_URL + "?" + urlencode({
            "client_id": GMAIL_CLIENT_ID, "redirect_uri": GMAIL_REDIRECT_URI,
            "response_type": "code", "scope": GMAIL_SCOPE,
            "access_type": "offline", "prompt": "consent",
            "state": _oauth_state(ctx, "oauth"),
        })
    elif provider == "microsoft":
        if not MS_CLIENT_ID:
            raise RuntimeError("Microsoft OAuth not configured on this instance.")
        url = MS_AUTH_URL + "?" + urlencode({
            "client_id": MS_CLIENT_ID, "response_type": "code",
            "redirect_uri": MS_REDIRECT_URI, "scope": MS_SCOPE,
            "response_mode": "query", "state": _oauth_state(ctx, "microsoft"),
        })
    else:
        raise RuntimeError(f"Unknown OAuth provider: {provider}")
    return OAuthUrlResult(auth_url=url, provider=provider)


async def impl_add_imap(ctx, email: str, password: str, imap_host: str = "",
                        smtp_host: str = "", imap_port: int = 993, smtp_port: int = 587) -> ConnectImapResult:
    detected = _detect_imap_settings(email)
    imap_h = imap_host or detected["imap_host"]
    imap_p = imap_port or detected["imap_port"]
    smtp_h = smtp_host or detected["smtp_host"]
    smtp_p = smtp_port or detected["smtp_port"]
    ok, err = await asyncio.to_thread(_sync_imap_test, email, password, imap_h, imap_p)
    if not ok:
        raise RuntimeError(f"IMAP connection failed: {err}")
    await ctx.store.create(COLLECTION, {
        "email": email, "provider": "imap", "is_active": True,
        "imap_host": imap_h, "imap_port": imap_p,
        "smtp_host": smtp_h, "smtp_port": smtp_p,
        "password": _encrypt_password(password), "password_encrypted": True,
    })
    accounts = await _all_accounts(ctx)
    for d in accounts:
        if d.get("email") != email:
            clean = {k: v for k, v in d.items() if k != "doc_id"}
            await ctx.store.update(COLLECTION, d["doc_id"], {**clean, "is_active": False})
    return ConnectImapResult(connected=True, email=email, imap_server=imap_h)


# ─── @chat.function wrappers ──────────────────────────────────────────── #


@chat.function("mail_action", action_type="write", event="mail.action",
               effects=["update:email"],
               data_model=MailActionResult,
               description="Panel UI action dispatcher — called by inbox row buttons, not LLM chat. From chat use archive(), delete(), mark_read(), star() etc. individually.")
async def fn_mail_action(ctx, params: MailActionParams) -> ActionResult:
    try:
        r = await impl_mail_action(ctx, action=params.action, message_id=params.message_id,
                                   message_ids=params.message_ids, account=params.account)
        return ActionResult.success(data=r.model_dump(),
                                    summary=f"{params.action}: {r.count} message(s).",
                                    refresh_panels=["inbox"])
    except RuntimeError as e:
        return ActionResult.error(str(e), retryable=False)


@chat.function("folder_counts", action_type="read",
               data_model=FolderCountsResult,
               description="Get current unread message count for all 7 folders simultaneously — INBOX, sent, drafts, spam, trash, starred, archive.")
async def fn_folder_counts(ctx, params: AccountParam) -> ActionResult:
    try:
        r = await impl_folder_counts(ctx, account=params.account)
        return ActionResult.success(data=r.model_dump(),
                                    summary=f"INBOX: {r.counts.get('INBOX', 0)} unread.")
    except RuntimeError as e:
        return ActionResult.error(str(e), retryable=True)


@chat.function("get_oauth_url", action_type="read",
               data_model=OAuthUrlResult,
               description="Panel add-account wizard helper — returns OAuth URL for Google or Microsoft. From LLM chat use connect() or connect_microsoft() instead.")
async def fn_get_oauth_url(ctx, params: OAuthParams) -> ActionResult:
    try:
        r = await impl_get_oauth_url(ctx, provider=params.provider)
        return ActionResult.success(data=r.model_dump(), summary=f"OAuth URL for {params.provider}.")
    except RuntimeError as e:
        return ActionResult.error(str(e), retryable=False)


@chat.function("add_imap", action_type="write", event="account.connected",
               effects=["create:account"],
               data_model=ConnectImapResult,
               description="Panel add-account wizard helper — connects an IMAP account from the UI form. From LLM chat use connect_imap() instead.")
async def fn_add_imap(ctx, params: AddImapParams) -> ActionResult:
    try:
        r = await impl_add_imap(ctx, email=params.email, password=params.password,
                                imap_host=params.imap_host, smtp_host=params.smtp_host,
                                imap_port=params.imap_port, smtp_port=params.smtp_port)
        return ActionResult.success(data=r.model_dump(),
                                    summary=f"Connected {r.email} via IMAP ({r.imap_server}).")
    except RuntimeError as e:
        return ActionResult.error(str(e), retryable=False)
