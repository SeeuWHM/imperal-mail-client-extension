"""Federal-grade tests for read_attachment: engine client + provider download +
orchestration. All network I/O is mocked (ctx.http) — no live credentials
needed, matches the pattern already used across the SeeU-Extensions repo
(bing-webmaster-connector/tests, gsc-connector/tests).
"""
from __future__ import annotations

import base64
import time
from email.message import EmailMessage as PyEmailMessage
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest


# ── Fake ctx.http ────────────────────────────────────────────────────────────

class FakeResponse:
    def __init__(self, status_code: int, json_data: dict | None = None):
        self.status_code = status_code
        self._json = json_data or {}

    def json(self):
        return self._json

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakeHTTP:
    """Queue of canned responses per verb, consumed in order."""

    def __init__(self):
        self.get = AsyncMock()
        self.post = AsyncMock()


def make_ctx(imperal_id: str = "imp_u_test123"):
    ctx = SimpleNamespace()
    ctx.http = FakeHTTP()
    ctx.user = SimpleNamespace(imperal_id=imperal_id)
    return ctx


# ── providers/attachments.py (engine client) ─────────────────────────────────

import providers.attachments as eng


@pytest.mark.asyncio
async def test_imperal_id_missing_hard_fails():
    ctx = SimpleNamespace(http=FakeHTTP(), user=None)
    with pytest.raises(RuntimeError, match="no user context"):
        eng._imperal_id(ctx)


@pytest.mark.asyncio
async def test_ingest_attachment_success():
    ctx = make_ctx()
    ctx.http.post.return_value = FakeResponse(200, {
        "data": {"documents": [{"document_id": 42, "status": "processed", "size_bytes": 100}]}
    })
    doc = await eng.ingest_attachment(ctx, filename="invoice.pdf", content=b"%PDF fake", mime_type="application/pdf")
    assert doc["document_id"] == 42
    assert doc["status"] == "processed"
    _, kwargs = ctx.http.post.call_args
    assert kwargs["data"]["source"] == "mail_attachment"
    assert kwargs["data"]["imperal_id"] == "imp_u_test123"


@pytest.mark.asyncio
async def test_ingest_attachment_empty_content_rejected():
    ctx = make_ctx()
    with pytest.raises(RuntimeError, match="no content"):
        await eng.ingest_attachment(ctx, filename="x", content=b"", mime_type="text/plain")
    ctx.http.post.assert_not_called()


@pytest.mark.asyncio
async def test_ingest_attachment_no_documents_in_response():
    ctx = make_ctx()
    ctx.http.post.return_value = FakeResponse(200, {"data": {"documents": []}})
    with pytest.raises(RuntimeError, match="no result"):
        await eng.ingest_attachment(ctx, filename="x", content=b"bytes", mime_type="text/plain")


@pytest.mark.asyncio
async def test_read_text_success():
    ctx = make_ctx()
    ctx.http.get.return_value = FakeResponse(200, {
        "data": {"text": "Hello world", "truncated": False, "status": "processed"}
    })
    data = await eng.read_text(ctx, 42)
    assert data["text"] == "Hello world"
    _, kwargs = ctx.http.get.call_args
    assert kwargs["params"]["source"] == "mail_attachment"
    assert kwargs["params"]["imperal_id"] == "imp_u_test123"


@pytest.mark.asyncio
async def test_overview_success():
    ctx = make_ctx()
    ctx.http.get.return_value = FakeResponse(200, {"data": {"status": "processing"}})
    data = await eng.overview(ctx, 42)
    assert data["status"] == "processing"


@pytest.mark.asyncio
async def test_send_retries_on_5xx_then_succeeds():
    ctx = make_ctx()
    ctx.http.get.side_effect = [FakeResponse(500, {}), FakeResponse(200, {"data": {"ok": True}})]
    resp = await eng._send(ctx, "get", "https://example/x")
    assert resp.status_code == 200
    assert ctx.http.get.call_count == 2


