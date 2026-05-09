"""IMAP read operations — inbox, fetch page, unread count.

Performance: batch FETCH — single UID FETCH command for all UIDs in a page
instead of N sequential round trips. O(1) network latency instead of O(n).
"""
from __future__ import annotations

import email as email_lib
import logging
import re

from .helpers import IMAP_FOLDER_CANDIDATES
from .imap_connection import _imap_connect_auth
from .text_utils import _decode_header

# Re-export message-level operations so imap.py only needs to import from imap_read
from .imap_read_message import (  # noqa: F401
    _sync_imap_read, _sync_imap_search, _sync_imap_folder,
)

log = logging.getLogger(__name__)

_UID_RE   = re.compile(rb'\bUID\s+(\d+)', re.IGNORECASE)
_FLAGS_RE = re.compile(rb'FLAGS\s*\(([^)]*)\)', re.IGNORECASE)


# ── Batch FETCH helpers ───────────────────────────────────────────────────────

def _parse_fetch_response(batch_data, fallback_uids: list[int]) -> list[tuple[int, bytes, bytes]]:
    """Parse imaplib batch UID FETCH response.

    Returns list of (uid_int, raw_header_bytes, flags_bytes).
    Uses fallback_uids order when UID is absent from the FETCH info line.
    """
    results: list[tuple[int, bytes, bytes]] = []
    fb_iter = iter(fallback_uids)
    for item in (batch_data or []):
        if not isinstance(item, tuple) or len(item) < 2:
            continue
        info = item[0] if isinstance(item[0], bytes) else b""
        raw  = item[1]
        if not isinstance(raw, bytes) or not raw:
            continue
        uid_m  = _UID_RE.search(info)
        uid    = int(uid_m.group(1)) if uid_m else next(fb_iter, 0)
        flags_m = _FLAGS_RE.search(info)
        flags   = flags_m.group(1) if flags_m else b""
        results.append((uid, raw, flags))
    return results


def _fetch_headers_batch(imap, page_uids: list[int]) -> list[tuple[int, bytes, bytes]]:
    """Single UID FETCH for all page_uids — one round trip instead of N."""
    uid_str = ",".join(str(u) for u in page_uids)
    _, batch = imap.uid("FETCH", uid_str, "(RFC822.HEADER FLAGS)")
    return _parse_fetch_response(batch, page_uids)


def _msg_dict(uid_int: int, raw: bytes, flags: bytes, starred_override: bool = False) -> dict:
    """Build a normalised message preview dict from a FETCH result."""
    msg = email_lib.message_from_bytes(raw)
    return {
        "message_id":    str(uid_int),
        "thread_id":     str(uid_int),
        "from":          _decode_header(msg.get("From", "unknown")),
        "subject":       _decode_header(msg.get("Subject", "(no subject)")),
        "snippet":       "",
        "date":          msg.get("Date", ""),
        "unread":        b"\\Seen" not in flags,
        "starred":       starred_override or b"\\Flagged" in flags,
        "has_attachments": False,
        "labels":        [],
    }


# ── Public functions ──────────────────────────────────────────────────────────

def _sync_imap_folder_stats(email_addr: str, host: str, port: int, imap_folder: str,
                             *, password: str = "", access_token: str = "") -> dict:
    """Return {'total': int, 'unread': int} via IMAP STATUS command."""
    imap = _imap_connect_auth(email_addr, host, port, password=password, access_token=access_token)
    try:
        candidates = IMAP_FOLDER_CANDIDATES.get(imap_folder.lower(), [imap_folder])
        if imap_folder.upper() == "INBOX":
            candidates = ["INBOX"]
        for candidate in candidates:
            try:
                r, data = imap.status(f'"{candidate}"', "(MESSAGES UNSEEN)")
                if r == "OK" and data and data[0]:
                    m_total  = re.search(rb"MESSAGES\s+(\d+)", data[0])
                    m_unseen = re.search(rb"UNSEEN\s+(\d+)", data[0])
                    return {
                        "total":  int(m_total.group(1))  if m_total  else 0,
                        "unread": int(m_unseen.group(1)) if m_unseen else 0,
                    }
            except Exception:
                continue
    finally:
        try: imap.logout()
        except Exception: pass
    return {"total": 0, "unread": 0}


def _sync_imap_inbox(email_addr: str, host: str, port: int, max_results: int = 20,
                     *, password: str = "", access_token: str = "") -> list[dict]:
    """Fetch recent INBOX messages — batch FETCH, single round trip."""
    imap = _imap_connect_auth(email_addr, host, port, password=password, access_token=access_token)
    imap.select("INBOX")
    _, uid_data = imap.uid("SEARCH", "ALL")
    all_uids    = uid_data[0].split() if uid_data and uid_data[0] else []
    if not all_uids:
        imap.logout()
        return []
    recent_uid_ints = [int(u) for u in all_uids[-max_results:][::-1]]
    parsed = _fetch_headers_batch(imap, recent_uid_ints)
    imap.logout()
    return [
        {
            "id":                str(uid),
            "thread_id":         str(uid),
            "subject":           _decode_header(email_lib.message_from_bytes(raw).get("Subject", "(no subject)")),
            "from":              _decode_header(email_lib.message_from_bytes(raw).get("From", "unknown")),
            "date":              email_lib.message_from_bytes(raw).get("Date", ""),
            "unread":            b"\\Seen" not in flags,
            "message_id_header": email_lib.message_from_bytes(raw).get("Message-ID", ""),
        }
        for uid, raw, flags in parsed
    ]


