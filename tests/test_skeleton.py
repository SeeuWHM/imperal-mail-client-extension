"""Federal-grade tests for the mail_inbox_summary skeleton — the 2026-07-19
duplicate-notification fix (monotonic seen-id watermark, no-notify-on-failed-
write, date-gate belt-and-suspenders). See skeleton.py's module docstring for
the full root-cause writeup this covers.
"""
from __future__ import annotations

import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import skeleton as sk


# ── pure helpers: seen-id load / merge / migration ──────────────────────────

def test_load_seen_ids_migrates_legacy_bare_list():
    acc = {"last_message_ids": ["a", "b", "c"], "last_fetched": 1000}
    seen = sk._load_seen_ids(acc)
    assert seen == {"a": 1000, "b": 1000, "c": 1000}


def test_load_seen_ids_migrates_legacy_with_no_last_fetched():
    acc = {"last_message_ids": ["a"]}
    seen = sk._load_seen_ids(acc)
    assert "a" in seen
    assert isinstance(seen["a"], int)


def test_load_seen_ids_reads_new_shape():
    acc = {"seen_message_ids": [{"id": "x", "last_seen": 500}, {"id": "y", "last_seen": 600}]}
    assert sk._load_seen_ids(acc) == {"x": 500, "y": 600}


def test_load_seen_ids_empty_when_nothing_stored():
    assert sk._load_seen_ids({}) == {}


def test_merge_seen_ids_is_a_union_not_a_replace():
    """The core of the fix: ids that leave the current page must NOT be forgotten."""
    prev = {"old1": 100, "old2": 200}
    curr = {"new1"}
    merged = sk._merge_seen_ids(prev, curr, now=300)
    assert merged == {"old1": 100, "old2": 200, "new1": 300}
    # old1/old2 are NOT in curr_ids (they fell off the page) but must survive.
    assert "old1" in merged and "old2" in merged


def test_merge_seen_ids_bounds_to_cap_evicting_oldest_first():
    prev = {f"id{i}": i for i in range(sk._SEEN_ID_CAP)}  # oldest ts = 0
    merged = sk._merge_seen_ids(prev, {"new"}, now=sk._SEEN_ID_CAP + 1000)
    assert len(merged) == sk._SEEN_ID_CAP
    assert "id0" not in merged  # the oldest-seen id was evicted
    assert "new" in merged


def test_seen_ids_for_store_roundtrip():
    seen = {"a": 1, "b": 2}
    stored = sk._seen_ids_for_store(seen)
    assert {"id": "a", "last_seen": 1} in stored
    assert {"id": "b", "last_seen": 2} in stored
    assert sk._load_seen_ids({"seen_message_ids": stored}) == seen


def test_parse_msg_date_rfc2822():
    dt = sk._parse_msg_date("Mon, 20 Jul 2026 10:00:00 +0000")
    assert dt is not None and dt.year == 2026


def test_parse_msg_date_none_on_garbage():
    assert sk._parse_msg_date("not a date") is None
    assert sk._parse_msg_date(None) is None
    assert sk._parse_msg_date("") is None


# ── full skeleton refresh — the duplicate-notification regression ──────────

class _FakeStore:
    def __init__(self, fail: bool = False):
        self.fail = fail
        self.updates: list[tuple[str, str, dict]] = []

    async def update(self, collection, doc_id, data):
        if self.fail:
            raise RuntimeError("store unavailable (simulated)")
        self.updates.append((collection, doc_id, data))
        return SimpleNamespace(id=doc_id)


class _FakeCache:
    def __init__(self):
        self.set = AsyncMock()


def _make_ctx(store: _FakeStore | None = None):
    ctx = SimpleNamespace()
    ctx.user = SimpleNamespace(imperal_id="imp_u_test")
    ctx.store = store or _FakeStore()
    ctx.cache = _FakeCache()
    ctx.notify = AsyncMock()
    return ctx


def _msg(mid: str, subject: str = "Hello", date: str = "Mon, 20 Jul 2026 10:00:00 +0000"):
    return {"id": mid, "subject": subject, "date": date, "unread": True}


@pytest.fixture(autouse=True)
def _patch_common(monkeypatch):
    """Stub out the network-facing pieces every test needs, leaving only the
    seen-id / notify / store logic under real test."""
    async def fake_refresh(ctx, acc):
        return acc

    monkeypatch.setattr(sk, "_refresh_token_if_needed", fake_refresh)
    monkeypatch.setattr(sk, "encode_cursor", lambda *a, **kw: "")