@pytest.mark.asyncio
async def test_send_raises_after_repeated_5xx():
    ctx = make_ctx()
    ctx.http.get.side_effect = [FakeResponse(500, {}), FakeResponse(502, {})]
    with pytest.raises(RuntimeError, match="engine returned"):
        await eng._send(ctx, "get", "https://example/x")


@pytest.mark.asyncio
async def test_send_retries_on_network_exception():
    ctx = make_ctx()
    ctx.http.get.side_effect = [ConnectionError("boom"), FakeResponse(200, {"data": {}})]
    resp = await eng._send(ctx, "get", "https://example/x")
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_ingest_and_wait_immediate_cached_hit():
    ctx = make_ctx()
    ctx.http.post.return_value = FakeResponse(200, {
        "data": {"documents": [{"document_id": 7, "status": "cached"}]}
    })
    doc = await eng.ingest_and_wait(ctx, filename="a.pdf", content=b"bytes", mime_type="application/pdf")
    assert doc["status"] == "cached"
    ctx.http.get.assert_not_called()  # no polling needed for a cached hit


@pytest.mark.asyncio
async def test_ingest_and_wait_polls_until_processed():
    ctx = make_ctx()
    ctx.http.post.return_value = FakeResponse(200, {
        "data": {"documents": [{"document_id": 7, "status": "pending"}]}
    })
    ctx.http.get.side_effect = [
        FakeResponse(200, {"data": {"status": "processing"}}),
        FakeResponse(200, {"data": {"status": "processed", "document_id": 7}}),
    ]
    doc = await eng.ingest_and_wait(ctx, filename="a.pdf", content=b"bytes",
                                    mime_type="application/pdf", max_wait_s=5.0)
    assert doc["status"] == "processed"
    assert ctx.http.get.call_count == 2


@pytest.mark.asyncio
async def test_ingest_and_wait_gives_up_after_deadline():
    ctx = make_ctx()
    ctx.http.post.return_value = FakeResponse(200, {
        "data": {"documents": [{"document_id": 7, "status": "pending"}]}
    })
    ctx.http.get.return_value = FakeResponse(200, {"data": {"status": "processing"}})
    doc = await eng.ingest_and_wait(ctx, filename="a.pdf", content=b"bytes",
                                    mime_type="application/pdf", max_wait_s=1.2)
    assert doc["status"] == "processing"  # honestly reports "still going", doesn't fabricate done


@pytest.mark.asyncio
async def test_ingest_and_wait_no_document_id_returns_early():
    ctx = make_ctx()
    ctx.http.post.return_value = FakeResponse(200, {
        "data": {"documents": [{"status": "failed", "error": "too_large"}]}
    })
    doc = await eng.ingest_and_wait(ctx, filename="a.pdf", content=b"bytes", mime_type="application/pdf")
    assert doc["status"] == "failed"
    ctx.http.get.assert_not_called()


# ── Gmail download_attachment ─────────────────────────────────────────────────

from providers.google import GoogleMailProvider


def _far_future_acc():
    return {"email": "u@gmail.com", "access_token": "tok", "expires_at": time.time() + 99999}


def _gmail_provider():
    # Real concrete provider class (not the bare read mixin) — needs
    # BaseMailProvider's self.ok()/self.err() helpers to actually run.
    return GoogleMailProvider()


@pytest.mark.asyncio
async def test_gmail_download_attachment_success():
    provider = _gmail_provider()
    ctx = make_ctx()
    raw = b"hello pdf bytes"
    b64url = base64.urlsafe_b64encode(raw).decode().rstrip("=")
    ctx.http.get.return_value = FakeResponse(200, {"size": len(raw), "data": b64url})
    result = await provider.download_attachment(ctx, _far_future_acc(), "msg1", "att1")
    assert result["RESULT"] == "SUCCESS"
    assert result["content"] == raw


@pytest.mark.asyncio
async def test_gmail_download_attachment_not_found():
    provider = _gmail_provider()
    ctx = make_ctx()
    ctx.http.get.return_value = FakeResponse(404, {})
    result = await provider.download_attachment(ctx, _far_future_acc(), "msg1", "att1")
    assert result["RESULT"] == "ERROR"
    assert "not found" in result["error"].lower()


