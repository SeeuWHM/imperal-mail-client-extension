"""IMAP read operations — inbox, fetch page, unread count."""
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
                    import re as _re
                    m_total  = _re.search(rb"MESSAGES\s+(\d+)", data[0])
                    m_unseen = _re.search(rb"UNSEEN\s+(\d+)", data[0])
                    total  = int(m_total.group(1))  if m_total  else 0
                    unread = int(m_unseen.group(1)) if m_unseen else 0
                    return {"total": total, "unread": unread}
            except Exception:
                continue
    finally:
        try:
            imap.logout()
        except Exception:
            pass
    return {"total": 0, "unread": 0}


def _sync_imap_inbox(email_addr: str, host: str, port: int, max_results: int = 20,
                     *, password: str = "", access_token: str = "") -> list[dict]:
    imap = _imap_connect_auth(email_addr, host, port, password=password, access_token=access_token)
    imap.select("INBOX")
    _, uid_data   = imap.uid("SEARCH", "ALL")
    all_uids      = uid_data[0].split() if uid_data and uid_data[0] else []
    _, useen_data = imap.uid("SEARCH", "UNSEEN")
    unseen_uids   = set(useen_data[0].split()) if useen_data and useen_data[0] else set()
    recent_uids = all_uids[-max_results:][::-1]
    messages    = []
    for uid in recent_uids:
        _, msg_data = imap.uid("FETCH", uid, "(RFC822.HEADER)")
        if not msg_data or not msg_data[0]: continue
        raw = msg_data[0][1] if isinstance(msg_data[0], tuple) else msg_data[0]
        if not raw: continue
        msg = email_lib.message_from_bytes(raw)
        messages.append({
            "id":               uid.decode(),
            "thread_id":        uid.decode(),
            "subject":          _decode_header(msg.get("Subject", "(no subject)")),
            "from":             _decode_header(msg.get("From", "unknown")),
            "date":             msg.get("Date", ""),
            "unread":           uid in unseen_uids,
            "message_id_header": msg.get("Message-ID", ""),
        })
    imap.logout()
    return messages


def _sync_imap_fetch_page(email_addr: str, host: str, port: int,
                          imap_folder: str, limit: int,
                          last_uid: int | None,
                          *, password: str = "",
                          access_token: str = "") -> tuple[list[dict], int | None, bool]:
    imap = _imap_connect_auth(email_addr, host, port,
                               password=password, access_token=access_token)
    # IMAP has no "starred" folder — flagged messages live in INBOX with \Flagged flag
    if imap_folder.lower() == "starred":
        imap.select('"INBOX"', readonly=True)
        _, uid_data = imap.uid("SEARCH", "FLAGGED")
        all_uids = uid_data[0].split() if uid_data and uid_data[0] else []
        if not all_uids:
            imap.logout()
            return [], None, False
        # Skip the folder-selection block below; uid_ints handled after this branch
        uid_ints = sorted([int(u) for u in all_uids], reverse=True)
        if last_uid is not None:
            uid_ints = [u for u in uid_ints if u < last_uid]
        page_uids = uid_ints[:limit]
        if not page_uids:
            imap.logout()
            return [], None, False
        _, useen_data = imap.uid("SEARCH", "UNSEEN")
        unseen_uids = set(useen_data[0].split()) if useen_data and useen_data[0] else set()
        messages: list[dict] = []
        for uid_int in page_uids:
            uid_bytes = str(uid_int).encode()
            _, msg_data = imap.uid("FETCH", uid_bytes, "(RFC822.HEADER FLAGS)")
            if not msg_data or not msg_data[0]:
                continue
            raw = msg_data[0][1] if isinstance(msg_data[0], tuple) else msg_data[0]
            if not raw:
                continue
            msg = email_lib.message_from_bytes(raw)
            messages.append({
                "message_id": str(uid_int), "thread_id": str(uid_int),
                "from":    _decode_header(msg.get("From", "unknown")),
                "subject": _decode_header(msg.get("Subject", "(no subject)")),
                "snippet": "", "date": msg.get("Date", ""),
                "unread":  uid_bytes in unseen_uids, "starred": True,
                "has_attachments": False, "labels": [],
            })
        imap.logout()
        lowest = page_uids[-1] if page_uids else None
        remaining = [u for u in uid_ints if u < lowest] if lowest else []
        return messages, (lowest if remaining else None), bool(remaining)

    candidates = IMAP_FOLDER_CANDIDATES.get(imap_folder.lower(), [imap_folder])
    if imap_folder.upper() == "INBOX":
        candidates = ["INBOX"]
    selected = False
    for candidate in candidates:
        r, _ = imap.select(f'"{candidate}"', readonly=True)
        if r == "OK":
            selected = True
            break
    if not selected:
        imap.logout()
        return [], None, False

    _, uid_data = imap.uid("SEARCH", "ALL")
    all_uids = uid_data[0].split() if uid_data and uid_data[0] else []
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

    _, useen_data = imap.uid("SEARCH", "UNSEEN")
    unseen_uids = set(useen_data[0].split()) if useen_data and useen_data[0] else set()

    messages: list[dict] = []
    for uid_int in page_uids:
        uid_bytes = str(uid_int).encode()
        _, msg_data = imap.uid("FETCH", uid_bytes, "(RFC822.HEADER FLAGS)")
        if not msg_data or not msg_data[0]:
            continue
        raw = msg_data[0][1] if isinstance(msg_data[0], tuple) else msg_data[0]
        if not raw:
            continue
        msg = email_lib.message_from_bytes(raw)
        starred = b"\\Flagged" in (msg_data[0][0] if isinstance(msg_data[0], tuple) else b"")
        messages.append({
            "message_id":  str(uid_int),
            "thread_id":   str(uid_int),
            "from":        _decode_header(msg.get("From", "unknown")),
            "subject":     _decode_header(msg.get("Subject", "(no subject)")),
            "snippet":     "",
            "date":        msg.get("Date", ""),
            "unread":      uid_bytes in unseen_uids,
            "starred":     starred,
            "has_attachments": False,
            "labels":      [],
        })

    imap.logout()
    lowest_fetched = page_uids[-1] if page_uids else None
    remaining = [u for u in uid_ints if u < lowest_fetched] if lowest_fetched else []
    has_more = len(remaining) > 0
    new_last_uid = lowest_fetched if has_more else None
    return messages, new_last_uid, has_more


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

