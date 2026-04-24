"""
Mail Client — Extension instance + lifecycle (SDK v2.0.0).

Migration notes (2026-04-24, Plan 3 Task 3):
  * Base class switched from legacy ``ChatExtension`` to v2 ``Extension``.
    The :class:`~tools.MailExtension` subclass in ``tools.py`` registers
    every tool via ``@sdk_ext.tool(output_schema=...)``. Webbee Narrator
    grounds user-facing prose against those schemas kernel-side, so the
    per-extension ``system_prompt.txt`` is gone.
  * Panels (``panels.py`` / ``panels_*.py``), skeleton (``skeleton.py``),
    cache models (``cache_models.py``) + health check keep their v1
    instance-based decorators (``@ext.panel`` / ``@ext.skeleton`` /
    ``@ext.cache_model`` / ``@ext.health_check``) — those surfaces are
    unchanged in v2.0.0 and register against the module-level ``ext``.
  * Business logic stays in ``handlers_*.py`` as ``impl_*`` functions so
    the envelope swap (ActionResult → Pydantic return) is minimal.
  * Context helpers (``_user_id`` / ``_get_acc``) live in ``ctx_helpers``
    to keep the import graph acyclic — ``tools.py`` imports the handler
    modules, which imported ``_get_acc`` from here in v1; moving them
    out breaks the ``app → tools → handlers_* → app`` cycle.
"""
from __future__ import annotations

import logging

from providers.helpers import _all_accounts

from tools import MailExtension

log = logging.getLogger("mail")


# ── Extension instance ────────────────────────────────────────────────────────
#
# Module-level ``ext`` so v1 instance-based decorators (``@ext.panel`` /
# ``@ext.skeleton`` / ``@ext.cache_model`` / ``@ext.health_check``) continue
# to register across panels.py / skeleton.py / cache_models.py without edits.

ext = MailExtension(app_id="mail", version="5.0.0")


# ── Lifecycle ─────────────────────────────────────────────────────────────────


@ext.health_check
async def health(ctx) -> dict:
    accounts = await _all_accounts(ctx)
    return {"status": "ok", "version": ext.version, "accounts_connected": len(accounts)}


@ext.on_install
async def on_install(ctx):
    log.info(
        f"mail installed for user {ctx.user.id if ctx and hasattr(ctx, 'user') and ctx.user else 'system'}"
    )


@ext.on_event("email.received")
async def on_email_received(ctx, event):
    log.info(f"Mail event handler: {event.get('event_type', '?')}")
