"""Mail Client · Panel action handlers (archive/delete/spam/mark/counts/oauth/imap)."""
from __future__ import annotations

import asyncio
import base64
import json
import logging
from urllib.parse import urlencode

from pydantic import BaseModel, Field

from app import chat, ActionResult, _get_acc, _no_account_error
from providers.cache import invalidate_inbox
from providers import get_provider
from providers.helpers import (
    _all_accounts, COLLECTION,
    GMAIL_CLIENT_ID, GMAIL_REDIRECT_URI, GOOGLE_AUTH_URL, GMAIL_SCOPE,
    MS_CLIENT_ID, MS_REDIRECT_URI, MS_AUTH_URL, MS_SCOPE,
    _encrypt_password, _detect_imap_settings,
)
from providers.imap import _sync_imap_test

log = logging.getLogger(__name__)


# ─── Models ───────────────────────────────────────────────────────────── #

class MailActionParams(BaseModel):
    """Batch mail action from panel (archive/delete/spam/mark/star)."""
    action: str = Field(description="archive, delete, spam, mark_read, mark_unread, star")
    message_id: str = Field(default="", description="Single message ID")
    message_ids: list[str] = Field(default_factory=list, description="Multiple message IDs")
    account: str = Field(default="", description="Email account")


class FolderCountsParams(BaseModel):
    """Get unread counts per folder."""
    account: str = Field(default="", description="Email account")


class OAuthUrlParams(BaseModel):
    """Request OAuth URL for Google/Microsoft."""
    provider: str = Field(description="google or microsoft")


class AddImapParams(BaseModel):
    """Connect IMAP account from panel wizard."""
    email: str = Field(description="Email address")
    password: str = Field(description="Password or app password")
    imap_host: str = Field(default="", description="IMAP server host")
    smtp_host: str = Field(default="", description="SMTP server host")
    imap_port: int = Field(default=993, description="IMAP port")
    smtp_port: int = Field(default=587, description="SMTP port")


# ─── mail_action ─────────────────────────────────────────────────────── #

@chat.function("mail_action", action_type="write", event="mail_action",
               description="Direct mail action from panel: archive/delete/spam/mark.")
async def fn_mail_action(ctx, params: MailActionParams) -> ActionResult:
    acc, provider = await _get_acc(ctx, params.account)
    if not acc:
        return _no_account_error()

    ids = params.message_ids or ([params.message_id] if params.message_id else [])
    if not ids:
        return ActionResult.error("No message ID provided.")

    action_map = {
        "archive":    lambda mid: provider.archive(ctx, acc, mid),
        "delete":     lambda mid: provider.delete(ctx, acc, mid),
        "spam":       lambda mid: provider.move(ctx, acc, mid, "INBOX", "spam"),
        "mark_read":  lambda mid: provider.mark_read(ctx, acc, mid, read=True),
        "mark_unread": lambda mid: provider.mark_read(ctx, acc, mid, read=False),
        "star":       lambda mid: provider.star(ctx, acc, mid),
    }

    fn = action_map.get(params.action)
    if not fn:
        return ActionResult.error(f"Unknown action: {params.action}")

    errors = []
    for mid in ids:
        try:
            result = await fn(mid)
            if isinstance(result, dict) and result.get("RESULT") == "ERROR":
                errors.append(f"{mid}: {result.get('error', '?')}")
        except Exception as e:
            errors.append(f"{mid}: {e}")

    if errors:
        return ActionResult.error(f"Some actions failed: {'; '.join(errors)}")

    await invalidate_inbox(ctx, acc.get("email", ""))

    return ActionResult.success(
        data={"action": params.action, "count": len(ids)},
        summary=f"{params.action} {len(ids)} email(s)",
    )


# ─── folder_counts ───────────────────────────────────────────────────── #

FOLDER_KEYS = ["INBOX", "sent", "drafts", "spam", "trash", "starred"]


@chat.function("folder_counts", action_type="read",
               description="Get unread counts per folder for sidebar badges.")
