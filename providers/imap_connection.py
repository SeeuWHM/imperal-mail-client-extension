"""IMAP/SMTP connection helpers — connect, authenticate, test."""
from __future__ import annotations

import imaplib
import logging
import smtplib
import ssl

from .text_utils import _xoauth2_string

log = logging.getLogger(__name__)


def _imap_connect_auth(email_addr: str, host: str, port: int,
                        password: str = "", access_token: str = "") -> imaplib.IMAP4_SSL:
    ctx_ssl = ssl.create_default_context()
    imap    = imaplib.IMAP4_SSL(host, port, ssl_context=ctx_ssl)
    if access_token:
        auth_str = _xoauth2_string(email_addr, access_token)
        imap.authenticate("XOAUTH2", lambda challenge: auth_str.encode())
    else:
        imap.login(email_addr, password)
    return imap


def _sync_imap_test(email_addr: str, password: str, host: str, port: int) -> tuple[bool, str]:
    try:
        imap = _imap_connect_auth(email_addr, host, port, password=password)
        imap.logout()
        return True, ""
    except imaplib.IMAP4.error as e:
        return False, f"IMAP auth failed: {e}"
    except Exception as e:
        return False, f"Connection error: {e}"


def _sync_smtp_test(email_addr: str, password: str, host: str, port: int) -> tuple[bool, str]:
    try:
        if port == 465:
            smtp = smtplib.SMTP_SSL(host, port, timeout=10)
        else:
            smtp = smtplib.SMTP(host, port, timeout=10)
            smtp.starttls()
        smtp.login(email_addr, password)
        smtp.quit()
        return True, ""
    except smtplib.SMTPAuthenticationError as e:
        return False, f"SMTP auth failed: {e}"
    except Exception as e:
        return False, f"SMTP connection error: {e}"
