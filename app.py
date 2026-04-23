"""Mail Client · Shared state & extension setup."""
from __future__ import annotations

import logging

from imperal_sdk import Extension, Context
from imperal_sdk.chat import ChatExtension, ActionResult

from providers import get_provider
from providers.helpers import _all_accounts, _active_account, COLLECTION

log = logging.getLogger("mail")


# ─── Helpers ──────────────────────────────────────────────────────────── #

def _user_id(ctx) -> str:
    return ctx.user.id if hasattr(ctx, "user") and ctx.user else ""


async def _get_acc(ctx: Context, account: str = ""):
    """Resolve active account and provider. Returns (acc, provider) or (None, None)."""
    acc = await _active_account(ctx, account)
    if not acc:
        return None, None
    return acc, get_provider(acc)


def _no_account_error() -> ActionResult:
    return ActionResult.error("No email account connected. Connect one first.")


def _wrap_provider_result(result: dict, summary: str) -> ActionResult:
    """Convert provider dict (RESULT: SUCCESS/ERROR) to ActionResult."""
    if result.get("RESULT") == "ERROR":
        err = result.get("error", "Unknown provider error")
        retryable = any(k in err.lower() for k in ("rate", "timeout", "timed out", "network", "connect"))
        return ActionResult.error(err, retryable=retryable)
    data = {k: v for k, v in result.items() if k != "RESULT"}
    return ActionResult.success(data=data, summary=summary)


# ─── System Prompt ────────────────────────────────────────────────────── #

from pathlib import Path as _Path
SYSTEM_PROMPT = (_Path(__file__).parent / "system_prompt.txt").read_text()


# ─── Extension ────────────────────────────────────────────────────────── #

ext = Extension("mail", version="4.3.0")

chat = ChatExtension(
    ext=ext,
    tool_name="tool_mail_client_chat",
    description=(
        "Mail Client — inbox, read, send, reply, forward, search, archive, delete, "
        "star, mark read/unread, browse folders, view threads, bulk operations. "
        "Connect Google, Microsoft Outlook, Yahoo, AOL, iCloud, or any IMAP/SMTP provider."
    ),
    system_prompt=SYSTEM_PROMPT,
    model="claude-haiku-4-5-20251001",
)


# ─── Health Check ─────────────────────────────────────────────────────── #

@ext.health_check
async def health(ctx) -> dict:
    accounts = await _all_accounts(ctx)
    return {"status": "ok", "version": ext.version, "accounts_connected": len(accounts)}


# ─── Lifecycle Hooks ──────────────────────────────────────────────────── #

@ext.on_install
async def on_install(ctx):
    log.info(f"mail installed for user {ctx.user.id if ctx and hasattr(ctx, 'user') and ctx.user else 'system'}")


# ─── Event Handlers ───────────────────────────────────────────────────── #

@ext.on_event("email.received")
async def on_email_received(ctx, event):
    log.info(f"Mail event handler: {event.get('event_type', '?')}")
