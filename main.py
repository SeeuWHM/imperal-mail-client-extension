"""Mail Client v4.3.0 · Multi-provider email for Imperal Cloud."""
from __future__ import annotations

import sys, os
_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _dir)
for _m in [k for k in sys.modules if k in (
    "app", "handlers_connect", "handlers_inbox", "handlers_manage",
    "handlers_contacts", "handlers_panel_compose", "handlers_panel_actions",
    "skeleton", "panels", "panels_email_viewer", "panels_compose",
    "panels_accounts", "panels_add_account",
)]:
    del sys.modules[_m]

from app import ext, chat  # noqa: F401

import handlers_connect           # noqa: F401
import handlers_inbox             # noqa: F401
import handlers_manage            # noqa: F401
import handlers_contacts          # noqa: F401
import handlers_panel_compose     # noqa: F401
import handlers_panel_actions     # noqa: F401
import skeleton                   # noqa: F401
import panels_email_viewer        # noqa: F401
import panels_compose             # noqa: F401
import panels_accounts            # noqa: F401
import panels_add_account         # noqa: F401
import panels                     # noqa: F401
