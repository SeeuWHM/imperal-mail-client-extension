"""Tests for the Accounts/Filters right panel (panels_accounts.py).

Covers the visual-identity split between the two tabs (blue/green Accounts
vs. purple/orange Filters, as requested so the two switchable modes read as
distinct at a glance) plus the header text/subtitle changing with the active
tab. All account/store I/O is mocked -- no live credentials needed, matching
the pattern in tests/test_email_viewer_panel.py.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

import panels_accounts as pa


def _find_nodes(n, node_type):
    found = []
    if getattr(n, "type", None) == node_type:
        found.append(n)
    children = (getattr(n, "props", {}) or {}).get("children", []) or []
    for child in children:
        found.extend(_find_nodes(child, node_type))
    items = (getattr(n, "props", {}) or {}).get("items", []) or []
    for item in items:
        found.extend(_find_nodes(item, node_type))
    return found


class FakeDoc:
    def __init__(self, id_, data):
        self.id = id_
        self.data = data


class FakePage:
    def __init__(self, data):
        self.data = data


# ── Accounts tab: blue/green identity ───────────────────────────────────────

@pytest.mark.asyncio
async def test_accounts_tab_has_blue_green_stat_identity(monkeypatch):
    accounts = [
        {"email": "<EMAIL>", "provider": "google", "is_active": True, "unread_count": 3},
    ]
    monkeypatch.setattr(pa, "_all_accounts", AsyncMock(return_value=accounts))

    node = await pa._build_accounts_tab(object())

    stats = _find_nodes(node, "Stat")
    assert stats, "expected Stat nodes in the Accounts tab"
    colors = {s.props.get("color") for s in stats}
    assert "blue" in colors or "green" in colors, "Accounts tab should use its blue/green identity"
    assert not any(s.props.get("color") in ("purple", "orange") for s in stats), (
        "Accounts tab must not borrow Filters' purple/orange identity"
    )


@pytest.mark.asyncio
async def test_accounts_tab_empty_state_offers_add_account(monkeypatch):
    monkeypatch.setattr(pa, "_all_accounts", AsyncMock(return_value=[]))
    node = await pa._build_accounts_tab(object())
    buttons = _find_nodes(node, "Button")
    assert any(b.props.get("label") == "Add Account" for b in buttons)


# ── Filters tab: purple/orange identity ─────────────────────────────────────

@pytest.mark.asyncio
async def test_filters_tab_has_purple_orange_stat_identity(monkeypatch):
    ctx = MagicMock()
    ctx.user.imperal_id = "imp_u_test"
    ctx.store.query = AsyncMock(return_value=FakePage([
        FakeDoc("f1", {"name": "LinkedIn", "color": "purple", "criteria_from": "linkedin.com"}),
    ]))
    monkeypatch.setattr(pa, "_active_account", AsyncMock(return_value={"email": "<EMAIL>"}))

    node = await pa._build_filters_tab(ctx)

    stats = _find_nodes(node, "Stat")
    assert stats, "expected Stat nodes in the Filters tab"
    colors = {s.props.get("color") for s in stats}
    assert "purple" in colors or "orange" in colors, "Filters tab should use its purple/orange identity"
    assert not any(s.props.get("color") in ("blue", "green") for s in stats), (
        "Filters tab must not borrow Accounts' blue/green identity"
    )


@pytest.mark.asyncio
async def test_filters_tab_empty_state_suggests_creating_one(monkeypatch):
    ctx = MagicMock()
    ctx.user.imperal_id = "imp_u_test"
    ctx.store.query = AsyncMock(return_value=FakePage([]))
    monkeypatch.setattr(pa, "_active_account", AsyncMock(return_value={"email": "<EMAIL>"}))

    node = await pa._build_filters_tab(ctx)

    alerts = _find_nodes(node, "Alert")
    assert any("filter" in (a.props.get("message") or "").lower() for a in alerts)


# ── Entry point: header follows the active tab ──────────────────────────────

@pytest.mark.asyncio
async def test_header_switches_with_active_tab(monkeypatch):
    monkeypatch.setattr(pa, "_all_accounts", AsyncMock(return_value=[]))
    ctx = MagicMock()
    ctx.user.imperal_id = "imp_u_test"
    ctx.store.query = AsyncMock(return_value=FakePage([]))
    monkeypatch.setattr(pa, "_active_account", AsyncMock(return_value={"email": "<EMAIL>"}))

    accounts_node = await pa.build_accounts_panel(ctx, tab="accounts")
    filters_node = await pa.build_accounts_panel(ctx, tab="filters")

    accounts_headers = _find_nodes(accounts_node, "Header")
    filters_headers = _find_nodes(filters_node, "Header")
    assert accounts_headers and filters_headers
    assert accounts_headers[0].props.get("text") != filters_headers[0].props.get("text"), (
        "the panel header must change between Accounts and Filters, not stay a static label"
    )
