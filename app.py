"""Mail Client — Extension instance + lifecycle (SDK v5.2.0 / SDL)."""
from __future__ import annotations

import logging

from imperal_sdk import Extension
from imperal_sdk.chat import ChatExtension

from providers.helpers import _all_accounts

log = logging.getLogger("mail")

# ── Extension + ChatExtension ─────────────────────────────────────────────────

ext = Extension(
    "mail",
    version="5.8.0",
    display_name="Mail Client",
    description=(
        "Multi-provider email client — Google, Microsoft, Yahoo, IMAP. "
        "Inbox, send, reply, forward, search, archive, manage emails, contacts."
    ),
    icon="mail.svg",
    actions_explicit=True,
    capabilities=["store:read", "store:write", "notify:push"],
)

chat = ChatExtension(
    ext=ext,
    tool_name="tool_mail_client_chat",
    description=(
        "Mail Client — inbox, read emails, send, reply, forward, search, archive, "
        "delete, mark read/unread, star, browse folders, view threads, bulk operations, "
        "contacts CRUD + sync. Connect Google, Microsoft, Yahoo, IMAP."
    ),
)

# ── Lifecycle ─────────────────────────────────────────────────────────────────

@ext.health_check
async def health(ctx) -> dict:
    accounts = await _all_accounts(ctx)
    return {"status": "ok", "version": ext.version, "accounts_connected": len(accounts)}


@ext.on_install
async def on_install(ctx):
    uid = ctx.user.imperal_id if ctx and hasattr(ctx, "user") and ctx.user else "system"
    log.info(f"mail installed for user {uid}")


