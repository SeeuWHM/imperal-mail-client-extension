"""Text, encoding, MIME, and crypto helpers for the mail extension."""
from __future__ import annotations

import base64
import email.header
import logging
import re
from email.mime.text import MIMEText

from cryptography.fernet import Fernet

log = logging.getLogger(__name__)


def _encrypt_password(password: str, enc_key: str = "") -> str:
    if not enc_key: return password
    try: return Fernet(enc_key.encode()).encrypt(password.encode()).decode()
    except Exception as e: log.warning(f"Encryption failed: {e}"); return password


def _decrypt_password(value: str, is_encrypted: bool = True, enc_key: str = "") -> str:
    if not is_encrypted or not enc_key: return value
    try: return Fernet(enc_key.encode()).decrypt(value.encode()).decode()
    except Exception: return value


def _header(headers: list, name: str) -> str:
    for h in headers:
        if h["name"].lower() == name.lower(): return h["value"]
    return ""


def _decode_header(value: str) -> str:
    if not value: return ""
    parts = email.header.decode_header(value)
    decoded = []
    for part, charset in parts:
        if isinstance(part, bytes): decoded.append(part.decode(charset or "utf-8", errors="replace"))
        else: decoded.append(part)
    return "".join(decoded)


def _short_sender(raw: str) -> str:
    if "<" in raw: return raw.split("<")[0].strip().strip('"')
    return raw.strip()


def _strip_html(text: str) -> str:
    text = re.sub(r"<style[^>]*>.*?</style>", " ", text, flags=re.DOTALL)
    text = re.sub(r"<script[^>]*>.*?</script>", " ", text, flags=re.DOTALL)
    text = re.sub(r"<[^>]+>", " ", text)
    text = (text.replace("&nbsp;", " ").replace("&amp;", "&")
                .replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"'))
    return re.sub(r"\s+", " ", text).strip()


def _b64_decode(data: str) -> str:
    return base64.urlsafe_b64decode(data + "==").decode("utf-8", errors="replace")


def _decode_body(payload: dict) -> str:
    if payload.get("body", {}).get("data"):
        raw = _b64_decode(payload["body"]["data"])
        return _strip_html(raw) if raw.lstrip().startswith("<") else raw
    parts = payload.get("parts", [])
    for part in parts:
        if part.get("mimeType") == "text/plain" and part.get("body", {}).get("data"):
            return _b64_decode(part["body"]["data"])
    for part in parts:
        if part.get("mimeType", "").startswith("multipart/"):
            result = _decode_body(part)
            if result and result != "(no body)": return result
    for part in parts:
        if part.get("mimeType") == "text/html" and part.get("body", {}).get("data"):
            return _strip_html(_b64_decode(part["body"]["data"]))
    return "(no body)"


def _decode_body_with_type(payload: dict) -> tuple[str, str]:
    html_body = ""
    text_body = ""

    def _scan(p: dict) -> None:
        nonlocal html_body, text_body
        mime = p.get("mimeType", "")
        data = p.get("body", {}).get("data")
        if data and mime == "text/html" and not html_body:
            html_body = _b64_decode(data)
        elif data and mime == "text/plain" and not text_body:
            text_body = _b64_decode(data)
        elif data and not mime and not html_body and not text_body:
            raw = _b64_decode(data)
            if raw.lstrip().startswith("<"):
                html_body = raw
            else:
                text_body = raw
        for sub in p.get("parts", []):
            _scan(sub)

    _scan(payload)
    if html_body: return html_body, "html"
    if text_body: return text_body, "text"
    return "(no body)", "text"


def _build_message(to: str, subject: str, body: str, from_email: str = "",
                   cc: str = "", bcc: str = "", reply_to_id: str = "",
                   is_html: bool = False) -> str:
    msg = MIMEText(body, "html" if is_html else "plain", "utf-8")
    msg["To"]      = to
    msg["Subject"] = subject
    if from_email: msg["From"] = from_email
    if cc:         msg["Cc"]   = cc
    if bcc:        msg["Bcc"]  = bcc
    if reply_to_id:
        msg["In-Reply-To"] = reply_to_id
        msg["References"]  = reply_to_id
    return base64.urlsafe_b64encode(msg.as_bytes()).decode()


def _norm_graph_msg(msg: dict) -> dict:
    from_data = msg.get("from", {}).get("emailAddress", {})
    return {
        "id":              msg.get("id", ""),
        "thread_id":       msg.get("conversationId", ""),
        "subject":         msg.get("subject") or "(no subject)",
        "from":            from_data.get("address", "unknown"),
        "from_name":       from_data.get("name", ""),
        "date":            msg.get("receivedDateTime", ""),
        "unread":          not msg.get("isRead", True),
        "has_attachments": msg.get("hasAttachments", False),
        "preview":         (msg.get("bodyPreview") or "")[:150],
    }


def _xoauth2_string(email: str, access_token: str) -> str:
    raw = f"user={email}\x01auth=Bearer {access_token}\x01\x01"
    return base64.b64encode(raw.encode()).decode()
