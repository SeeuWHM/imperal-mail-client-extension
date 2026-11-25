"""Google Mail Provider — Gmail REST API (OAuth2).

Split into three files to stay under 300-line limit:
  google.py        — class skeleton + _normalize_msg (this file)
  google_read.py   — fetch, read, search, folder, thread
  google_write.py  — send, reply, forward, archive, delete, mark_read, star, move, purge
"""
from __future__ import annotations

from .base import BaseMailProvider
from .google_read import GoogleReadMixin
from .google_write import GoogleWriteMixin
from .google_filters import GoogleFilterMixin
from .helpers import _header, _short_sender


class GoogleMailProvider(GoogleReadMixin, GoogleWriteMixin, GoogleFilterMixin, BaseMailProvider):
    """Gmail provider — all methods via mixins, shared normalizer here."""

    @staticmethod
    def _normalize_msg(data: dict) -> dict:
        headers       = data.get("payload", {}).get("headers", [])
        label_ids     = data.get("labelIds", [])
        parts         = data.get("payload", {}).get("parts", [])
        has_attachments = any(
            p.get("filename") and p.get("body", {}).get("attachmentId") for p in parts
        )
        raw_from = _header(headers, "From") or "unknown"
        from .text_utils import _parse_sender
        sender_name, sender_email = _parse_sender(raw_from)
        return {
            "message_id":      data.get("id", ""),
            "thread_id":       data.get("threadId", ""),
            "from":            _short_sender(raw_from),
            "from_email":      sender_email,
            "from_raw":        raw_from,
            "subject":         _header(headers, "Subject") or "(no subject)",
            "snippet":         data.get("snippet", ""),
            "date":            _header(headers, "Date") or "",
            "unread":          "UNREAD"   in label_ids,
            "starred":         "STARRED"  in label_ids,
            "has_attachments": has_attachments,
            "labels":          label_ids,
        }
