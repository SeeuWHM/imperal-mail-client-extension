"""Mail Client v5.0.0 — Multi-provider email for Imperal Cloud (SDK v3.x)."""
from __future__ import annotations

import os
import sys

# ── Module purge (hot-reload + cross-extension sys.modules safety) ───────────
_dir = os.path.dirname(os.path.abspath(__file__))
if _dir not in sys.path:
    sys.path.insert(0, _dir)

_MODULES = (
    "app", "ctx_helpers", "schemas",
    "handlers_connect", "handlers_inbox", "handlers_manage",
    "handlers_contacts", "handlers_panel_compose", "handlers_panel_actions",
    "skeleton", "panels", "panels_email_viewer", "panels_compose",
    "panels_accounts", "panels_add_account", "cache_models", "cache_model_defs",
)
for _m in [k for k in sys.modules if k in _MODULES]:
    del sys.modules[_m]

# ── Import core + submodules ─────────────────────────────────────────────────
from app import ext, chat  # noqa: E402, F401

# Register cache models BEFORE modules that use ctx.cache.get_or_fetch.
import cache_models  # noqa: E402, F401

import handlers_connect           # noqa: E402, F401
import handlers_inbox             # noqa: E402, F401
import handlers_manage            # noqa: E402, F401
import handlers_contacts          # noqa: E402, F401
import handlers_panel_compose     # noqa: E402, F401
import handlers_panel_actions     # noqa: E402, F401
import skeleton                   # noqa: E402, F401
import panels_email_viewer        # noqa: E402, F401
import panels_compose             # noqa: E402, F401
import panels_accounts            # noqa: E402, F401
import panels_add_account         # noqa: E402, F401
import panels                     # noqa: E402, F401
