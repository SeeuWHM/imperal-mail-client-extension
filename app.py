"""Mail Client — Extension instance + lifecycle (SDK v5.3.0 / SDL)."""
from __future__ import annotations

import logging

from imperal_sdk import Extension
from imperal_sdk.chat import ChatExtension
from imperal_sdk.secrets.spec import SecretSpec

from providers.helpers import _all_accounts

log = logging.getLogger("mail")

# ── Extension + ChatExtension ─────────────────────────────────────────────────

ext = Extension(
    "mail",
    version="6.3.0",
    display_name="Mail Client",
    description=(
        "Multi-provider email client — Google, Microsoft, Yahoo, IMAP. "
        "Inbox, send, reply, forward, search, archive, manage emails, contacts, "
        "custom folders/labels. Gmail batchModify for instant bulk operations."
    ),
    icon="mail.svg",
    actions_explicit=True,
    capabilities=["store:read", "store:write", "notify:push", "secrets:read", "secrets:write"],
)

chat = ChatExtension(
    ext=ext,
    tool_name="tool_mail_client_chat",
    description=(
        "Mail Client — inbox, send, reply, forward, search, archive, delete, "
        "mark read/unread, star, folders, threads, bulk operations (mark_all_matching_read), "
        "custom folder/label creation, contacts. Connect Google, Microsoft, Yahoo, IMAP."
    ),
)

# ── App-scope secrets (scope="app"): shared credentials, set once by owner ───
# Extension.secret() in SDK 5.8.1 doesn't expose scope/env_fallback yet —
# register SecretSpec directly (manifest.py reads ext._secrets, this is stable).

_APP_SECRETS = [
    ("google_client_id",        "Shared Google OAuth Client ID (developer-owned; one OAuth app for all users)",  "IMPERAL_APPSECRET_MAIL_GOOGLE_CLIENT_ID"),
    ("google_client_secret",    "Shared Google OAuth Client Secret (developer-owned)",                           "IMPERAL_APPSECRET_MAIL_GOOGLE_CLIENT_SECRET"),
    ("microsoft_client_id",     "Shared Microsoft OAuth Client ID — from Azure AD App Registration",             "IMPERAL_APPSECRET_MAIL_MICROSOFT_CLIENT_ID"),
    ("microsoft_client_secret", "Shared Microsoft OAuth Client Secret — from Azure AD App Registration",         "IMPERAL_APPSECRET_MAIL_MICROSOFT_CLIENT_SECRET"),
    ("yahoo_client_id",         "Shared Yahoo OAuth Client ID — from Yahoo Developer Console",                   "IMPERAL_APPSECRET_MAIL_YAHOO_CLIENT_ID"),
    ("yahoo_client_secret",     "Shared Yahoo OAuth Client Secret — from Yahoo Developer Console",               "IMPERAL_APPSECRET_MAIL_YAHOO_CLIENT_SECRET"),
    ("imap_encryption_key",     "Fernet key for encrypting stored IMAP passwords (set to current IMAP_ENCRYPTION_KEY value)", "IMPERAL_APPSECRET_MAIL_IMAP_ENCRYPTION_KEY"),
]
for _name, _desc, _fb in _APP_SECRETS:
    ext._secrets[_name] = SecretSpec(
        name=_name, description=_desc, scope="app", env_fallback=_fb, required=True,
    )

# ── Per-user secret — written by extension after OAuth authorize ──────────────

ext.secret(
    name="google_tokens",
    description="Google OAuth tokens per connected account — managed automatically by the extension",
    write_mode="extension",
    max_bytes=65536,
)(lambda: None)

# ── Lifecycle ─────────────────────────────────────────────────────────────────

@ext.health_check
async def health(ctx) -> dict:
    accounts = await _all_accounts(ctx)
    return {"status": "ok", "version": ext.version, "accounts_connected": len(accounts)}


@ext.on_install
async def on_install(ctx):
    uid = ctx.user.imperal_id if ctx and hasattr(ctx, "user") and ctx.user else "system"
    log.info(f"mail installed for user {uid}")