async def fn_folder_counts(ctx, params: FolderCountsParams) -> ActionResult:
    acc, provider = await _get_acc(ctx, params.account)
    if not acc:
        return _no_account_error()

    counts: dict[str, int] = {}
    for folder in FOLDER_KEYS:
        try:
            counts[folder] = await provider.get_unread_count(ctx, acc, folder)
        except Exception:
            counts[folder] = 0

    return ActionResult.success(data={"counts": counts}, summary="Folder counts loaded")


# ─── get_oauth_url ────────────────────────────────────────────────────── #

def _oauth_state(ctx, provider: str) -> str:
    payload = {
        "user_id": str(ctx.user.id) if hasattr(ctx, "user") and ctx.user else "",
        "tenant_id": getattr(ctx.user, "tenant_id", "default") if hasattr(ctx, "user") else "default",
        "provider": provider,
    }
    return base64.urlsafe_b64encode(json.dumps(payload).encode()).decode()


@chat.function("get_oauth_url", action_type="read",
               description="Get OAuth authorization URL for Google or Microsoft.")
async def fn_get_oauth_url(ctx, params: OAuthUrlParams) -> ActionResult:
    if params.provider == "google":
        if not GMAIL_CLIENT_ID:
            return ActionResult.error("Google OAuth not configured on this instance.")
        url = GOOGLE_AUTH_URL + "?" + urlencode({
            "client_id": GMAIL_CLIENT_ID, "redirect_uri": GMAIL_REDIRECT_URI,
            "response_type": "code", "scope": GMAIL_SCOPE,
            "access_type": "offline", "prompt": "consent",
            "state": _oauth_state(ctx, "oauth"),
        })
    elif params.provider == "microsoft":
        if not MS_CLIENT_ID:
            return ActionResult.error("Microsoft OAuth not configured on this instance.")
        url = MS_AUTH_URL + "?" + urlencode({
            "client_id": MS_CLIENT_ID, "response_type": "code",
            "redirect_uri": MS_REDIRECT_URI, "scope": MS_SCOPE,
            "response_mode": "query", "state": _oauth_state(ctx, "microsoft"),
        })
    else:
        return ActionResult.error(f"Unknown OAuth provider: {params.provider}")

    return ActionResult.success(
        data={"auth_url": url, "provider": params.provider},
        summary=f"Opening {params.provider} authorization...",
    )


# ─── add_imap ─────────────────────────────────────────────────────────── #

@chat.function("add_imap", action_type="write", event="account_connected",
               description="Connect IMAP email account from the add-account panel wizard.")
async def fn_add_imap(ctx, params: AddImapParams) -> ActionResult:
    detected = _detect_imap_settings(params.email)
    imap_h = params.imap_host or detected["imap_host"]
    imap_p = params.imap_port or detected["imap_port"]
    smtp_h = params.smtp_host or detected["smtp_host"]
    smtp_p = params.smtp_port or detected["smtp_port"]

    ok, err = await asyncio.to_thread(_sync_imap_test, params.email, params.password, imap_h, imap_p)
    if not ok:
        return ActionResult.error(f"IMAP connection failed: {err}", retryable="timeout" in str(err).lower())

    # Create the new account FIRST — if this fails, existing active account is preserved.
    await ctx.store.create(COLLECTION, {
        "email": params.email, "provider": "imap", "is_active": True,
        "imap_host": imap_h, "imap_port": imap_p,
        "smtp_host": smtp_h, "smtp_port": smtp_p,
        "password": _encrypt_password(params.password), "password_encrypted": True,
    })
    # Now deactivate all other accounts; exclude doc_id from the update payload.
    accounts = await _all_accounts(ctx)
    for d in accounts:
        if d.get("email") != params.email:
            doc_data = {k: v for k, v in d.items() if k != "doc_id"}
            await ctx.store.update(COLLECTION, d["doc_id"], {**doc_data, "is_active": False})

    return ActionResult.success(
        data={"connected": True, "email": params.email, "imap_server": imap_h},
        summary=f"IMAP {params.email} connected via {imap_h}",
    )
