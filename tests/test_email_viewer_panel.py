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


# ── HTML body rendering: sandbox=False (not the iframe default) ─────────────
#
# sandbox=True puts the body in an <iframe sandbox="allow-popups"> with NO
# allow-same-origin -- the parent can never read iframe.contentDocument, so
# the height-fitting ResizeObserver silently fails and the box is stuck at
# a ~300px floor no matter what max_height is set to (raising max_height
# alone, tried previously, could not fix this -- the observer never fires).
# The same sandboxed theme also forces table{display:block} on every table,
# which shreds table-based HTML email (WHMCS invoices/notices are almost
# always table-laid-out) into a stack of tiny scroll boxes.
# sandbox=False renders through sanitized dangerouslySetInnerHTML in the
# page's own `prose` typography instead -- real auto height, and prose's
# table rule is table-layout:auto, not display:block.

def _find_html_nodes(n):
    found = []
    if getattr(n, "type", None) == "Html":
        found.append(n)
    children = (getattr(n, "props", {}) or {}).get("children", []) or []
    for child in children:
        found.extend(_find_html_nodes(child))
    return found


@pytest.mark.asyncio
async def test_html_body_never_sandboxed_for_html_type(monkeypatch):
    acc = {"email": "<EMAIL>", "provider": "oauth"}
    provider = FakeProvider(_base_email_result(
        body="<table><tr><td>Invoice</td></tr></table>", body_type="html",
    ))
    monkeypatch.setattr(pv, "_get_acc", AsyncMock(return_value=(acc, provider)))

    node = await pv.build_email_viewer(object(), "msg1", account="<EMAIL>")

    html_nodes = _find_html_nodes(node)
    assert html_nodes, "expected at least one Html node in the tree"
    for html_node in html_nodes:
        assert html_node.props.get("sandbox") is False


@pytest.mark.asyncio
async def test_html_body_never_sandboxed_for_plain_text(monkeypatch):
    acc = {"email": "<EMAIL>", "provider": "oauth"}
    provider = FakeProvider(_base_email_result(body="plain text body", body_type="text"))
    monkeypatch.setattr(pv, "_get_acc", AsyncMock(return_value=(acc, provider)))

    node = await pv.build_email_viewer(object(), "msg1", account="<EMAIL>")

    html_nodes = _find_html_nodes(node)
    assert html_nodes, "expected at least one Html node in the tree"
    for html_node in html_nodes:
        assert html_node.props.get("sandbox") is False


@pytest.mark.asyncio
async def test_plain_text_body_follows_app_theme_not_forced_light(monkeypatch):
    """Plain-text mail has no design of its own -- it must render through the
    SDK's default (theme-reactive) path, not theme="light" (which forces
    dark-on-white regardless of the user's app theme). HTML mail keeps
    theme="light" on purpose (it renders the sender's own design, same as a
    real mail client) -- this test asserts the plain-text branch specifically
    does NOT set theme="light".
    """
    acc = {"email": "<EMAIL>", "provider": "oauth"}
    provider = FakeProvider(_base_email_result(body="plain text body", body_type="text"))
    monkeypatch.setattr(pv, "_get_acc", AsyncMock(return_value=(acc, provider)))

    node = await pv.build_email_viewer(object(), "msg1", account="<EMAIL>")

    html_nodes = _find_html_nodes(node)
    assert html_nodes, "expected at least one Html node in the tree"
    for html_node in html_nodes:
        assert html_node.props.get("theme") != "light", (
            "plain-text body must not force theme=\"light\" -- it should follow "
            "the app's own dark/light theme via the SDK default"
        )


@pytest.mark.asyncio
async def test_plain_text_body_not_wrapped_in_pre_tag(monkeypatch):
    """REAL root cause of "still dark-on-dark" even after omitting theme=:
    Tailwind Typography (the `prose` classes DHtml renders through) has a
    dedicated rule for <pre> -- `.prose :where(pre){color:var(
    --tw-prose-pre-code);background:var(--tw-prose-pre-bg)}` -- it treats
    <pre> as a CODE BLOCK and force-sets its own color/background, which
    wins over the inherited .text-body color regardless of theme=. Wrapping
    plain text in <pre> silently defeated the theme fix. Must use <div> (or
    any non-pre/code element) with white-space:pre-wrap instead, so the
    plain inherited .text-body color -- the actually theme-reactive one --
    is what renders.
    """
    acc = {"email": "<EMAIL>", "provider": "oauth"}
    provider = FakeProvider(_base_email_result(body="plain text body", body_type="text"))
    monkeypatch.setattr(pv, "_get_acc", AsyncMock(return_value=(acc, provider)))

    node = await pv.build_email_viewer(object(), "msg1", account="<EMAIL>")

    html_nodes = _find_html_nodes(node)
    assert html_nodes, "expected at least one Html node in the tree"
    plain_text_nodes = [n for n in html_nodes if "plain text body" in str(n.props.get("content", ""))]
    assert plain_text_nodes, "expected the plain-text body content in an Html node"
    for n in plain_text_nodes:
        content = n.props.get("content", "")
        assert "<pre" not in content, (
            "plain-text body must not be wrapped in <pre> -- Tailwind Typography's "
            "prose classes force their own color/background on <pre> (code-block "
            "styling), which defeats the theme-reactive .text-body color"
        )


