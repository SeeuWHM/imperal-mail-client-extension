"""Mail Client — Extension instance + lifecycle (SDK v5.3.0 / SDL)."""
from __future__ import annotations

import logging

from imperal_sdk import Extension
from imperal_sdk.chat import ChatExtension
from imperal_sdk.secrets.spec import SecretSpec

log = logging.getLogger("mail")

# ── Extension + ChatExtension ─────────────────────────────────────────────────

ext = Extension(
    "mail",
    version="6.5.1",
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

# File Mage L3 — declares this app as a valid destination when the user has
# an uploaded file (via the file-reader system ext) and wants it emailed.
# `arg="body"` maps the file's EXTRACTED TEXT into the existing `body` field
# (arg_kind="text") — `send`'s own alias handling (body/content/message/text)
# and is_html detection are unchanged; this is just another way to fill body.
# Text-only source formats since body expects text/markup, not a structured
# document — a plain document upload becomes the actual email content.
ext.file_sink(
    "send",
    accepts=["text/*", "text/html"],
    arg="body",
    arg_kind="text",
    description="Send an uploaded document's content as a new email",
)

# ── Unified platform OAuth — gateway handles code exchange, account storage ──

ext.oauth("google",
          collection="gmail_accounts",
          scopes=["https://www.googleapis.com/auth/gmail.modify",
                  "https://www.googleapis.com/auth/contacts.readonly"])
ext.oauth("microsoft",
          collection="gmail_accounts",
          scopes=["https://graph.microsoft.com/Mail.ReadWrite",
                  "https://graph.microsoft.com/Mail.Send",
                  "https://graph.microsoft.com/User.Read",
                  "https://graph.microsoft.com/Contacts.Read",
                  "offline_access"])
ext.oauth("yahoo",
          collection="gmail_accounts",
          scopes=["openid", "mail-r", "mail-w"])

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

ext.secret(
    name="imap_credentials",
    description="IMAP account passwords — JSON dict keyed by email, managed automatically by the extension",
    write_mode="extension",
    max_bytes=65536,
)(lambda: None)

# ── Lifecycle ─────────────────────────────────────────────────────────────────

@ext.health_check
async def health(ctx) -> dict:
    # App-level probe, no user context — ctx.store is per-user and raises here
    # (kernel I-HEALTH-CTX-HONEST, 2026-07-13). Static liveness only.
    return {"status": "ok", "version": ext.version}


@ext.on_install
async def on_install(ctx):
    uid = ctx.user.imperal_id if ctx and hasattr(ctx, "user") and ctx.user else "system"
    log.info(f"mail installed for user {uid}")