@pytest.mark.asyncio
async def test_gmail_download_attachment_empty_data():
    provider = _gmail_provider()
    ctx = make_ctx()
    ctx.http.get.return_value = FakeResponse(200, {"size": 0, "data": ""})
    result = await provider.download_attachment(ctx, _far_future_acc(), "msg1", "att1")
    assert result["RESULT"] == "ERROR"
    assert "no content" in result["error"].lower()


# ── Microsoft Graph download_attachment ───────────────────────────────────────

import providers.microsoft as ms


def _graph_provider():
    for name in dir(ms):
        obj = getattr(ms, name)
        if isinstance(obj, type) and hasattr(obj, "download_attachment") and "Microsoft" in name:
            return obj()
    raise RuntimeError("no Microsoft provider class with download_attachment found")


@pytest.mark.asyncio
async def test_graph_download_attachment_success():
    provider = _graph_provider()
    ctx = make_ctx()
    raw = b"hello docx bytes"
    b64 = base64.b64encode(raw).decode()
    ctx.http.get.return_value = FakeResponse(200, {
        "@odata.type": "#microsoft.graph.fileAttachment",
        "contentBytes": b64, "name": "report.docx",
        "contentType": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    })
    result = await provider.download_attachment(ctx, _far_future_acc(), "msg1", "att1")
    assert result["RESULT"] == "SUCCESS"
    assert result["content"] == raw


@pytest.mark.asyncio
async def test_graph_download_attachment_not_found():
    provider = _graph_provider()
    ctx = make_ctx()
    ctx.http.get.return_value = FakeResponse(404, {})
    result = await provider.download_attachment(ctx, _far_future_acc(), "msg1", "att1")
    assert result["RESULT"] == "ERROR"


@pytest.mark.asyncio
async def test_graph_download_attachment_rejects_non_file_attachment():
    provider = _graph_provider()
    ctx = make_ctx()
    ctx.http.get.return_value = FakeResponse(200, {"@odata.type": "#microsoft.graph.itemAttachment"})
    result = await provider.download_attachment(ctx, _far_future_acc(), "msg1", "att1")
    assert result["RESULT"] == "ERROR"
    assert "file attachment" in result["error"].lower()


# ── IMAP attachment walk + download (pure parsing, no socket) ───────────────

from providers.imap_read_message import (
    _walk_imap_attachments, _parse_imap_body, _sync_imap_download_attachment,
)


def _sample_msg_with_attachments() -> PyEmailMessage:
    msg = PyEmailMessage()
    msg["Subject"] = "Invoice"
    msg["From"] = "a@b.com"
    msg["To"] = "c@d.com"
    msg.set_content("See attached.")
    msg.add_attachment(b"%PDF-1.4 fake", maintype="application", subtype="pdf", filename="invoice.pdf")
    msg.add_attachment(b"col1,col2\n1,2\n", maintype="text", subtype="csv", filename="data.csv")
    return msg


def test_walk_imap_attachments_lists_real_files_with_stable_ids():
    msg = _sample_msg_with_attachments()
    atts = _walk_imap_attachments(msg)
    assert [a["filename"] for a in atts] == ["invoice.pdf", "data.csv"]
    assert all(a["id"].isdigit() for a in atts)
    parts = list(msg.walk())
    for a in atts:
        assert parts[int(a["id"])].get_filename() == a["filename"]


def test_walk_imap_attachments_empty_for_non_multipart():
    msg = PyEmailMessage()
    msg.set_content("plain body, no attachments")
    assert _walk_imap_attachments(msg) == []


def test_parse_imap_body_prefers_html_but_falls_back_to_text():
    msg = _sample_msg_with_attachments()
    body, body_type = _parse_imap_body(msg)
    assert body_type == "text"
    assert "See attached" in body


