"""IMAP message read, search, and folder browse operations."""
from __future__ import annotations

import email as email_lib
import logging

from .text_utils import _decode_header
from .helpers import IMAP_FOLDER_CANDIDATES
from .imap_connection import _imap_connect_auth

log = logging.getLogger(__name__)

# Folders to try when looking up a message by UID (INBOX first — most common).
# IMAP UIDs are per-mailbox, so a UID from Sent is not visible from INBOX.
_IMAP_READ_FOLDER_ORDER = [
    "INBOX",
    "Sent", "Sent Items", "[Gmail]/Sent Mail", "INBOX.Sent",
    "Drafts", "[Gmail]/Drafts", "INBOX.Drafts",
    "Trash", "[Gmail]/Trash", "Deleted Items", "Deleted Messages",
    "Junk", "Spam", "[Gmail]/Spam", "Junk Email",
    "Archive", "[Gmail]/All Mail",
]


def _parse_imap_body(msg) -> tuple[str, str]:
    """Extract (body_text, body_type) from an email.message.Message object."""
    html_body = ""
    text_body = ""
    if msg.is_multipart():
        for part in msg.walk():
            ct      = part.get_content_type()
            charset = part.get_content_charset() or "utf-8"
            payload = part.get_payload(decode=True)
            if not payload:
                continue
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
    body      = html_body or text_body
    body_type = "html" if html_body else "text"
    return body, body_type


def _sync_imap_read(email_addr: str, host: str, port: int, message_id: str,
                    *, password: str = "", access_token: str = "") -> dict:
    """Fetch and parse a single message by UID, searching across all common folders."""
    imap = _imap_connect_auth(email_addr, host, port, password=password, access_token=access_token)
    uid_bytes = message_id.encode()
    for folder in _IMAP_READ_FOLDER_ORDER:
        try:
            r, _ = imap.select(f'"{folder}"')
            if r != "OK":
                continue
            _, msg_data = imap.uid("FETCH", uid_bytes, "(RFC822)")
            if not msg_data or not msg_data[0]:
                continue
            raw = msg_data[0][1] if isinstance(msg_data[0], tuple) else msg_data[0]
            if not raw:
                continue
            msg = email_lib.message_from_bytes(raw)
            imap.uid("STORE", uid_bytes, "+FLAGS", "\\Seen")
            replied = False
            try:
                _, flags_resp = imap.uid("FETCH", uid_bytes, "FLAGS")
                if flags_resp and flags_resp[0]:
                    flags_line = flags_resp[0]
                    if isinstance(flags_line, tuple):
                        flags_line = flags_line[0]
                    replied = b"\\Answered" in (flags_line if isinstance(flags_line, bytes) else b"")
            except Exception:
                pass
            imap.logout()
            body, body_type = _parse_imap_body(msg)
            return {
                "subject":           _decode_header(msg.get("Subject", "(no subject)")),
                "from":              _decode_header(msg.get("From", "unknown")),
                "to":                _decode_header(msg.get("To", "")),
                "cc":                _decode_header(msg.get("Cc", "")),
                "date":              msg.get("Date", ""),
                "body":              body,
                "body_type":         body_type,
                "message_id_header": msg.get("Message-ID", ""),
                "replied":           replied,
            }
        except Exception:
            continue
    imap.logout()
    return {}


def _sync_imap_search(email_addr: str, host: str, port: int, query: str, max_results: int = 10,
                      *, password: str = "", access_token: str = "") -> list[dict] | None:
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
                      max_results: int = 20, *, password: str = "", access_token: str = "") -> list[dict] | None:
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
