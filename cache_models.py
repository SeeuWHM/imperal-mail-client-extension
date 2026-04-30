"""Mail Client · ctx.cache model registrations (SDK v1.6.0).

Registers the pure Pydantic classes from ``cache_model_defs`` with the
module-level ``ext`` instance. Handler modules import the class objects
directly from ``cache_model_defs`` to avoid re-entering ``app`` during
tool-class construction.

Constraints (enforced by CacheClient):
- value serialised <= 64 KB (I-CACHE-VALUE-SIZE-CAP-64KB)
- TTL in [5, 300] s (I-CACHE-TTL-CAP-300S)
- key syntax ``[A-Za-z0-9_\\-:]+`` length <= 128 (I-CACHE-KEY-SAFETY)
"""
from __future__ import annotations

from app import ext

from cache_model_defs import AccountList, InboxManifest, InboxMessages, InboxPage, UnreadSummary


__all__ = ["AccountList", "InboxManifest", "InboxMessages", "InboxPage", "UnreadSummary"]


ext.cache_model("inbox_page")(InboxPage)
ext.cache_model("inbox_messages")(InboxMessages)
ext.cache_model("unread_summary")(UnreadSummary)
ext.cache_model("account_list")(AccountList)
ext.cache_model("inbox_manifest")(InboxManifest)