def test_sync_imap_download_attachment_invalid_index_type(monkeypatch):
    monkeypatch.setattr(
        "providers.imap_read_message._imap_connect_auth",
        lambda *a, **kw: SimpleNamespace(logout=lambda: None),
    )
    result = _sync_imap_download_attachment("u@x.com", "imap.x.com", 993, "5", "not-an-int")
    assert result["RESULT"] == "ERROR"
    assert "invalid" in result["error"].lower()


# ── impl_read_attachment orchestration ────────────────────────────────────────

import handlers_inbox_impl as impl
from schemas import AttachmentContent


class _StubProvider:
    def __init__(self, read_email_result, download_result):
        self._read_email_result = read_email_result
        self._download_result = download_result

    async def read_email(self, ctx, acc, message_id):
        return self._read_email_result

    async def download_attachment(self, ctx, acc, message_id, attachment_id):
        return self._download_result


@pytest.mark.asyncio
async def test_impl_read_attachment_unknown_id_raises(monkeypatch):
    provider = _StubProvider(
        read_email_result={"RESULT": "SUCCESS", "attachments": [{"id": "0", "filename": "a.pdf"}]},
        download_result={"RESULT": "SUCCESS", "content": b"x"},
    )
    monkeypatch.setattr(impl, "_get_acc", AsyncMock(return_value=({"email": "u@x.com"}, provider)))
    with pytest.raises(RuntimeError, match="was not found"):
        await impl.impl_read_attachment(SimpleNamespace(), message_id="m1",
                                        attachment_id="99", account="u@x.com")


@pytest.mark.asyncio
async def test_impl_read_attachment_happy_path(monkeypatch):
    provider = _StubProvider(
        read_email_result={"RESULT": "SUCCESS", "attachments": [
            {"id": "0", "filename": "invoice.pdf", "mime_type": "application/pdf"}
        ]},
        download_result={"RESULT": "SUCCESS", "content": b"%PDF bytes"},
    )
    monkeypatch.setattr(impl, "_get_acc", AsyncMock(return_value=({"email": "u@x.com"}, provider)))

    import providers.attachments as attachment_engine_mod

    async def fake_ingest_and_wait(ctx, *, filename, content, mime_type):
        return {"document_id": 1, "status": "processed", "size_bytes": len(content)}

    async def fake_read_text(ctx, document_id):
        return {"text": "Invoice #123", "truncated": False, "extraction_method": "native_pdf"}

    monkeypatch.setattr(attachment_engine_mod, "ingest_and_wait", fake_ingest_and_wait)
    monkeypatch.setattr(attachment_engine_mod, "read_text", fake_read_text)

    result = await impl.impl_read_attachment(SimpleNamespace(), message_id="m1",
                                             attachment_id="0", account="u@x.com")
    assert isinstance(result, AttachmentContent)
    assert result.filename == "invoice.pdf"
    assert result.text == "Invoice #123"
    assert result.status == "ready"


@pytest.mark.asyncio
async def test_impl_read_attachment_provider_read_email_error(monkeypatch):
    provider = _StubProvider(
        read_email_result={"RESULT": "ERROR", "error": "Message not found."},
        download_result={"RESULT": "SUCCESS", "content": b"x"},
    )
    monkeypatch.setattr(impl, "_get_acc", AsyncMock(return_value=({"email": "u@x.com"}, provider)))
    with pytest.raises(RuntimeError, match="Message not found"):
        await impl.impl_read_attachment(SimpleNamespace(), message_id="m1",
                                        attachment_id="0", account="u@x.com")


@pytest.mark.asyncio
async def test_impl_read_attachment_download_error(monkeypatch):
    provider = _StubProvider(
        read_email_result={"RESULT": "SUCCESS", "attachments": [{"id": "0", "filename": "a.pdf"}]},
        download_result={"RESULT": "ERROR", "error": "IMAP error: timeout"},
    )
    monkeypatch.setattr(impl, "_get_acc", AsyncMock(return_value=({"email": "u@x.com"}, provider)))
    with pytest.raises(RuntimeError, match="timeout"):
        await impl.impl_read_attachment(SimpleNamespace(), message_id="m1",
                                        attachment_id="0", account="u@x.com")
