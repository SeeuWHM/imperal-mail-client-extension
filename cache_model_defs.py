"""Mail Client · ctx.cache model classes (pure Pydantic).

Separated from ``cache_models.py`` registration so handler modules can
import model classes without triggering the ``app → tools → handlers_* →
cache_models → app`` cycle. Registration against ``ext`` still happens
in ``cache_models.py`` which is loaded by ``main.py`` right after ``ext``
is constructed.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class InboxPage(BaseModel):
    """A single page of inbox messages returned by provider.fetch_page.

    ``messages`` is kept as ``list[dict]`` — MessagePreview shape is provider-
    specific (Gmail/Graph/IMAP normalised), migration to a typed shape can
    happen in a later SDK bump.
    """
    account_id: str
    folder: str
    cursor: str = ""
    messages: list[dict[str, Any]] = Field(default_factory=list)
    next_cursor: str = ""
    has_more: bool = False
    fetched_at: datetime


class UnreadSummary(BaseModel):
    """Per-account unread count for the INBOX folder."""
    account_id: str
    folder: str = "INBOX"
    unread_count: int = 0


class AccountList(BaseModel):
    """Cached list of accounts for panels/handlers that don't need fresh data."""
    accounts: list[dict[str, Any]] = Field(default_factory=list)
