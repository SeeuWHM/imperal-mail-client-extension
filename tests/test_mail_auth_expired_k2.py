"""K2.6 tests: expired mailbox OAuth / IMAP / SMTP auth emits AUTH_EXPIRED."""
from __future__ import annotations

import imaplib
import smtplib
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import handlers_inbox
import handlers_manage
import skeleton as sk
from mail_providers import imap_connection, token_refresh
from mail_providers.errors import (
    AUTH_EXPIRED_CODE,
    MailAuthExpiredError,
    mail_error_result,
    raise_if_auth_expired,
)
from mail_providers.google_write import GoogleWriteMixin
from mail_providers.microsoft import MicrosoftMailProvider


class _FakeResp:
    def __init__(self, status_code: int, data: dict | None = None, text: str = ""):
        self.status_code = status_code
        self._data = data or {}
        self.text = text

    def json(self):
        return self._data


def _ctx_with_http(get=None, post=None, patch=None, delete=None):
    return SimpleNamespace(
        user=SimpleNamespace(imperal_id="imp_u_test"),
        http=SimpleNamespace(
            get=AsyncMock(return_value=get) if get is not None else AsyncMock(),
            post=AsyncMock(return_value=post) if post is not None else AsyncMock(),
            patch=AsyncMock(return_value=patch) if patch is not None else AsyncMock(),
            delete=AsyncMock(return_value=delete) if delete is not None else AsyncMock(),
        ),
        store=SimpleNamespace(
            find=AsyncMock(return_value=[]),
            update=AsyncMock(),
        ),
        notify=AsyncMock(),
        secrets=SimpleNamespace(get=AsyncMock(return_value="test-oauth-cred")),
    )


def test_mail_error_result_maps_auth_expired_and_smtp_auth():
    err = MailAuthExpiredError(
        "Google mailbox token expired for u@example.com (HTTP 401) — reconnect mailbox.",
        email="u@example.com",
        provider="google",
        status_code=401,
    )
    res = mail_error_result(err)
    d = res.to_dict()
    assert d["status"] == "error"
    assert d["error_code"] == AUTH_EXPIRED_CODE
    assert "u@example.com" in d["error"]

    smtp_err = smtplib.SMTPAuthenticationError(535, b"5.7.8 Username and Password not accepted")
    smtp_res = mail_error_result(smtp_err).to_dict()
    assert smtp_res["status"] == "error"
    assert smtp_res["error_code"] == AUTH_EXPIRED_CODE

    generic = mail_error_result(RuntimeError("network blip")).to_dict()
    assert generic["status"] == "error"
    assert not generic.get("error_code")


def test_raise_if_auth_expired_on_401_only():
    ok_resp = _FakeResp(200)
    assert raise_if_auth_expired(ok_resp, acc={"email": "a@b.com"}, provider="google") is ok_resp

    err_500 = _FakeResp(500)
    assert raise_if_auth_expired(err_500, acc={"email": "a@b.com"}, provider="google") is err_500

    with pytest.raises(MailAuthExpiredError) as exc_info:
        raise_if_auth_expired(_FakeResp(401), acc={"email": "a@b.com"}, provider="google")
    assert exc_info.value.status_code == 401
    assert exc_info.value.email == "a@b.com"
    assert "a@b.com" in str(exc_info.value)


@pytest.mark.asyncio
async def test_google_token_refresh_400_401_raises_auth_expired():
    acc = {
        "doc_id": "d1",
        "email": "alice@gmail.com",
        "provider": "google",
        "access_token": "old",
        "refresh_token": "revoked-rt",
        "token_expiry": 0,
    }
    ctx = _ctx_with_http(post=_FakeResp(400, {"error": "invalid_grant"}, text="invalid_grant"))
    with pytest.raises(MailAuthExpiredError) as exc_info:
        await token_refresh._refresh_google_token(ctx, acc)
    assert exc_info.value.provider == "google"
    assert exc_info.value.email == "alice@gmail.com"
    assert "reconnect" in str(exc_info.value).lower()


@pytest.mark.asyncio
async def test_microsoft_token_refresh_401_raises_auth_expired():
    acc = {
        "doc_id": "d2",
        "email": "bob@outlook.com",
        "provider": "microsoft",
        "access_token": "old",
        "refresh_token": "revoked-rt",
        "token_expiry": 0,
    }
    ctx = _ctx_with_http(post=_FakeResp(401, {"error": "invalid_grant"}, text="invalid_grant"))
    with pytest.raises(MailAuthExpiredError) as exc_info:
        await token_refresh._refresh_microsoft_token(ctx, acc)
    assert exc_info.value.provider == "microsoft"
    assert exc_info.value.email == "bob@outlook.com"


