"""Shared helpers for all mail providers.

Constants (OAuth URLs, env vars, storage keys), account helpers,
IMAP provider detection, cursor encode/decode, IMAP folder candidates,
and SDK v1.6.0 ``ctx.cache``-aware helpers for last-read watermark + best-
effort inbox page invalidation.
"""
from __future__ import annotations

import base64
import json
import logging
import os
from typing import Optional

from imperal_sdk import Context

log = logging.getLogger(__name__)

# ── Storage constants ──────────────────────────────────────────────────────
COLLECTION          = "gmail_accounts"   # kept for backwards compat with stored data
CONTACTS_COLLECTION = "mail_contacts"
INBOX_FETCH_SIZE    = 20

# ── Google OAuth / Gmail REST ──────────────────────────────────────────────
GOOGLE_AUTH_URL  = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GMAIL_API        = "https://gmail.googleapis.com/gmail/v1/users/me"
PEOPLE_API       = "https://people.googleapis.com/v1"
GMAIL_SCOPE      = ("https://www.googleapis.com/auth/gmail.modify "
                   "https://www.googleapis.com/auth/contacts.readonly")

GMAIL_CLIENT_ID     = os.getenv("GMAIL_CLIENT_ID", "")
GMAIL_CLIENT_SECRET = os.getenv("GMAIL_CLIENT_SECRET", "")
GMAIL_REDIRECT_URI  = os.getenv("GMAIL_REDIRECT_URI", "https://auth.imperal.io/v1/oauth/gmail/callback")

# ── Microsoft OAuth / Graph API ────────────────────────────────────────────
MS_CLIENT_ID     = os.getenv("MICROSOFT_CLIENT_ID", "")
MS_CLIENT_SECRET = os.getenv("MICROSOFT_CLIENT_SECRET", "")
MS_REDIRECT_URI  = os.getenv("MICROSOFT_REDIRECT_URI", "https://auth.imperal.io/v1/oauth/microsoft/callback")
MS_AUTH_URL      = "https://login.microsoftonline.com/common/oauth2/v2.0/authorize"
MS_TOKEN_URL     = "https://login.microsoftonline.com/common/oauth2/v2.0/token"
MS_GRAPH_BASE    = "https://graph.microsoft.com/v1.0"
MS_SCOPE = (
    "https://graph.microsoft.com/Mail.ReadWrite "
    "https://graph.microsoft.com/Mail.Send "
    "https://graph.microsoft.com/User.Read "
    "https://graph.microsoft.com/Contacts.Read "
    "offline_access"
)

# ── Yahoo / AOL OAuth ──────────────────────────────────────────────────────
YAHOO_CLIENT_ID     = os.getenv("YAHOO_CLIENT_ID", "")
YAHOO_CLIENT_SECRET = os.getenv("YAHOO_CLIENT_SECRET", "")
YAHOO_REDIRECT_URI  = os.getenv("YAHOO_REDIRECT_URI", "https://auth.imperal.io/v1/oauth/yahoo/callback")
YAHOO_AUTH_URL      = "https://api.login.yahoo.com/oauth2/request_auth"
YAHOO_TOKEN_URL     = "https://api.login.yahoo.com/oauth2/get_token"
YAHOO_SCOPE         = "mail-r mail-w"


# ── Re-exports for backward compatibility ─────────────────────────────────
from .token_refresh import (  # noqa: E402, F401
    _refresh_google_token, _refresh_microsoft_token, _refresh_yahoo_token,
    _refresh_token_if_needed,
    _api_get, _api_post, _graph_get, _graph_post, _graph_patch,
)
from .text_utils import (  # noqa: E402, F401
    _encrypt_password, _decrypt_password,
    _header, _decode_header, _short_sender,
    _strip_html, _decode_body, _decode_body_with_type, _build_message,
    _norm_graph_msg, _xoauth2_string,
)


# ── ctx.cache inbox-page key helpers (SDK v1.6.0) ─────────────────────────
# Keys must satisfy ``[A-Za-z0-9_\-:]+`` length <= 128 (I-CACHE-KEY-SAFETY).
# We derive a stable short token per (email, folder, cursor) and hash the
# cursor so arbitrary cursor payloads (base64/URL-safe) stay within the
# key grammar.
import hashlib as _hashlib
import re as _re

_KEY_SAFE = _re.compile(r"[^A-Za-z0-9_\-]")


def _slug(s: str, max_len: int = 24) -> str:
    """Collapse an arbitrary string to a key-safe short token."""
    safe = _KEY_SAFE.sub("_", (s or ""))[:max_len]
    return safe or "none"