def _sync_imap_fetch_page(email_addr: str, host: str, port: int,
                          imap_folder: str, limit: int,
                          last_uid: int | None,
                          *, password: str = "",
                          access_token: str = "") -> tuple[list[dict], int | None, bool]:
    imap = _imap_connect_auth(email_addr, host, port,
                               password=password, access_token=access_token)

    # ── Starred folder: INBOX filtered by \Flagged ───────────────────────────
    if imap_folder.lower() == "starred":
        imap.select('"INBOX"', readonly=True)
        _, uid_data = imap.uid("SEARCH", "FLAGGED")
        all_uids    = uid_data[0].split() if uid_data and uid_data[0] else []
        if not all_uids:
            imap.logout()
            return [], None, False
        uid_ints = sorted([int(u) for u in all_uids], reverse=True)
        if last_uid is not None:
            uid_ints = [u for u in uid_ints if u < last_uid]
        page_uids = uid_ints[:limit]
        if not page_uids:
            imap.logout()
            return [], None, False
        parsed   = _fetch_headers_batch(imap, page_uids)
        messages = [_msg_dict(u, r, f, starred_override=True) for u, r, f in parsed]
        imap.logout()
        lowest    = page_uids[-1] if page_uids else None
        remaining = [u for u in uid_ints if u < lowest] if lowest else []
        return messages, (lowest if remaining else None), bool(remaining)

    # ── Regular folder ────────────────────────────────────────────────────────
    candidates = IMAP_FOLDER_CANDIDATES.get(imap_folder.lower(), [imap_folder])
    if imap_folder.upper() == "INBOX":
        candidates = ["INBOX"]
    selected = False
    count    = 0
    for candidate in candidates:
        r, data = imap.select(f'"{candidate}"', readonly=True)
        if r == "OK":
            selected = True
            count = int(data[0]) if data and data[0] else 0
            break
    if not selected or count == 0:
        imap.logout()
        return [], None, False

    if last_uid is None:
        # First page: sequence-range FETCH — O(1), no SEARCH ALL on large folders.
        # UID is requested in the field spec so _parse_fetch_response can extract it.
        start_seq = max(1, count - limit + 1)
        _, batch  = imap.fetch(f"{start_seq}:{count}", "(UID FLAGS RFC822.HEADER)")
        parsed    = _parse_fetch_response(batch, [])
        parsed.sort(key=lambda x: x[0], reverse=True)
        messages  = [_msg_dict(u, r, f) for u, r, f in parsed if u > 0]
        lowest    = parsed[-1][0] if parsed else None
        has_more  = start_seq > 1
        imap.logout()
        return messages, (lowest if has_more and lowest else None), has_more

    # Cursor page: UID range search — bounded, avoids downloading the full UID list.
    _, uid_data = imap.uid("SEARCH", f"UID 1:{last_uid - 1}")
    all_uids    = uid_data[0].split() if uid_data and uid_data[0] else []
    if not all_uids:
        imap.logout()
        return [], None, False

    uid_ints  = sorted([int(u) for u in all_uids], reverse=True)
    page_uids = uid_ints[:limit]
    if not page_uids:
        imap.logout()
        return [], None, False

    parsed    = _fetch_headers_batch(imap, page_uids)
    messages  = [_msg_dict(u, r, f) for u, r, f in parsed]
    imap.logout()
    lowest    = page_uids[-1] if page_uids else None
    remaining = [u for u in uid_ints if u < lowest] if lowest else []
    has_more  = bool(remaining)
    return messages, (lowest if has_more else None), has_more


def _sync_imap_unread_count(email_addr: str, host: str, port: int,
                            imap_folder: str, *,
                            password: str = "",
                            access_token: str = "") -> int:
    imap = _imap_connect_auth(email_addr, host, port, password=password, access_token=access_token)
    count = 0
    try:
        if imap_folder.lower() == "starred":
            imap.select('"INBOX"', readonly=True)
            _, uid_data = imap.uid("SEARCH", "FLAGGED UNSEEN")
            count = len(uid_data[0].split()) if uid_data and uid_data[0] else 0
        else:
            candidates = IMAP_FOLDER_CANDIDATES.get(imap_folder.lower(), [imap_folder])
            if imap_folder.upper() == "INBOX":
                candidates = ["INBOX"]
            for candidate in candidates:
                try:
                    r, data = imap.status(f'"{candidate}"', "(UNSEEN)")
                    if r == "OK" and data and data[0]:
                        match = re.search(rb"UNSEEN\s+(\d+)", data[0])
                        if match:
                            count = int(match.group(1))
                    break
                except Exception:
                    continue
    finally:
        imap.logout()
    return count