def _fake_provider(messages, counts=None):
    provider = SimpleNamespace()

    async def get_counts(ctx, acc):
        return counts or {}

    async def get_today_count(ctx, acc):
        return 0

    async def fetch_page(ctx, acc, folder, size, cursor):
        return messages, None, False

    provider.get_counts = get_counts
    provider.get_today_count = get_today_count
    provider.fetch_page = fetch_page
    return provider


@pytest.mark.asyncio
async def test_first_run_notifies_and_persists_seen_ids(monkeypatch):
    """No prior watermark — the first page's ids are all new, notify fires once,
    and every id gets persisted (not just page-1 subset lost next tick)."""
    acc = {"email": "u@x.com", "doc_id": "doc1", "is_active": True}
    monkeypatch.setattr(sk, "_all_accounts", AsyncMock(return_value=[acc]))
    messages = [_msg("m1"), _msg("m2")]
    monkeypatch.setattr(sk, "get_provider", lambda a: _fake_provider(messages))

    store = _FakeStore()
    ctx = _make_ctx(store)
    await sk.skeleton_refresh_mail_inbox_summary(ctx)

    ctx.notify.assert_awaited_once()
    assert store.updates, "store.update must be called to persist the watermark"
    seen_write = next(u for u in store.updates if "seen_message_ids" in u[2])
    saved_ids = {d["id"] for d in seen_write[2]["seen_message_ids"]}
    assert saved_ids == {"m1", "m2"}


@pytest.mark.asyncio
async def test_message_falling_off_page_window_is_never_re_notified(monkeypatch):
    """THE regression this ticket describes: a message seen before, now absent
    from the fresh page-1 window (jitter/reorder), must stay suppressed —
    i.e. still counted in prev_ids, NOT re-classified as new."""
    acc = {
        "email": "u@x.com", "doc_id": "doc1", "is_active": True,
        "seen_message_ids": [{"id": "m1", "last_seen": 1000}],
    }
    monkeypatch.setattr(sk, "_all_accounts", AsyncMock(return_value=[acc]))
    # m1 no longer appears in page 1 (fell off the window) — only m2 (new) does.
    messages = [_msg("m2")]
    monkeypatch.setattr(sk, "get_provider", lambda a: _fake_provider(messages))

    store = _FakeStore()
    ctx = _make_ctx(store)
    await sk.skeleton_refresh_mail_inbox_summary(ctx)

    ctx.notify.assert_awaited_once()
    call_text = ctx.notify.call_args[0][0]
    assert "m2" not in call_text  # message ids aren't in the text, but subject check below
    # m1 must have SURVIVED the merge (still present after this tick), proving
    # it wasn't silently dropped and available to be "rediscovered" later.
    # (Two store.update calls happen this tick — the seen-ids write, then a
    # second one advancing last_notified_date — so find the one carrying
    # seen_message_ids rather than assuming call order.)
    seen_write = next(u for u in store.updates if "seen_message_ids" in u[2])
    saved_ids = {d["id"] for d in seen_write[2]["seen_message_ids"]}
    assert "m1" in saved_ids
    assert "m2" in saved_ids


@pytest.mark.asyncio
async def test_previously_seen_message_reappearing_in_page_does_not_renotify(monkeypatch):
    """Direct regression test for the ticket: an id already in prev_ids that
    resurfaces in curr_ids (e.g. page reordering) must NOT trigger notify."""
    acc = {
        "email": "u@x.com", "doc_id": "doc1", "is_active": True,
        "seen_message_ids": [{"id": "m1", "last_seen": 1000}],
    }
    monkeypatch.setattr(sk, "_all_accounts", AsyncMock(return_value=[acc]))
    messages = [_msg("m1")]  # same id resurfaces, nothing genuinely new
    monkeypatch.setattr(sk, "get_provider", lambda a: _fake_provider(messages))

    ctx = _make_ctx()
    await sk.skeleton_refresh_mail_inbox_summary(ctx)

    ctx.notify.assert_not_awaited()


@pytest.mark.asyncio
async def test_failed_store_write_skips_notify_this_tick(monkeypatch):
    """Ticket requirement #2: a failed persist must not fire notify on a
    watermark we know didn't make it to storage."""
    acc = {"email": "u@x.com", "doc_id": "doc1", "is_active": True}
    monkeypatch.setattr(sk, "_all_accounts", AsyncMock(return_value=[acc]))
    messages = [_msg("m1")]
    monkeypatch.setattr(sk, "get_provider", lambda a: _fake_provider(messages))

    failing_store = _FakeStore(fail=True)
    ctx = _make_ctx(failing_store)
    await sk.skeleton_refresh_mail_inbox_summary(ctx)

    ctx.notify.assert_not_awaited()


