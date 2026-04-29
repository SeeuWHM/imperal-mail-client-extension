"""Mail Client — Extension instance + lifecycle (SDK v3.x / ChatExtension)."""
from __future__ import annotations

import logging
from pathlib import Path

from imperal_sdk import Extension
from imperal_sdk.chat import ChatExtension

from providers.helpers import _all_accounts

log = logging.getLogger("mail")

# ── System prompt ─────────────────────────────────────────────────────────────

_SYSTEM_PROMPT = (Path(__file__).parent / "system_prompt.txt").read_text()

# ── Extension + ChatExtension ─────────────────────────────────────────────────

ext = Extension(
    "mail",
    version="5.0.0",
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
    system_prompt=_SYSTEM_PROMPT,
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


@ext.on_event("email.received")
async def on_email_received(ctx, event):
    log.info(f"Mail event handler: {event.get('event_type', '?')}")
