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


class InboxManifest(BaseModel):
    """Prefetch manifest: total count + ordered cursor list for true pagination.

    ``cursors[n]`` is the opaque cursor that fetches page n+1.
    cursors[0] is always "" (first page, no cursor).
    ``preloaded`` indicates how many pages are currently in ctx.cache.
    """
    account_id: str
    folder: str
    total: int = 0        # total messages in folder (0 = unknown)
    unread: int = 0
    page_size: int = 25
    cursors: list[str] = Field(default_factory=list)  # cursors[0]="", cursors[1]=cursor for page 2, etc.
    preloaded: int = 0    # how many pages are pre-cached
    fetched_at: datetime


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


class InboxMessages(BaseModel):
    """Flat list of messages for a folder — powers native ui.List pagination."""
    account_id: str
    folder: str
    messages: list[dict[str, Any]] = Field(default_factory=list)
    total_in_folder: int = 0    # from get_folder_stats
    unread_in_folder: int = 0   # total unread in folder (not per-page)
    next_cursor: str = ""       # encoded cursor for fetching the next batch
    fetched_at: datetime


class AccountList(BaseModel):
    """Cached list of accounts for panels/handlers that don't need fresh data."""
    accounts: list[dict[str, Any]] = Field(default_factory=list)
