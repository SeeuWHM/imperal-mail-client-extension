"""IMAP read operations — inbox, fetch page, unread count, read, search, folder."""
from __future__ import annotations

import email as email_lib
import logging
import re

from .text_utils import _decode_header
from .helpers import IMAP_FOLDER_CANDIDATES
from .imap_connection import _imap_connect_auth

log = logging.getLogger(__name__)


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
    candidates = IMAP_FOLDER_CANDIDATES.get(imap_folder.lower(), [imap_folder])
    if imap_folder.upper() == "INBOX":
        candidates = ["INBOX"]
    count = 0
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
    imap.logout()
    return count


def _sync_imap_read(email_addr: str, host: str, port: int, message_id: str,
                    *, password: str = "", access_token: str = "") -> dict:
    imap = _imap_connect_auth(email_addr, host, port, password=password, access_token=access_token)
    imap.select("INBOX")
    _, msg_data = imap.uid("FETCH", message_id.encode(), "(RFC822)")
    if not msg_data or not msg_data[0]:
        imap.logout(); return {}
    raw = msg_data[0][1] if isinstance(msg_data[0], tuple) else msg_data[0]
    if not raw: imap.logout(); return {}
    msg = email_lib.message_from_bytes(raw)
    imap.uid("STORE", message_id.encode(), "+FLAGS", "\\Seen")
    imap.logout()
    html_body = ""
    text_body = ""
    if msg.is_multipart():
        for part in msg.walk():
            ct = part.get_content_type()
            charset = part.get_content_charset() or "utf-8"
            payload = part.get_payload(decode=True)
            if not payload: continue
            decoded = payload.decode(charset, errors="replace")
            if ct == "text/html" and not html_body:
                html_body = decoded
            elif ct == "text/plain" and not text_body:
                text_body = decoded
    else:
        charset = msg.get_content_charset() or "utf-8"
        payload = msg.get_payload(decode=True)
        if payload:
            decoded = payload.decode(charset, errors="replace")
            if msg.get_content_type() == "text/html":
                html_body = decoded
            else:
                text_body = decoded
    body = html_body or text_body
    body_type = "html" if html_body else "text"
    return {
        "subject":           _decode_header(msg.get("Subject", "(no subject)")),
        "from":              _decode_header(msg.get("From", "unknown")),
        "to":                _decode_header(msg.get("To", "")),
        "date":              msg.get("Date", ""),
        "body":              body,
        "body_type":         body_type,
        "message_id_header": msg.get("Message-ID", ""),
    }


def _sync_imap_search(email_addr: str, host: str, port: int, query: str, max_results: int = 10,
                      *, password: str = "", access_token: str = "") -> list[dict]:
    def _map_query(q: str) -> str:
        ql = q.strip().lower()
        if ql.startswith("from:"):    return f'FROM "{q[5:].strip()}"'
        if ql.startswith("to:"):      return f'TO "{q[3:].strip()}"'
        if ql.startswith("subject:"): return f'SUBJECT "{q[8:].strip()}"'
        if ql in ("is:unread", "unread"): return "UNSEEN"
        if ql in ("is:read",   "read"):   return "SEEN"
        return f'TEXT "{q.strip()}"'
    try:
        imap = _imap_connect_auth(email_addr, host, port, password=password, access_token=access_token)
        imap.select("INBOX")
        _, uid_data = imap.uid("SEARCH", _map_query(query))
        uid_list = uid_data[0].split() if uid_data and uid_data[0] else []
        recent   = uid_list[-max_results:][::-1]
        messages = []
        for uid in recent:
            _, msg_data = imap.uid("FETCH", uid, "(RFC822.HEADER)")
            if not msg_data or not msg_data[0]: continue
            raw = msg_data[0][1] if isinstance(msg_data[0], tuple) else msg_data[0]
            if not raw: continue
            msg = email_lib.message_from_bytes(raw)
            messages.append({
                "id":      uid.decode(),
                "subject": _decode_header(msg.get("Subject", "(no subject)")),
                "from":    _decode_header(msg.get("From", "unknown")),
                "date":    msg.get("Date", ""),
            })
        imap.logout()
        return messages
    except Exception as e:
        log.warning(f"IMAP search failed: {e}")
        return None


def _sync_imap_folder(email_addr: str, host: str, port: int, folder_name: str,
                      max_results: int = 20, *, password: str = "", access_token: str = "") -> list[dict]:
    try:
        imap       = _imap_connect_auth(email_addr, host, port, password=password, access_token=access_token)
        candidates = IMAP_FOLDER_CANDIDATES.get(folder_name.lower(), [folder_name])
        selected   = False
        for candidate in candidates:
            r, _ = imap.select(f'"{candidate}"', readonly=True)
            if r == "OK": selected = True; break
        if not selected: imap.logout(); return []
        search_criteria = "UNSEEN" if folder_name.lower() == "unread" else "ALL"
        _, uid_data = imap.uid("SEARCH", search_criteria)
        uid_list = uid_data[0].split() if uid_data and uid_data[0] else []
        recent   = uid_list[-max_results:][::-1]
        messages = []
        for uid in recent:
            _, msg_data = imap.uid("FETCH", uid, "(RFC822.HEADER)")
            if not msg_data or not msg_data[0]: continue
            raw = msg_data[0][1] if isinstance(msg_data[0], tuple) else msg_data[0]
            if not raw: continue
            msg = email_lib.message_from_bytes(raw)
            messages.append({
                "id":      uid.decode(),
                "subject": _decode_header(msg.get("Subject", "(no subject)")),
                "from":    _decode_header(msg.get("From", "unknown")),
                "date":    msg.get("Date", ""),
            })
        imap.logout()
        return messages
    except Exception as e:
        log.warning(f"IMAP folder browse failed: {e}")
        return None
