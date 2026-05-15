"""Mail Client · ctx.cache model classes (pure Pydantic).

Separated from ``cache_models.py`` registration so handler modules can
import model classes without triggering the ``app → tools → handlers_* →
cache_models → app`` cycle. Registration against ``ext`` still happens
in ``cache_models.py`` which is loaded by ``main.py`` right after ``ext``
is constructed.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field



class UnreadSummary(BaseModel):
    """Per-account unread count for the INBOX folder."""
    account_id: str
    folder: str = "INBOX"
    unread_count: int = 0


class InboxMessages(BaseModel):
    """Flat list of messages for a folder — powers native ui.List pagination."""
    account_id: str
    folder: str
    messages: list[dict[str, Any]] = Field(default_factory=list)
    total_in_folder: int = 0    # from get_folder_stats
    unread_in_folder: int = 0   # total unread in folder (not per-page)
    next_cursor: str = ""       # encoded cursor for fetching the next batch
    fetched_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class AccountList(BaseModel):
    """Cached list of accounts for panels/handlers that don't need fresh data."""
    accounts: list[dict[str, Any]] = Field(default_factory=list)
