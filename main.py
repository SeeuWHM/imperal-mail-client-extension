"""Mail Client v6.2.0 — Multi-provider email for Imperal Cloud (SDK v5.3.0 / SDL)."""
from __future__ import annotations

import os
import sys

# ── Module purge (hot-reload + cross-extension sys.modules safety) ───────────
_dir = os.path.dirname(os.path.abspath(__file__))
if _dir not in sys.path:
    sys.path.insert(0, _dir)

_MODULES = (
    "app", "ctx_helpers", "schemas", "schemas_params",
    "schemas_sdl", "schemas_sdl_builders",
    "schemas_sdl_rules", "schemas_sdl_builders_rules",
    "handlers_ui",
    "handlers_connect",
    "handlers_inbox_impl", "handlers_inbox",
    "handlers_manage_impl", "handlers_manage",
    "handlers_cleanup_impl",
    "handlers_contacts", "handlers_panel_compose", "handlers_panel_actions",
    "handlers_filters", "handlers_folders",
    "panels_filters_bar", "panels_filter_view",
    "skeleton", "panels", "panels_inbox", "panels_inbox_panel",
    "panels_email_viewer", "panels_compose",
    "panels_accounts", "panels_add_account",
    "cache_models", "cache_model_defs",
)
for _m in [k for k in sys.modules if k in _MODULES]:
    del sys.modules[_m]

# ── Import core + submodules ─────────────────────────────────────────────────
from app import ext, chat  # noqa: E402, F401

# SDL entity classes must load before any handler that uses them.
import schemas_sdl                # noqa: E402, F401
import schemas_sdl_rules          # noqa: E402, F401
import schemas_sdl_builders       # noqa: E402, F401
import schemas_sdl_builders_rules  # noqa: E402, F401

# Register cache models BEFORE modules that use ctx.cache.get_or_fetch.
import cache_models  # noqa: E402, F401

import handlers_connect           # noqa: E402, F401
import handlers_inbox_impl        # noqa: E402, F401
import handlers_inbox             # noqa: E402, F401
import handlers_manage_impl       # noqa: E402, F401
import handlers_cleanup_impl      # noqa: E402, F401
import handlers_manage            # noqa: E402, F401
import handlers_contacts          # noqa: E402, F401
import handlers_panel_compose     # noqa: E402, F401
import handlers_panel_actions     # noqa: E402, F401
import handlers_filters           # noqa: E402, F401
import handlers_folders           # noqa: E402, F401
import panels_filter_view         # noqa: E402, F401
import panels_filters_bar         # noqa: E402, F401
import skeleton                   # noqa: E402, F401
import panels_email_viewer        # noqa: E402, F401
import panels_compose             # noqa: E402, F401
import panels_accounts            # noqa: E402, F401
import panels_add_account         # noqa: E402, F401
import panels_inbox_panel         # noqa: E402, F401
import panels                     # noqa: E402, F401

# Multiple extensions share one worker process and each inserts its own
# directory at sys.path[0] on load. Leaving it there after our imports are
# done means a LATER extension's plain `import app` (or any other same-named
# top-level module -- mail-client and imperal-matomo-analytics-extension both
# use the flat name `app.py`) can resolve to THIS extension's file instead of
# its own. Once our modules are cached in sys.modules under their bare names,
# the directory is no longer needed on sys.path -- remove it so it can't leak
# into a later/deferred import from another extension (this is exactly the
# `cannot import name 'SERVER_URL' from 'app'` cross-extension bleed reported
# against imperal-matomo-analytics-extension's ext_scheduler daily_summary
# job; same fix already applied in gsc-connector/bing-webmaster-connector
# after it hit them first).
if _dir in sys.path:
    sys.path.remove(_dir)
