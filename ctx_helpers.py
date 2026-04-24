"""Mail Client · Context helpers shared across handlers + panels.

Kept out of ``app.py`` so that ``handlers_*.py`` can import these without
re-entering the ``app → tools → handlers_* → app`` cycle.
"""
from __future__ import annotations

from imperal_sdk import Context

from providers import get_provider
from providers.helpers import _active_account


def _user_id(ctx) -> str:
    return ctx.user.id if hasattr(ctx, "user") and ctx.user else ""


async def _get_acc(ctx: Context, account: str = ""):
    """Resolve active account and provider. Returns (acc, provider) or (None, None)."""
    acc = await _active_account(ctx, account)
    if not acc:
        return None, None
    return acc, get_provider(acc)
