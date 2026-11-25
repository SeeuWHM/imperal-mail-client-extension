"""Tests for email analytics and sender volume aggregation."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from handlers_inbox_impl import impl_top_senders
from handlers_cleanup_impl import impl_inbox_analytics
from mail_providers.text_utils import _parse_sender


def test_parse_sender_various_formats():
    assert _parse_sender("John Doe <john@example.com>") == ("John Doe", "john@example.com")
    assert _parse_sender('"Acme Alerts" <alerts@acme.org>') == ("Acme Alerts", "alerts@acme.org")
    assert _parse_sender("<no-name@domain.com>") == ("no-name@domain.com", "no-name@domain.com")
    assert _parse_sender("simple@example.com") == ("simple@example.com", "simple@example.com")
    assert _parse_sender("Plain Display Name") == ("Plain Display Name", "")
    assert _parse_sender("") == ("unknown", "")


@pytest.mark.asyncio
async def test_impl_top_senders_fast_path():
    ctx = MagicMock()
    mock_results = [
        {"from": "Alice <alice@test.com>", "from_email": "alice@test.com"},
        {"from": "Alice <alice@test.com>", "from_email": "alice@test.com"},
        {"from": "Alice <alice@test.com>", "from_email": "alice@test.com"},
        {"from": "Bob <bob@test.com>", "from_email": "bob@test.com"},
        {"from": "Carol <carol@other.org>", "from_email": "carol@other.org"},
    ]
    mock_sr = MagicMock()
    mock_sr.results = mock_results

    with patch("handlers_inbox_impl._get_acc", new=AsyncMock(return_value=({"email": "me@test.com"}, MagicMock()))), \
         patch("handlers_inbox_impl.impl_search", new=AsyncMock(return_value=mock_sr)):

        senders = await impl_top_senders(ctx, days=30, limit=2)
        assert len(senders) == 2
        assert senders[0]["email"] == "alice@test.com"
        assert senders[0]["count"] == 3
        assert senders[0]["sender"] == "Alice"
        assert senders[1]["email"] == "bob@test.com"
        assert senders[1]["count"] == 1


@pytest.mark.asyncio
async def test_impl_inbox_analytics_domain_grouping():
    ctx = MagicMock()
    mock_top_senders = [
        {"sender": "Alice", "email": "alice@company.com", "count": 15},
        {"sender": "Bob", "email": "bob@company.com", "count": 10},
        {"sender": "News", "email": "news@newsletter.io", "count": 8},
        {"sender": "Support", "email": "help@service.net", "count": 5},
    ]

    with patch("handlers_cleanup_impl.impl_top_senders", new=AsyncMock(return_value=mock_top_senders)):
        domains = await impl_inbox_analytics(ctx, period_days=30, group_by="domain", limit=2)
        assert len(domains) == 2
        # company.com should have 15 + 10 = 25
        assert domains[0]["sender"] == "company.com"
        assert domains[0]["email"] == "*@company.com"
        assert domains[0]["count"] == 25
        # newsletter.io should have 8
        assert domains[1]["sender"] == "newsletter.io"
        assert domains[1]["count"] == 8