@pytest.mark.asyncio
async def test_gmail_api_get_401_raises_auth_expired():
    ctx = _ctx_with_http(get=_FakeResp(401, text="Unauthorized"))
    acc = {"email": "alice@gmail.com", "access_token": "expired-tok", "expires_at": 9999999999}
    with pytest.raises(MailAuthExpiredError) as exc_info:
        await token_refresh._api_get(ctx, "/messages", acc)
    assert exc_info.value.status_code == 401
    assert exc_info.value.provider == "google"
    assert exc_info.value.email == "alice@gmail.com"


@pytest.mark.asyncio
async def test_graph_get_401_raises_auth_expired():
    ctx = _ctx_with_http(get=_FakeResp(401, text="InvalidAuthenticationToken"))
    acc = {"email": "bob@outlook.com", "access_token": "expired-tok", "expires_at": 9999999999}
    with pytest.raises(MailAuthExpiredError) as exc_info:
        await token_refresh._graph_get(ctx, "/me/messages", acc)
    assert exc_info.value.status_code == 401
    assert exc_info.value.provider == "microsoft"
    assert exc_info.value.email == "bob@outlook.com"


def test_imap_login_error_raises_mail_auth_expired(monkeypatch):
    class _FakeIMAP:
        def __init__(self, host, port, ssl_context=None, timeout=None):
            pass

        def login(self, email_addr, password):
            raise imaplib.IMAP4.error("AUTHENTICATIONFAILED")

        def logout(self):
            pass

    monkeypatch.setattr(imaplib, "IMAP4_SSL", _FakeIMAP)
    with pytest.raises(MailAuthExpiredError) as exc_info:
        imap_connection._imap_connect_auth(
            "imap@example.com", "imap.example.com", 993, password="badpass"
        )
    assert exc_info.value.provider == "imap"
    assert exc_info.value.email == "imap@example.com"


@pytest.mark.asyncio
async def test_direct_http_401_in_gmail_write_and_microsoft_raises():
    class _GW(GoogleWriteMixin):
        def ok(self, **kw):
            return {"RESULT": "SUCCESS", **kw}

        def err(self, msg):
            return {"RESULT": "ERROR", "error": msg}

    ctx = _ctx_with_http(delete=_FakeResp(401, text="Unauthorized"))
    acc = {"email": "g@gmail.com", "access_token": "tok", "expires_at": 9999999999}
    with pytest.raises(MailAuthExpiredError):
        await _GW().purge(ctx, acc, "m1")

    ms_ctx = _ctx_with_http(get=_FakeResp(401, text="Unauthorized"))
    ms_acc = {"email": "m@outlook.com", "access_token": "tok", "expires_at": 9999999999}
    with pytest.raises(MailAuthExpiredError):
        await MicrosoftMailProvider().get_today_count(ms_ctx, ms_acc)


@pytest.mark.asyncio
async def test_handlers_inbox_and_manage_emit_auth_expired_code(monkeypatch):
    async def _boom(*args, **kwargs):
        raise MailAuthExpiredError(
            "Google mailbox token expired for alice@gmail.com (HTTP 401) — reconnect mailbox.",
            email="alice@gmail.com",
            provider="google",
            status_code=401,
        )

    monkeypatch.setattr(handlers_inbox, "impl_inbox", _boom)
    res_inbox = await handlers_inbox.fn_inbox(_ctx_with_http(), handlers_inbox.InboxParams())
    d_inbox = res_inbox.to_dict()
    assert d_inbox["status"] == "error"
    assert d_inbox["error_code"] == AUTH_EXPIRED_CODE
    assert "alice@gmail.com" in d_inbox["error"]

    monkeypatch.setattr(handlers_manage, "impl_archive", _boom)
    res_arch = await handlers_manage.fn_archive(
        _ctx_with_http(),
        handlers_manage.ArchiveParams(message_ids="msg-1"),
    )
    d_arch = res_arch.to_dict()
    assert d_arch["status"] == "error"
    assert d_arch["error_code"] == AUTH_EXPIRED_CODE


@pytest.mark.asyncio
async def test_skeleton_refresh_emits_needs_human_on_auth_expired_while_preserving_fallback(monkeypatch):
    acc = {
        "doc_id": "d1",
        "email": "alice@gmail.com",
        "provider": "google",
        "unread_count": 7,
        "is_active": True,
    }
    monkeypatch.setattr(sk, "_all_accounts", AsyncMock(return_value=[acc]))

    async def _expired(ctx, a):
        raise MailAuthExpiredError(
            "Google mailbox token expired for alice@gmail.com (HTTP 401) — reconnect mailbox.",
            email="alice@gmail.com",
            provider="google",
            status_code=401,
        )

    monkeypatch.setattr(sk, "_refresh_token_if_needed", _expired)
    ctx = _ctx_with_http()
    result = await sk.skeleton_refresh_mail_inbox_summary(ctx)

    assert result["response"]["unread_total"] == 7
    assert result["response"]["active_account"] == "alice@gmail.com"
    assert result["error_code"] == AUTH_EXPIRED_CODE
    assert result["needs_human"]["kind"] == "means"
    assert "alice@gmail.com" in result["needs_human"]["what"]
    ctx.notify.assert_not_awaited()