@pytest.mark.asyncio
async def test_html_body_keeps_light_theme_for_own_design(monkeypatch):
    """HTML mail (WHMCS invoices etc.) ships its own design/colours -- it
    should still force theme="light" so it renders as a white "paper"
    background, same as any real mail client renders sender HTML.
    """
    acc = {"email": "<EMAIL>", "provider": "oauth"}
    provider = FakeProvider(_base_email_result(
        body="<table><tr><td>Invoice</td></tr></table>", body_type="html",
    ))
    monkeypatch.setattr(pv, "_get_acc", AsyncMock(return_value=(acc, provider)))

    node = await pv.build_email_viewer(object(), "msg1", account="<EMAIL>")

    html_nodes = _find_html_nodes(node)
    assert html_nodes, "expected at least one Html node in the tree"
    assert any(n.props.get("theme") == "light" for n in html_nodes)


@pytest.mark.asyncio
async def test_html_body_gets_explicit_white_backdrop_for_whmcs_style_mail(monkeypatch):
    """The REAL WHMCS bug: sandbox=False's non-iframe path renders through
    `<div class="prose prose-sm max-w-none">` with NO background of its own
    (only the iframe/sandbox=True variant has bg-white) -- theme="light"
    alone only picks the text-color side of the prose classes. A WHMCS order
    notification (and most corporate HTML mail) sets its OWN dark inline text
    color while relying on landing on a plain white inbox background; it
    never paints a background because no honest mail client needs it to.
    Without an explicit backdrop, that dark-on-assumed-white text sits
    directly on our dark app background = unreadable in dark mode. The fix
    wraps the body in an explicit white/dark-text backdrop div.
    """
    acc = {"email": "<EMAIL>", "provider": "oauth"}
    whmcs_body = (
        '<div style="color:#333333">'
        '<h2>Order Information</h2>'
        '<p>Order ID: 92650</p>'
        '</div>'
    )
    provider = FakeProvider(_base_email_result(body=whmcs_body, body_type="html"))
    monkeypatch.setattr(pv, "_get_acc", AsyncMock(return_value=(acc, provider)))

    node = await pv.build_email_viewer(object(), "msg1", account="<EMAIL>")

    html_nodes = _find_html_nodes(node)
    assert html_nodes, "expected at least one Html node in the tree"
    rendered_content = html_nodes[0].props.get("content", "")
    assert "background:#ffffff" in rendered_content, (
        "HTML email body must be wrapped in an explicit white backdrop -- "
        "otherwise mail that sets its own dark text but no background "
        "(WHMCS invoices/order notices are the classic case) is unreadable "
        "dark-on-dark in the app's dark theme."
    )


# ── Attachments: real 'Read text' action wired to read_attachment() ─────────

@pytest.mark.asyncio
async def test_attachment_with_id_gets_read_text_button(monkeypatch):
    acc = {"email": "<EMAIL>", "provider": "oauth"}
    provider = FakeProvider(_base_email_result(
        attachments=[{"id": "att1", "filename": "Invoice-6285.pdf", "size_kb": 42}],
    ))
    monkeypatch.setattr(pv, "_get_acc", AsyncMock(return_value=(acc, provider)))

    node = await pv.build_email_viewer(object(), "msg1", account="<EMAIL>")

    rendered = str(node)
    assert "Invoice-6285.pdf" in rendered
    assert "Read text" in rendered
    assert "att1" in rendered
    assert "msg1" in rendered


@pytest.mark.asyncio
async def test_attachment_without_id_gets_no_dead_button(monkeypatch):
    acc = {"email": "<EMAIL>", "provider": "oauth"}
    provider = FakeProvider(
        _base_email_result(attachments=[{"filename": "mystery.bin", "size_kb": 10}]),
    )
    monkeypatch.setattr(pv, "_get_acc", AsyncMock(return_value=(acc, provider)))

    node = await pv.build_email_viewer(object(), "msg1", account="<EMAIL>")

    rendered = str(node)
    assert "mystery.bin" in rendered
    assert "Read text" not in rendered