@pytest.mark.asyncio
async def test_date_gate_blocks_notify_for_old_message_even_if_id_looks_new(monkeypatch):
    """Ticket requirement #3 (belt-and-suspenders): a candidate whose own date
    is not after last_notified_date must not fire, even if its id is 'new'."""
    acc = {
        "email": "u@x.com", "doc_id": "doc1", "is_active": True,
        "last_notified_date": "Mon, 20 Jul 2026 12:00:00 +0000",
    }
    monkeypatch.setattr(sk, "_all_accounts", AsyncMock(return_value=[acc]))
    # id never seen before, but its date is BEFORE the watermark.
    messages = [_msg("m_old", date="Mon, 20 Jul 2026 08:00:00 +0000")]
    monkeypatch.setattr(sk, "get_provider", lambda a: _fake_provider(messages))

    ctx = _make_ctx()
    await sk.skeleton_refresh_mail_inbox_summary(ctx)

    ctx.notify.assert_not_awaited()


@pytest.mark.asyncio
async def test_date_gate_allows_notify_for_message_after_watermark(monkeypatch):
    acc = {
        "email": "u@x.com", "doc_id": "doc1", "is_active": True,
        "last_notified_date": "Mon, 20 Jul 2026 08:00:00 +0000",
    }
    monkeypatch.setattr(sk, "_all_accounts", AsyncMock(return_value=[acc]))
    messages = [_msg("m_new", date="Mon, 20 Jul 2026 12:00:00 +0000")]
    monkeypatch.setattr(sk, "get_provider", lambda a: _fake_provider(messages))

    ctx = _make_ctx()
    await sk.skeleton_refresh_mail_inbox_summary(ctx)

    ctx.notify.assert_awaited_once()


@pytest.mark.asyncio
async def test_no_accounts_returns_zeroed_envelope(monkeypatch):
    monkeypatch.setattr(sk, "_all_accounts", AsyncMock(return_value=[]))
    ctx = _make_ctx()
    result = await sk.skeleton_refresh_mail_inbox_summary(ctx)
    assert result["response"]["per_account"] == []
    assert result["response"]["unread_total"] == 0


@pytest.mark.asyncio
async def test_no_user_returns_note(monkeypatch):
    ctx = SimpleNamespace(user=SimpleNamespace(imperal_id=""))
    result = await sk.skeleton_refresh_mail_inbox_summary(ctx)
    assert "note" in result["response"]


@pytest.mark.asyncio
async def test_provider_error_falls_back_to_last_known_unread(monkeypatch):
    acc = {"email": "u@x.com", "doc_id": "doc1", "is_active": True, "unread_count": 7}
    monkeypatch.setattr(sk, "_all_accounts", AsyncMock(return_value=[acc]))

    def boom(acc):
        raise RuntimeError("provider down")

    monkeypatch.setattr(sk, "get_provider", boom)
    ctx = _make_ctx()
    result = await sk.skeleton_refresh_mail_inbox_summary(ctx)
    assert result["response"]["unread_total"] == 7
    ctx.notify.assert_not_awaited()


# ── skeleton_alert_mail_inbox_summary (kernel diff-alert, second layer) ────

@pytest.mark.asyncio
async def test_alert_fires_on_unread_increase():
    result = await sk.skeleton_alert_mail_inbox_summary(
        SimpleNamespace(), old={"unread_total": 2}, new={"unread_total": 5},
    )
    assert result["response"] == "3 new unread emails"


@pytest.mark.asyncio
async def test_alert_silent_when_unread_unchanged_or_decreased():
    result = await sk.skeleton_alert_mail_inbox_summary(
        SimpleNamespace(), old={"unread_total": 5}, new={"unread_total": 5},
    )
    assert result["response"] == ""
    result2 = await sk.skeleton_alert_mail_inbox_summary(
        SimpleNamespace(), old={"unread_total": 5}, new={"unread_total": 3},
    )
    assert result2["response"] == ""


@pytest.mark.asyncio
async def test_alert_handles_missing_new_snapshot():
    result = await sk.skeleton_alert_mail_inbox_summary(SimpleNamespace(), old=None, new=None)
    assert result["response"] == ""
