"""IMAP/SMTP write operations — send, move, flag, purge, save to sent."""
from __future__ import annotations

import imaplib
import logging
import smtplib
import time
from email.mime.text import MIMEText

from .text_utils import _xoauth2_string
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

        smtp.sendmail(email_addr, all_recipients, msg.as_string())
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
        smtp.sendmail(email_addr, all_recipients, msg.as_string())
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


def _sync_imap_flag_op(email_addr: str, host: str, port: int, message_id: str,
                       flag: str, add: bool, *, password: str = "", access_token: str = "") -> tuple[bool, str]:
    try:
        imap = _imap_connect_auth(email_addr, host, port, password=password, access_token=access_token)
        imap.select("INBOX")
        imap.uid("STORE", message_id.encode(), "+FLAGS" if add else "-FLAGS", f"\\{flag}")
        imap.logout()
        return True, ""
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