def _inbox_page_key(email: str, folder: str, cursor: str = "") -> str:
    """Canonical ctx.cache key for an inbox page.

    Shape: ``inbox:<email-slug>:<folder-slug>:<cursor-hash>``. Stays within
    the 128-char bound and only uses alphanumerics + ``_-:`` per
    I-CACHE-KEY-SAFETY.
    """
    email_slug  = _slug(email)
    folder_slug = _slug(folder)
    if cursor:
        cur = _hashlib.md5(cursor.encode()).hexdigest()[:10]
    else:
        cur = "first"
    return f"inbox:{email_slug}:{folder_slug}:{cur}"


def _unread_summary_key(email: str, folder: str = "INBOX") -> str:
    return f"unread:{_slug(email)}:{_slug(folder)}"


def _inbox_manifest_key(email: str, folder: str = "INBOX") -> str:
    """Canonical ctx.cache key for the inbox pagination manifest."""
    return f"manifest:{_slug(email)}:{_slug(folder)}"


# ── Best-effort cache-bust helpers (thin wrappers over ctx.cache.delete) ─
# Replaces the Redis SCAN-based invalidation from the deleted providers/cache.py.
# ctx.cache exposes only per-key delete (no SCAN), so we invalidate the
# first-page key on write actions — subsequent pages self-expire via TTL.
# Staleness trade-off is documented in the migration spec.

async def _invalidate_first_page(ctx, email: str, folder: str = "INBOX") -> None:
    try:
        if hasattr(ctx, "cache") and ctx.cache is not None:
            await ctx.cache.delete(_inbox_page_key(email, folder, ""))
            await ctx.cache.delete(_unread_summary_key(email, folder))
    except Exception as e:
        log.debug("_invalidate_first_page(%s/%s): %s", email, folder, e)


async def _remove_from_cache(ctx, email: str, message_id: str) -> None:
    """Invalidate the first-page inbox cache after a single-message remove."""
    await _invalidate_first_page(ctx, email, "INBOX")


async def _remove_multiple_from_cache(ctx, email: str, message_ids: list[str]) -> None:
    """Invalidate the first-page inbox cache after a bulk remove."""
    if not message_ids:
        return
    await _invalidate_first_page(ctx, email, "INBOX")


async def _update_read_in_cache(ctx, email: str, message_id: str, is_read: bool = True) -> None:
    """Invalidate the first-page inbox cache after a read-state change."""
    await _invalidate_first_page(ctx, email, "INBOX")


async def _save_last_read(ctx, message_id: str, subject: str, sender: str,
                          message_id_header: str = "", thread_id: str = "") -> None:
    """Persist the last-read watermark per user (upsert by user_id)."""
    try:
        user_id = str(ctx.user.imperal_id) if ctx.user and ctx.user.imperal_id else ""
        data = {
            "message_id":        message_id,
            "subject":           subject,
            "sender":            sender,
            "message_id_header": message_id_header,
            "thread_id":         thread_id,
            "user_id":           user_id,
        }
        page = await ctx.store.query("mail_last_read", where={"user_id": user_id}, limit=1)
        if page.data:
            await ctx.store.update("mail_last_read", page.data[0].id, data)
        else:
            await ctx.store.create("mail_last_read", data)
    except Exception as e:
        log.debug("_save_last_read failed: %s", e)


# ── Account helpers ───────────────────────────────────────────────────────

async def _all_accounts(ctx: Context) -> list[dict]:
    docs = await ctx.store.query(COLLECTION)
    return [{"doc_id": d.id, **d.data} for d in docs]


async def _active_account(ctx: Context, account_id: str = "") -> Optional[dict]:
    docs = await ctx.store.query(COLLECTION)
    if not docs: return None
    if account_id:
        for d in docs:
            if d.id == account_id or d.get("email") == account_id:
                return {"doc_id": d.id, **d.data}
        return None
    for d in docs:
        if d.get("is_active"): return {"doc_id": d.id, **d.data}
    return {"doc_id": docs.data[0].id, **docs.data[0].data}


# ── IMAP provider detection ───────────────────────────────────────────────

