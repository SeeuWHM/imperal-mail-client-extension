"""IMAP/SMTP write + search operations — send, move, flag, purge, save to sent, search, folder."""
from __future__ import annotations

import email as email_lib
import imaplib
import logging
import smtplib
import time
from email.mime.text import MIMEText

from .text_utils import _xoauth2_string, _decode_header
from .helpers import IMAP_FOLDER_CANDIDATES
from .imap_connection import _imap_connect_auth

log = logging.getLogger(__name__)


def _sync_smtp_send(email_addr: str, password: str, smtp_host: str, smtp_port: int,
                    to: str, subject: str, body: str, cc: str = "", bcc: str = "",
                    reply_to_mid: str = "") -> tuple[bool, str, bytes]:
    try:
        msg            = MIMEText(body, "plain", "utf-8")
        msg["From"]    = email_addr; msg["To"] = to; msg["Subject"] = subject
        if cc:           msg["Cc"] = cc
        if reply_to_mid: msg["In-Reply-To"] = reply_to_mid; msg["References"] = reply_to_mid
        all_recipients = [a.strip() for a in to.split(",") if a.strip()]
        if cc:  all_recipients += [a.strip() for a in cc.split(",") if a.strip()]
        if bcc: all_recipients += [a.strip() for a in bcc.split(",") if a.strip()]
        msg_bytes = msg.as_bytes()

        if smtp_port == 465:
            smtp = smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=30)
            smtp.login(email_addr, password)
        else:
            smtp = smtplib.SMTP(smtp_host, smtp_port, timeout=30)
            smtp.starttls()
            smtp.login(email_addr, password)

        smtp.sendmail(email_addr, all_recipients, msg_bytes)
        smtp.quit()
        return True, "", msg_bytes
    except Exception as e:
        return False, str(e), b""


def _sync_smtp_xoauth2_send(email_addr: str, access_token: str, smtp_host: str, smtp_port: int,
                             to: str, subject: str, body: str, cc: str = "", bcc: str = "",
                             reply_to_mid: str = "") -> tuple[bool, str, bytes]:
    try:
        auth_str       = _xoauth2_string(email_addr, access_token)
        msg            = MIMEText(body, "plain", "utf-8")
        msg["From"]    = email_addr; msg["To"] = to; msg["Subject"] = subject
        if cc:           msg["Cc"] = cc
        if reply_to_mid: msg["In-Reply-To"] = reply_to_mid; msg["References"] = reply_to_mid
        all_recipients = [a.strip() for a in to.split(",") if a.strip()]
        if cc:  all_recipients += [a.strip() for a in cc.split(",") if a.strip()]
        if bcc: all_recipients += [a.strip() for a in bcc.split(",") if a.strip()]
        msg_bytes = msg.as_bytes()

        smtp = smtplib.SMTP(smtp_host, smtp_port, timeout=30)
        smtp.ehlo(); smtp.starttls(); smtp.ehlo()
        code, resp_bytes = smtp.docmd("AUTH", "XOAUTH2 " + auth_str)
        if code != 235:
            smtp.quit()
            return False, f"XOAUTH2 AUTH failed ({code}): {resp_bytes.decode() if isinstance(resp_bytes, bytes) else str(resp_bytes)}", b""
        smtp.sendmail(email_addr, all_recipients, msg_bytes)
        smtp.quit()
        return True, "", msg_bytes
    except Exception as e:
        return False, str(e), b""


def _sync_imap_move(email_addr: str, host: str, port: int, message_id: str,
                    dest_folders: list, *, password: str = "", access_token: str = "",
                    source_folder: str = "INBOX",
                    source_candidates: list = None) -> tuple[bool, str]:
    try:
        imap = _imap_connect_auth(email_addr, host, port, password=password, access_token=access_token)
        srcs = source_candidates or [source_folder]
        selected = None
        for src in srcs:
            r, _ = imap.select(f'"{src}"')
            if r == "OK":
                selected = src
                break
        if not selected:
            imap.logout()
            return False, f"Source folder not found. Tried: {srcs}"

        copied = False
        for folder in dest_folders:
            try:
                r, _ = imap.uid("COPY", message_id.encode(), f'"{folder}"')
                if r == "OK":
                    copied = True
                    log.info(f"IMAP UID COPY {message_id} → \"{folder}\" OK for {email_addr}")
                    break
            except Exception as copy_err:
                log.debug(f"IMAP UID COPY to \"{folder}\" failed: {copy_err}")
                continue

        if not copied:
            imap.logout()
            return False, (
                f"Could not move message UID {message_id} from '{selected}' to {dest_folders}. "
                f"The message may have already been moved, or the destination folder is unavailable."
            )

        imap.uid("STORE", message_id.encode(), "+FLAGS", "\\Deleted")
        imap.expunge()
        imap.logout()
        return True, ""
    except Exception as e:
        return False, str(e)


