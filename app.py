"""Mail Client — Extension instance + lifecycle (SDK v5.3.0 / SDL)."""
from __future__ import annotations

import logging

from imperal_sdk import Extension
from imperal_sdk.chat import ChatExtension

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

# ── Developer-owned shared secrets (set once in Dev Portal, used by all users) ─

ext.secret(
    name="google_client_id",
    description="Google OAuth Client ID — from Google Cloud Console → APIs & Services → Credentials",
    write_mode="extension",
    required=True,
)(lambda: None)

ext.secret(
    name="google_client_secret",
    description="Google OAuth Client Secret — from Google Cloud Console → APIs & Services → Credentials",
    write_mode="extension",
    required=True,
)(lambda: None)

ext.secret(
    name="microsoft_client_id",
    description="Microsoft OAuth Client ID — from Azure AD App Registration",
    write_mode="extension",
    required=True,
)(lambda: None)

ext.secret(
    name="microsoft_client_secret",
    description="Microsoft OAuth Client Secret — from Azure AD App Registration",
    write_mode="extension",
    required=True,
)(lambda: None)

ext.secret(
    name="yahoo_client_id",
    description="Yahoo OAuth Client ID — from Yahoo Developer Console",
    write_mode="extension",
    required=True,
)(lambda: None)

ext.secret(
    name="yahoo_client_secret",
    description="Yahoo OAuth Client Secret — from Yahoo Developer Console",
    write_mode="extension",
    required=True,
)(lambda: None)

ext.secret(
    name="imap_encryption_key",
    description="Fernet key for encrypting IMAP passwords at rest — generate with Fernet.generate_key()",
    write_mode="extension",
    required=True,
)(lambda: None)

# ── Extension-managed per-user secrets ────────────────────────────────────────

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


