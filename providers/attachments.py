"""Mail Client · attachment content reading — doc-extractor engine client.

Reads the actual TEXT of an email attachment the user received (not just its
filename/size, which read_email already reports). Mirrors file-reader's own
engine client (providers/extractor.py there) exactly — same engine
(whm-doc-extractor-api, reached over the same nginx-proxied public path),
same ctx.http platform client, same 3 operations used here (ingest,
read_text, overview) — but with its OWN partition key
(source="mail_attachment") so a downloaded attachment's stored text never
mixes with file-reader's own uploaded-document rows for the same user.

Raw attachment bytes are held ONLY in memory for the span of one provider
download + one engine ingest call; nothing is persisted here. The engine is
the only place the extracted text lives after that, exactly like file-reader.

Not wired to ctx.files (the new kernel-injected primitive from the File Mage
design, imperal-sdk 5.9.11+): its exact method contract could not be
independently confirmed in this session (design doc says
`ctx.files.extract(bytes, filename)`, a later delegation ticket says
`ctx.files.ingest(content, filename, mime_type=...)` — a real discrepancy,
not a formatting nuance) against a live kernel checkout, and this ships to
every Mail Client user. Using the proven, already-live HTTP contract instead
(confirmed directly against whm-doc-extractor-api's own source over SSH)
is the honest choice until that primitive can be verified the same way.
"""
from __future__ import annotations

import logging

log = logging.getLogger("mail_attachments")

# Same public route file-reader's engine client uses (nginx-proxied, api-server).
_DOCUMENTS_URL = "https://api.webhostmost.com/doc-extractor/v1/documents"
SOURCE = "mail_attachment"

# Bounded, honest read window — matches file-reader's own default window size
# so an attachment doesn't blow the chat response budget.
DEFAULT_READ_LIMIT = 40_000


def _imperal_id(ctx) -> str:
    """Canonical user id scoping ALL engine storage. Missing -> hard error: we
    must never ingest/read under an unscoped or wrong identity."""
    user = getattr(ctx, "user", None)
    uid = getattr(user, "imperal_id", None) if user else None
    if not uid:
        raise RuntimeError("no user context (imperal_id) — cannot scope attachment storage")
    return uid


async def _send(ctx, method: str, url: str, **kwargs):
    """One retry on transient 5xx / network error — same shape as
    file-reader's extractor._send. Real 4xx are returned as-is."""
    call = getattr(ctx.http, method)
    last: Exception | None = None
    for _ in range(2):
        try:
            resp = await call(url, **kwargs)
        except Exception as e:  # noqa: BLE001 - network/timeout -> retry once
            last = e
            continue
        if resp.status_code >= 500:
            last = RuntimeError(f"engine returned {resp.status_code}")
            continue
        return resp
    raise last if last else RuntimeError("engine request failed")


async def ingest_attachment(ctx, *, filename: str, content: bytes,
                            mime_type: str | None = None) -> dict:
    """Hand the engine the raw attachment bytes. Idempotent by
    (source, imperal_id, sha256) on the engine side: re-reading the same
    attachment (e.g. re-opening the same email) is a fast `cached` hit, no
    re-extract. Returns the DocumentOut dict. The caller must not retain
    `content` after this call returns — this is the ONLY place the raw
    attachment bytes exist in this extension."""
    if not content:
        raise RuntimeError("Attachment has no content to read.")
    files = {"files": (filename or "attachment", content, mime_type or "application/octet-stream")}
    resp = await _send(ctx, "post", _DOCUMENTS_URL, data={
        "source": SOURCE, "imperal_id": _imperal_id(ctx),
    }, files=files, timeout=120)
    resp.raise_for_status()
    docs = ((resp.json() or {}).get("data") or {}).get("documents") or []
    if not docs:
        raise RuntimeError("Attachment reader returned no result.")
    return docs[0]


async def read_text(ctx, document_id: int, offset: int = 0, limit: int = DEFAULT_READ_LIMIT) -> dict:
    """Windowed plain text from the engine's stored blob for this attachment.
    Returns {text, offset, limit, total_chars, truncated, status, ...} —
    callers check `status` (pending|processing|processed|failed|unsupported)
    before trusting `text`."""
    resp = await _send(ctx, "get", f"{_DOCUMENTS_URL}/{document_id}/text", params={
        "source": SOURCE, "imperal_id": _imperal_id(ctx), "offset": offset, "limit": limit,
    }, timeout=60)
    resp.raise_for_status()
    return (resp.json() or {}).get("data") or {}


async def overview(ctx, document_id: int) -> dict:
    """Cheap metadata + preview + processing status, no full text read."""
    resp = await _send(ctx, "get", f"{_DOCUMENTS_URL}/{document_id}", params={
        "source": SOURCE, "imperal_id": _imperal_id(ctx),
    }, timeout=30)
    resp.raise_for_status()
    return (resp.json() or {}).get("data") or {}


async def ingest_and_wait(ctx, *, filename: str, content: bytes,
                          mime_type: str | None = None,
                          max_wait_s: float = 8.0) -> dict:
    """ingest_attachment() then poll overview() briefly for the drain loop
    (whm-doc-extractor-api's async processor, ~1s cadence) to finish, so a
    first-time read_attachment() call doesn't come back empty for an
    attachment that is still being extracted. Gives up after max_wait_s and
    returns whatever status the engine has reached — the caller reports it
    honestly (e.g. "still processing, try again in a moment") rather than
    stalling the chat turn indefinitely."""
    import asyncio
    import time

    doc = await ingest_attachment(ctx, filename=filename, content=content, mime_type=mime_type)
    status = doc.get("status", "")
    if status in ("processed", "cached", "failed", "unsupported"):
        return doc
    document_id = doc.get("document_id")
    if not document_id:
        return doc
    deadline = time.monotonic() + max_wait_s
    while time.monotonic() < deadline:
        await asyncio.sleep(1.0)
        doc = await overview(ctx, document_id)
        if doc.get("status") in ("processed", "cached", "failed", "unsupported"):
            return doc
    return doc