_IMAP_FLAG_FOLDER_ORDER = [
    "INBOX",
    "Sent", "Sent Items", "[Gmail]/Sent Mail", "INBOX.Sent",
    "Drafts", "[Gmail]/Drafts", "INBOX.Drafts",
    "Trash", "[Gmail]/Trash", "Deleted Items", "Deleted Messages",
    "Junk", "Spam", "[Gmail]/Spam", "Junk Email",
    "Archive", "[Gmail]/All Mail",
]


def _sync_imap_flag_op(email_addr: str, host: str, port: int, message_id: str,
                       flag: str, add: bool, *, password: str = "", access_token: str = "") -> tuple[bool, str]:
    """Set or clear an IMAP flag on a message, searching across all common folders."""
    uid_bytes  = message_id.encode()
    flag_cmd   = "+FLAGS" if add else "-FLAGS"
    flag_value = f"\\{flag}"
    try:
        imap = _imap_connect_auth(email_addr, host, port, password=password, access_token=access_token)
        for folder in _IMAP_FLAG_FOLDER_ORDER:
            try:
                r, _ = imap.select(f'"{folder}"')
                if r != "OK":
                    continue
                # Verify the message exists in this folder before flagging
                _, fetch_data = imap.uid("FETCH", uid_bytes, "(FLAGS)")
                if not fetch_data or not fetch_data[0]:
                    continue
                imap.uid("STORE", uid_bytes, flag_cmd, flag_value)
                imap.logout()
                return True, ""
            except Exception:
                continue
        imap.logout()
        return False, f"Message UID {message_id} not found in any folder"
    except Exception as e:
        return False, str(e)


def _save_to_imap_sent(email_addr: str, imap_host: str, imap_port: int, msg_bytes: bytes,
                       *, password: str = "", access_token: str = "") -> None:
    try:
        import imaplib as _imap
        imap = _imap_connect_auth(email_addr, imap_host, imap_port, password=password, access_token=access_token)
        for folder in ("Sent", "Sent Items", "[Gmail]/Sent Mail", "INBOX.Sent"):
            try:
                result = imap.append(f'"{folder}"', "(\\Seen)",
                                     imaplib.Time2Internaldate(time.time()), msg_bytes)
                if result[0] == "OK": break
            except Exception: continue
        try: imap.logout()
        except Exception: pass
    except Exception as e:
        log.debug(f"_save_to_imap_sent non-critical: {e}")


def _sync_imap_purge(email_addr: str, host: str, port: int, message_id: str,
                     source_folder: str = "Trash", *,
                     password: str = "", access_token: str = "") -> tuple[bool, str]:
    try:
        imap = _imap_connect_auth(email_addr, host, port, password=password, access_token=access_token)
        imap.select(f'"{source_folder}"')
        imap.uid("STORE", message_id.encode(), "+FLAGS", "\\Deleted")
        imap.expunge()
        imap.logout()
        return True, ""
    except Exception as e:
        return False, str(e)


# ── Search + folder browse (moved from imap_read.py for file size) ──────── #

def _sync_imap_search(email_addr: str, host: str, port: int, query: str, max_results: int = 10,
                      *, password: str = "", access_token: str = "") -> list[dict] | None:
    def _map_query(q: str) -> str:
        ql = q.strip().lower()
        if ql.startswith("from:"):       return f'FROM "{q[5:].strip()}"'
        if ql.startswith("to:"):         return f'TO "{q[3:].strip()}"'
        if ql.startswith("subject:"):    return f'SUBJECT "{q[8:].strip()}"'
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
        log.warning("IMAP search failed: %s", e)
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
        log.warning("IMAP folder browse failed: %s", e)
        return None
