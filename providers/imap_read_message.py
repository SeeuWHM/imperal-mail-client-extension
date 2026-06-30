"""IMAP message read, search, and folder browse operations."""
from __future__ import annotations

import email as email_lib
import logging
import re

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


def _gmail_to_imap(query: str) -> str:
    """Translate a Gmail-style search query to an IMAP SEARCH criteria string.

    Handles compound queries (from:X subject:Y → AND), quoted values, and
    the {term1 OR term2} OR-block syntax produced by _build_filter_query.
    Multiple clauses are AND-ed (IMAP implicit AND = space-separated criteria).
    """
    import shlex

    query = query.strip()
    if not query:
        return "ALL"

    # Handle Gmail OR-block: {from:a OR from:b} → OR FROM "a" FROM "b"
    if query.startswith("{") and query.endswith("}"):
        inner = query[1:-1].strip()
        clauses = [c.strip() for c in re.split(r"\bOR\b", inner, flags=re.IGNORECASE)]
        imap_clauses = [_gmail_to_imap(c) for c in clauses if c.strip()]
        if len(imap_clauses) == 1:
            return imap_clauses[0]
        if len(imap_clauses) == 2:
            return f"OR {imap_clauses[0]} {imap_clauses[1]}"
        # Nest OR pairs: OR A (OR B C) etc.
        result = imap_clauses[-1]
        for c in reversed(imap_clauses[:-1]):
            result = f"OR {c} {result}"
        return result

    # Tokenize respecting quoted strings (shlex strips surrounding quotes)
    try:
        tokens = shlex.split(query)
    except ValueError:
        tokens = query.split()

    parts = []
    for token in tokens:
        tl = token.lower()
        if tl in ("and", "or"):
            continue
        if tl.startswith("from:"):
            val = token[5:].strip('"')
            parts.append(f'FROM "{val}"')
        elif tl.startswith("to:"):
            val = token[3:].strip('"')
            parts.append(f'TO "{val}"')
        elif tl.startswith("subject:"):
            val = token[8:].strip('"')
            parts.append(f'SUBJECT "{val}"')
        elif tl in ("is:unread", "unread"):
            parts.append("UNSEEN")
        elif tl in ("is:read", "read"):
            parts.append("SEEN")
        elif tl.startswith(("in:", "newer_than:", "older_than:", "after:", "before:", "has:", "label:")):
            pass  # skip Gmail-only operators
        else:
            val = token.strip('"')
            if val:
                parts.append(f'TEXT "{val}"')

    return " ".join(parts) if parts else "ALL"


def _sync_imap_search(email_addr: str, host: str, port: int, query: str, max_results: int = 10,
                      *, password: str = "", access_token: str = "") -> list[dict] | None:

    # Search across INBOX + common Sent/Archive folders for full coverage
    _SEARCH_FOLDERS = [
        "INBOX",
        "Sent", "Sent Items", "INBOX.Sent", "[Gmail]/Sent Mail",
        "Archive", "[Gmail]/All Mail",
    ]

    try:
        imap    = _imap_connect_auth(email_addr, host, port, password=password, access_token=access_token)
        imap_q  = _gmail_to_imap(query)
        all_hits: list[tuple[str, bytes]] = []  # (folder, uid_bytes)
        seen_subjects: set[str] = set()

        for folder in _SEARCH_FOLDERS:
            try:
                r, _ = imap.select(f'"{folder}"', readonly=True)
                if r != "OK":
                    continue
                _, uid_data = imap.uid("SEARCH", imap_q)
                uids = uid_data[0].split() if uid_data and uid_data[0] else []
                for uid in uids:
                    all_hits.append((folder, uid))
            except Exception:
                continue

        # Sort by UID desc (most recent first), take top max_results
        # UIDs are per-folder so we fetch headers to sort by date properly
        total_found = len(all_hits)
        recent_hits = all_hits[-max_results:][::-1]

        messages = []
        for folder, uid in recent_hits:
            try:
                imap.select(f'"{folder}"', readonly=True)
                _, msg_data = imap.uid("FETCH", uid, "(RFC822.HEADER)")
                if not msg_data or not msg_data[0]:
                    continue
                raw = msg_data[0][1] if isinstance(msg_data[0], tuple) else msg_data[0]
                if not raw:
                    continue
                msg     = email_lib.message_from_bytes(raw)
                subject = _decode_header(msg.get("Subject", "(no subject)"))
                sender  = _decode_header(msg.get("From", "unknown"))
                date    = msg.get("Date", "")
                # Deduplicate by subject+sender (same message can appear in multiple folders)
                dedup_key = f"{subject}|{sender}"
                if dedup_key in seen_subjects:
                    total_found -= 1
                    continue
                seen_subjects.add(dedup_key)
                messages.append({
                    "id":      uid.decode(),
                    "subject": subject,
                    "from":    sender,
                    "date":    date,
                })
            except Exception:
                continue

        imap.logout()
        return messages, total_found
    except Exception as e:
        log.warning(f"IMAP search failed: {e}")
        return None, 0


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
