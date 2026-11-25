"""Tests for Gmail filter synchronization, creation, deletion, and query formatting."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from mail_providers.google_filters import GoogleFilterMixin
from panels_filter_view import _build_filter_query


class FakeGoogleProvider(GoogleFilterMixin):
    @staticmethod
    def ok(**kwargs):
        return {"RESULT": "SUCCESS", **kwargs}

    @staticmethod
    def err(error):
        return {"RESULT": "ERROR", "error": error}


@pytest.mark.asyncio
async def test_google_filter_mixin_list_filters():
    provider = FakeGoogleProvider()
    ctx = MagicMock()
    acc = {"email": "test@gmail.com"}

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "filter": [
            {
                "id": "filter_123",
                "criteria": {"from": "newsletter@example.com", "subject": "Daily Digest"},
                "action": {"removeLabelIds": ["INBOX"], "addLabelIds": ["Label_1"]},
            },
            {
                "id": "filter_456",
                "criteria": {"query": "is:unread unsubscribe"},
                "action": {"removeLabelIds": ["UNREAD"]},
            },
        ]
    }

    with patch("mail_providers.google_filters._api_get", new=AsyncMock(return_value=mock_resp)):
        filters = await provider.list_filters(ctx, acc)
        assert len(filters) == 2
        assert filters[0]["id"] == "filter_123"
        assert filters[0]["criteria_from"] == "newsletter@example.com"
        assert filters[0]["criteria_subject"] == "Daily Digest"
        assert "From: newsletter@example.com" in filters[0]["name"]
        assert filters[1]["id"] == "filter_456"
        assert filters[1]["criteria_query"] == "is:unread unsubscribe"


@pytest.mark.asyncio
async def test_google_filter_mixin_create_filter():
    provider = FakeGoogleProvider()
    ctx = MagicMock()
    acc = {"email": "test@gmail.com"}

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "id": "new_filt_789",
        "criteria": {"from": "alerts@service.io"},
        "action": {"addLabelIds": ["STARRED"]},
    }

    with patch("mail_providers.google_filters._api_post", new=AsyncMock(return_value=mock_resp)):
        res = await provider.create_filter(
            ctx, acc,
            criteria={"from": "alerts@service.io"},
            action={"addLabelIds": ["STARRED"]}
        )
        assert res["RESULT"] == "SUCCESS"
        assert res["filter_id"] == "new_filt_789"


@pytest.mark.asyncio
async def test_google_filter_mixin_delete_filter():
    provider = FakeGoogleProvider()
    ctx = MagicMock()
    acc = {"email": "test@gmail.com"}

    mock_resp = MagicMock()
    mock_resp.status_code = 200

    with patch("mail_providers.google_filters._api_delete", new=AsyncMock(return_value=mock_resp)):
        res = await provider.delete_filter(ctx, acc, "new_filt_789")
        assert res["RESULT"] == "SUCCESS"
        assert res["deleted"] is True
        assert res["filter_id"] == "new_filt_789"


def test_build_filter_query_from_emails_single_and_multi():
    q1 = _build_filter_query({"criteria_from_emails": ["support@example.com"]})
    assert q1 == "from:support@example.com"

    q2 = _build_filter_query({"criteria_from_emails": ["a@ex.com", "b@ex.com"]})
    assert q2 == "(from:a@ex.com OR from:b@ex.com)"


def test_build_filter_query_from_contains_and_subject():
    q = _build_filter_query({
        "criteria_from": "github.com",
        "criteria_subject": "Security Alert",
        "criteria_folder": "INBOX",
    })
    assert 'from:github.com' in q
    assert 'subject:"Security Alert"' in q
    assert 'in:inbox' in q


def test_build_filter_query_with_native_criteria_query():
    q = _build_filter_query({
        "criteria_query": "has:attachment filename:pdf",
        "criteria_to": "me@example.com",
    })
    assert "to:me@example.com" in q
    assert "has:attachment filename:pdf" in q