IMAP_PROVIDERS: dict = {
    "gmail.com":      {"imap_host": "imap.gmail.com",           "imap_port": 993, "smtp_host": "smtp.gmail.com",           "smtp_port": 587},
    "googlemail.com": {"imap_host": "imap.gmail.com",           "imap_port": 993, "smtp_host": "smtp.gmail.com",           "smtp_port": 587},
    "outlook.com":    {"imap_host": "outlook.office365.com",    "imap_port": 993, "smtp_host": "smtp.office365.com",       "smtp_port": 587},
    "hotmail.com":    {"imap_host": "outlook.office365.com",    "imap_port": 993, "smtp_host": "smtp.office365.com",       "smtp_port": 587},
    "live.com":       {"imap_host": "outlook.office365.com",    "imap_port": 993, "smtp_host": "smtp.office365.com",       "smtp_port": 587},
    "yahoo.com":      {"imap_host": "imap.mail.yahoo.com",      "imap_port": 993, "smtp_host": "smtp.mail.yahoo.com",      "smtp_port": 587},
    "ymail.com":      {"imap_host": "imap.mail.yahoo.com",      "imap_port": 993, "smtp_host": "smtp.mail.yahoo.com",      "smtp_port": 587},
    "aol.com":        {"imap_host": "imap.aol.com",             "imap_port": 993, "smtp_host": "smtp.aol.com",             "smtp_port": 587},
    "icloud.com":     {"imap_host": "imap.mail.me.com",         "imap_port": 993, "smtp_host": "smtp.mail.me.com",         "smtp_port": 587},
    "me.com":         {"imap_host": "imap.mail.me.com",         "imap_port": 993, "smtp_host": "smtp.mail.me.com",         "smtp_port": 587},
    "mac.com":        {"imap_host": "imap.mail.me.com",         "imap_port": 993, "smtp_host": "smtp.mail.me.com",         "smtp_port": 587},
    "zoho.com":       {"imap_host": "imap.zoho.com",            "imap_port": 993, "smtp_host": "smtp.zoho.com",            "smtp_port": 587},
    "webhostmost.com":{"imap_host": "mail.webhostmost.com",     "imap_port": 993, "smtp_host": "mail.webhostmost.com",     "smtp_port": 587},
    "yandex.ru":      {"imap_host": "imap.yandex.ru",           "imap_port": 993, "smtp_host": "smtp.yandex.ru",           "smtp_port": 465},
    "yandex.com":     {"imap_host": "imap.yandex.ru",           "imap_port": 993, "smtp_host": "smtp.yandex.ru",           "smtp_port": 465},
    "mail.ru":        {"imap_host": "imap.mail.ru",             "imap_port": 993, "smtp_host": "smtp.mail.ru",             "smtp_port": 465},
    "bk.ru":          {"imap_host": "imap.mail.ru",             "imap_port": 993, "smtp_host": "smtp.mail.ru",             "smtp_port": 465},
    "list.ru":        {"imap_host": "imap.mail.ru",             "imap_port": 993, "smtp_host": "smtp.mail.ru",             "smtp_port": 465},
    "inbox.ru":       {"imap_host": "imap.mail.ru",             "imap_port": 993, "smtp_host": "smtp.mail.ru",             "smtp_port": 465},
}


def _detect_imap_settings(email_addr: str) -> dict:
    domain = email_addr.split("@")[-1].lower()
    return IMAP_PROVIDERS.get(domain, {
        "imap_host": f"mail.{domain}", "imap_port": 993,
        "smtp_host": f"mail.{domain}", "smtp_port": 587,
    })


# ── IMAP folder candidates (tried in order) ───────────────────────────────
IMAP_FOLDER_CANDIDATES: dict = {
    "sent":    ["Sent", "Sent Items", "[Gmail]/Sent Mail", "INBOX.Sent"],
    "trash":   ["Trash", "[Gmail]/Trash", "Deleted Items", "Deleted Messages"],
    "spam":    ["Junk", "Spam", "[Gmail]/Spam", "Junk Email", "Bulk Mail"],
    "drafts":  ["Drafts", "[Gmail]/Drafts", "INBOX.Drafts"],
    "draft":   ["Drafts", "[Gmail]/Drafts", "INBOX.Drafts"],
    "archive": ["Archive", "[Gmail]/All Mail", "All Messages", "Archives"],
}


def _imap_hint(email_addr: str) -> str:
    domain = email_addr.split("@")[-1].lower()
    if domain in ("gmail.com", "googlemail.com"):
        return ("Gmail requires an App Password: "
                "Google Account → Security → 2-Step Verification → App Passwords.")
    if domain in ("yahoo.com", "ymail.com"):
        return "Yahoo requires an App Password: Yahoo Account Security → Generate app password."
    if domain == "aol.com":
        return "AOL requires an App Password: AOL Account Security → Generate app password."
    if domain in ("icloud.com", "me.com", "mac.com"):
        return ("iCloud requires an App-Specific Password: "
                "appleid.apple.com → Security → App-Specific Passwords.")
    if domain in ("outlook.com", "hotmail.com", "live.com", "msn.com"):
        return "Microsoft personal accounts: generate an App Password if 2FA is enabled."
    return "If 2FA is enabled, generate an App Password in your email provider's security settings."


# ── Cursor helpers ────────────────────────────────────────────────────────

def encode_cursor(provider: str, data: dict | None) -> str | None:
    if not data:
        return None
    payload = json.dumps({"p": provider, **data}, separators=(",", ":"))
    return base64.urlsafe_b64encode(payload.encode()).decode().rstrip("=")


def decode_cursor(cursor: str | None) -> dict | None:
    if not cursor:
        return None
    padded = cursor + "=" * (-len(cursor) % 4)
    return json.loads(base64.urlsafe_b64decode(padded))
