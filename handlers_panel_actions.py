"""Mail Client · Panel action handlers (SDK v2.0.0).

archive / delete / spam / mark / counts / oauth / imap — the UI panel dispatches
these directly via ``ui.Call(...)`` and the kernel routes through the tool
catalog, so they must be tool-shaped (not just panel helpers).
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
from urllib.parse import urlencode

from ctx_helpers import _get_acc
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
)

log = logging.getLogger(__name__)


# ─── Internal ─────────────────────────────────────────────────────────── #


def _oauth_state(ctx, provider: str) -> str:
    payload = {
        "user_id": str(ctx.user.id) if hasattr(ctx, "user") and ctx.user else "",
        "tenant_id": getattr(ctx.user, "tenant_id", "default") if hasattr(ctx, "user") else "default",
        "provider": provider,
    }
    return base64.urlsafe_b64encode(json.dumps(payload).encode()).decode()


# ─── mail_action ─────────────────────────────────────────────────────── #


async def impl_mail_action(
    ctx, action: str, message_id: str = "",
    message_ids: list[str] | None = None, account: str = "",
) -> MailActionResult:
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
        "star":        lambda mid: provider.star(ctx, acc, mid),
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


# ─── folder_counts ───────────────────────────────────────────────────── #


FOLDER_KEYS = ["INBOX", "sent", "drafts", "spam", "trash", "starred"]


async def impl_folder_counts(ctx, account: str = "") -> FolderCountsResult:
    acc, provider = await _get_acc(ctx, account)
    if not acc:
        raise RuntimeError("No email account connected. Connect one first.")

    counts: dict[str, int] = {}
    for folder in FOLDER_KEYS:
        try:
            counts[folder] = int(await provider.get_unread_count(ctx, acc, folder))
        except Exception:
            counts[folder] = 0

    return FolderCountsResult(counts=counts)


# ─── get_oauth_url ────────────────────────────────────────────────────── #


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


# ─── add_imap ─────────────────────────────────────────────────────────── #


async def impl_add_imap(
    ctx, email: str, password: str, imap_host: str = "",
    smtp_host: str = "", imap_port: int = 993, smtp_port: int = 587,
) -> ConnectImapResult:
    detected = _detect_imap_settings(email)
    imap_h = imap_host or detected["imap_host"]
    imap_p = imap_port or detected["imap_port"]
    smtp_h = smtp_host or detected["smtp_host"]
    smtp_p = smtp_port or detected["smtp_port"]

    ok, err = await asyncio.to_thread(_sync_imap_test, email, password, imap_h, imap_p)
    if not ok:
        raise RuntimeError(f"IMAP connection failed: {err}")

    # Create the new account FIRST — if this fails, existing active account is preserved.
    await ctx.store.create(COLLECTION, {
        "email": email, "provider": "imap", "is_active": True,
        "imap_host": imap_h, "imap_port": imap_p,
        "smtp_host": smtp_h, "smtp_port": smtp_p,
        "password": _encrypt_password(password), "password_encrypted": True,
    })
    # Now deactivate all other accounts; exclude doc_id from the update payload.
    accounts = await _all_accounts(ctx)
    for d in accounts:
        _data = d.data if hasattr(d, "data") else d
        _id = d.id if hasattr(d, "id") else d["doc_id"]
        if _data.get("email") != email:
            await ctx.store.update(COLLECTION, _id, {**_data, "is_active": False})

    return ConnectImapResult(connected=True, email=email, imap_server=imap_h)
