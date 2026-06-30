"""Mail Client · Panel action handlers (SDK 5.2.0 / SDL)."""
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
    GOOGLE_AUTH_URL, GMAIL_SCOPE,
    MS_REDIRECT_URI, MS_AUTH_URL, MS_SCOPE,
    _encrypt_password, _detect_imap_settings,
)
from providers.imap import _sync_imap_test

from schemas import (
    MailActionParams, AccountParam, CountParams, OAuthParams, AddImapParams,
    ConnectImapResult, FolderCountsResult, MailActionResult, OAuthUrlResult,
)
from schemas_sdl_builders import (
    MailActionOpResult, FolderCountsEntity, MailOAuthUrlResult, ImapConnectResult,
    build_mail_action_op, build_folder_counts, build_oauth_url, build_imap_connect,
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
        client_id = await ctx.secrets.get("google_client_id")
        if not client_id:
            raise RuntimeError("Google OAuth not configured — enter google_client_id in extension Secrets.")
        redirect_uri = ctx.webhook_url("callback")
        url = GOOGLE_AUTH_URL + "?" + urlencode({
            "client_id":     client_id,
            "redirect_uri":  redirect_uri,
            "response_type": "code",
            "scope":         GMAIL_SCOPE,
            "access_type":   "offline",
            "prompt":        "consent",
            "state":         _oauth_state(ctx, "oauth"),
        })
    elif provider == "microsoft":
        ms_client_id = await ctx.secrets.get("microsoft_client_id")
        if not ms_client_id:
            raise RuntimeError("Microsoft OAuth not configured — enter microsoft_client_id in extension Secrets.")
        url = MS_AUTH_URL + "?" + urlencode({
            "client_id": ms_client_id, "response_type": "code",
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
    enc_key = await ctx.secrets.get("imap_encryption_key")
    await ctx.store.create(COLLECTION, {
        "email": email, "provider": "imap", "is_active": True,
        "imap_host": imap_h, "imap_port": imap_p,
        "smtp_host": smtp_h, "smtp_port": smtp_p,
        "password": _encrypt_password(password, enc_key), "password_encrypted": True,
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
               data_model=MailActionOpResult,
               description="Panel UI action dispatcher — called by inbox row buttons, not LLM chat. From chat use archive(), delete(), mark_read(), star() etc. individually.")
async def fn_mail_action(ctx, params: MailActionParams) -> ActionResult:
    """Panel UI action dispatcher — called by inbox row buttons, not LLM chat."""
    try:
        r = await impl_mail_action(ctx, action=params.action, message_id=params.message_id,
                                   message_ids=params.message_ids, account=params.account)
        return ActionResult.success(
            data=build_mail_action_op(r),
            summary=f"{params.action}: {r.count} message(s).",
            refresh_panels=["inbox"],
        )
    except Exception as e:
        return ActionResult.error(str(e), retryable=False)


@chat.function("folder_counts", action_type="read",
               data_model=FolderCountsEntity,
               description="Get current unread message count for all 7 folders simultaneously — INBOX, sent, drafts, spam, trash, starred, archive.")
async def fn_folder_counts(ctx, params: AccountParam) -> ActionResult:
    """Get current unread message count for all 7 folders simultaneously — INBOX, sent, drafts, spam, trash, starred, archive."""
    try:
        r = await impl_folder_counts(ctx, account=params.account)
        return ActionResult.success(
            data=build_folder_counts(r),
            summary=f"INBOX: {r.counts.get('INBOX', 0)} unread.",
        )
    except Exception as e:
        return ActionResult.error(str(e), retryable=True)


async def impl_count(ctx, folder: str = "", query: str = "",
                     account: str = "") -> FolderCountsResult:
    """Exact email count. folder/state via provider.get_counts/get_today_count;
    query (date/sender) via provider.search total (accurate, not a page length).
    Returns counts keyed by account email + a 'total' across them."""
    folder_k = (folder or "").strip().lower()
    query_s  = (query or "").strip()
    if account:
        acc, _ = await _get_acc(ctx, account)
        accs = [acc] if acc else []
    else:
        accs = await _all_accounts(ctx)
    if not accs:
        raise RuntimeError("No email account connected. Connect one first.")

    counts: dict[str, int] = {}
    grand = 0
    for acc in accs:
        email = acc.get("email", "")
        provider = get_provider(acc)
        n = 0
        try:
            if query_s:
                r = await provider.search(ctx, acc, query=query_s, max_results=1)
                n = int(r.get("total", 0) or 0)
            else:
                c = await provider.get_counts(ctx, acc)
                if folder_k in ("", "all", "total"):
                    n = int(c.get("total", 0) or 0)
                elif folder_k == "unread":
                    n = int(c.get("unread", 0) or 0)
                elif folder_k == "spam":
                    n = int(c.get("spam", 0) or 0)
                elif folder_k == "archive":
                    n = int(c.get("archive", 0) or 0)
                elif folder_k == "inbox":
                    n = int(c.get("inbox_total", 0) or 0)
                elif folder_k == "today":
                    n = int(await provider.get_today_count(ctx, acc) or 0)
                else:
                    fs = await provider.get_folder_stats(ctx, acc, folder_k)
                    n = int(fs.get("total", 0) or 0)
        except Exception as e:
            log.warning("count_emails failed for %s: %s", email, e)
            n = 0
        counts[email] = n
        grand += n
    counts["total"] = grand
    return FolderCountsResult(counts=counts)


@chat.function("count_emails", action_type="read",
               data_model=FolderCountsEntity,
               description="Return the EXACT NUMBER of emails — use for ANY 'how many / сколько' question. CRITICAL: never answer a count by counting the items returned by inbox()/search()/folder() — those are capped display pages, not totals. Pass folder= for a folder/state count: 'all' (whole-mailbox total), 'unread', 'spam', 'archive', 'inbox', 'today', 'sent', 'trash'. OR pass query= for a date/sender count in Gmail syntax: 'newer_than:1d' (today), 'after:2026/06/05 before:2026/06/06' (one specific day), 'from:reddit'. Counts ALL connected accounts unless account= is given. Returns a per-account breakdown plus a 'total' key.")
async def fn_count_emails(ctx, params: CountParams) -> ActionResult:
    """Exact email count by folder/state or query, across one or all accounts."""
    try:
        r = await impl_count(ctx, folder=params.folder, query=params.query,
                             account=params.account)
        return ActionResult.success(
            data=build_folder_counts(r),
            summary=f"{r.counts.get('total', 0)} email(s).",
        )
    except Exception as e:
        return ActionResult.error(str(e), retryable=True)


@chat.function("get_oauth_url", action_type="read",
               data_model=MailOAuthUrlResult,
               description="Panel add-account wizard helper — returns OAuth URL for Google or Microsoft. From LLM chat use connect() or connect_microsoft() instead.")
async def fn_get_oauth_url(ctx, params: OAuthParams) -> ActionResult:
    """Panel add-account wizard helper — returns OAuth URL for Google or Microsoft."""
    try:
        r = await impl_get_oauth_url(ctx, provider=params.provider)
        return ActionResult.success(
            data=build_oauth_url(r),
            summary=f"OAuth URL for {params.provider}.",
        )
    except Exception as e:
        return ActionResult.error(str(e), retryable=False)


@chat.function("add_imap", action_type="write", event="account.connected",
               effects=["create:account"],
               data_model=ImapConnectResult,
               description="Panel add-account wizard helper — connects an IMAP account from the UI form. From LLM chat use connect_imap() instead.")
async def fn_add_imap(ctx, params: AddImapParams) -> ActionResult:
    """Panel add-account wizard helper — connects an IMAP account from the UI form."""
    try:
        r = await impl_add_imap(ctx, email=params.email, password=params.password,
                                imap_host=params.imap_host, smtp_host=params.smtp_host,
                                imap_port=params.imap_port, smtp_port=params.smtp_port)
        return ActionResult.success(
            data=build_imap_connect(r),
            summary=f"Connected {r.email} via IMAP ({r.imap_server}).",
        )
    except Exception as e:
        return ActionResult.error(str(e), retryable=False)
