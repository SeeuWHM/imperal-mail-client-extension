"""Federal-grade tests for the email viewer panel (panels_email_viewer.py):

- honest forward detection (subject prefix only — no guessing)
- honest replied detection for Google/Microsoft, derived from real thread data
  instead of always False (Gmail/Graph read_email has no \\Answered-equivalent
  flag; IMAP's own flag still wins when the provider gives one)
- truncated-body warning surfaces when the provider says the body was cut
- Conversation tab only appears when the provider can actually serve a thread
  (IMAP/Yahoo get_thread() is a hard error — never show a dead-end tab)

All provider I/O is mocked — no live credentials needed, matching the pattern
used across tests/test_skeleton.py and tests/test_read_attachment.py.
"""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

import panels_email_viewer as pv


# ── _is_forwarded: pure, subject-prefix only ─────────────────────────────────

def test_is_forwarded_detects_fwd_prefix():
    assert pv._is_forwarded("Fwd: quarterly report")
    assert pv._is_forwarded("FW: quarterly report")
    assert pv._is_forwarded("  fwd:   loose whitespace")


def test_is_forwarded_false_for_plain_or_reply_subjects():
    assert not pv._is_forwarded("quarterly report")
    assert not pv._is_forwarded("Re: quarterly report")
    assert not pv._is_forwarded("")
    assert not pv._is_forwarded(None)


# ── _really_replied: honest derivation from thread data ──────────────────────

def test_really_replied_true_when_later_message_from_own_address():
    messages = [
        {"id": "m1", "from": "someone@example.com", "date": "Mon, 1 Jan 2026 10:00:00 +0000"},
        {"id": "m2", "from": "Me <me@example.com>", "date": "Mon, 1 Jan 2026 11:00:00 +0000"},
    ]
    assert pv._really_replied(messages, "m1", "Mon, 1 Jan 2026 10:00:00 +0000", "me@example.com")


def test_really_replied_false_when_own_reply_is_earlier_not_later():
    messages = [
        {"id": "m0", "from": "me@example.com", "date": "Mon, 1 Jan 2026 09:00:00 +0000"},
        {"id": "m1", "from": "someone@example.com", "date": "Mon, 1 Jan 2026 10:00:00 +0000"},
    ]
    assert not pv._really_replied(messages, "m1", "Mon, 1 Jan 2026 10:00:00 +0000", "me@example.com")


def test_really_replied_false_when_no_own_address_in_thread():
    messages = [
        {"id": "m1", "from": "someone@example.com", "date": "Mon, 1 Jan 2026 10:00:00 +0000"},
        {"id": "m2", "from": "other@example.com", "date": "Mon, 1 Jan 2026 11:00:00 +0000"},
    ]
    assert not pv._really_replied(messages, "m1", "Mon, 1 Jan 2026 10:00:00 +0000", "me@example.com")


def test_really_replied_false_on_empty_messages_or_no_account():
    assert not pv._really_replied([], "m1", "", "me@example.com")
    assert not pv._really_replied([{"id": "m2", "from": "me@example.com"}], "m1", "", "")


# ── build_email_viewer: end-to-end panel assembly ────────────────────────────

class FakeProvider:
    def __init__(self, read_result: dict, thread_result: dict | None = None):
        self.read_email = AsyncMock(return_value=read_result)
        self.get_thread = AsyncMock(return_value=thread_result or {})


def _base_email_result(**overrides) -> dict:
    result = {
        "RESULT": "SUCCESS",
        "message_id": "msg1",
        "subject": "Quarterly report",
        "from": "someone@example.com",
        "to": "me@example.com",
        "cc": "",
        "date": "Mon, 1 Jan 2026 10:00:00 +0000",
        "body": "<p>hello</p>",
        "body_type": "html",
        "attachments": [],
        "thread_id": "",
        "replied": False,
        "truncated": False,
    }
    result.update(overrides)
    return result


@pytest.mark.asyncio
async def test_forwarded_badge_shown_for_fwd_subject(monkeypatch):
    acc = {"email": "me@example.com", "provider": "oauth"}
    provider = FakeProvider(_base_email_result(subject="Fwd: quarterly report"))
    monkeypatch.setattr(pv, "_get_acc", AsyncMock(return_value=(acc, provider)))

    node = await pv.build_email_viewer(object(), "msg1", account="me@example.com")

    rendered = str(node)
    assert "Forwarded" in rendered


@pytest.mark.asyncio
async def test_imap_style_account_never_shows_conversation_tab(monkeypatch):
    """thread_id present but provider is imap -> get_thread() would hard-error,
    so the tab must not be offered at all (no dead-end click)."""
    acc = {"email": "me@example.com", "provider": "imap"}
    provider = FakeProvider(_base_email_result(thread_id="thread1"))
    monkeypatch.setattr(pv, "_get_acc", AsyncMock(return_value=(acc, provider)))

    await pv.build_email_viewer(object(), "msg1", account="me@example.com")

    provider.get_thread.assert_not_awaited()


@pytest.mark.asyncio
async def test_oauth_account_with_thread_id_fetches_conversation_and_derives_replied(monkeypatch):
    acc = {"email": "me@example.com", "provider": "oauth"}
    thread_messages = [
        {"id": "msg1", "from": "someone@example.com", "subject": "Quarterly report",
         "date": "Mon, 1 Jan 2026 10:00:00 +0000", "body": "hello", "unread": False},
        {"id": "msg2", "from": "Me <me@example.com>", "subject": "Re: Quarterly report",
         "date": "Mon, 1 Jan 2026 11:00:00 +0000", "body": "reply body", "unread": False},
    ]
    provider = FakeProvider(
        _base_email_result(thread_id="thread1", replied=False),
        thread_result={"RESULT": "SUCCESS", "messages": thread_messages, "total": 2},
    )
    monkeypatch.setattr(pv, "_get_acc", AsyncMock(return_value=(acc, provider)))

    node = await pv.build_email_viewer(object(), "msg1", account="me@example.com")

    provider.get_thread.assert_awaited_once()
    rendered = str(node)
    assert "Conversation" in rendered
    assert "Replied" in rendered  # derived honestly from the thread, not the always-False flag


@pytest.mark.asyncio
async def test_truncated_body_shows_warning(monkeypatch):
    acc = {"email": "me@example.com", "provider": "imap"}
    provider = FakeProvider(_base_email_result(truncated=True))
    monkeypatch.setattr(pv, "_get_acc", AsyncMock(return_value=(acc, provider)))

    node = await pv.build_email_viewer(object(), "msg1", account="me@example.com")

    rendered = str(node)
    assert "shortened" in rendered


@pytest.mark.asyncio
async def test_thread_error_surfaces_as_alert_not_swallowed(monkeypatch):
    acc = {"email": "me@example.com", "provider": "oauth"}
    provider = FakeProvider(
        _base_email_result(thread_id="thread1"),
        thread_result={"RESULT": "ERROR", "error": "Thread thread1 not found."},
    )
    monkeypatch.setattr(pv, "_get_acc", AsyncMock(return_value=(acc, provider)))

    node = await pv.build_email_viewer(object(), "msg1", account="me@example.com")

    rendered = str(node)
    assert "not found" in rendered
