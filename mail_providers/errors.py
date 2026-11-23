"""Typed mail provider errors and ActionResult error translation (K2)."""
from __future__ import annotations

import smtplib
from typing import Any

from imperal_sdk.chat.action_result import ActionResult

AUTH_EXPIRED_CODE = "AUTH_EXPIRED"


class MailAuthExpiredError(RuntimeError):
    """Raised when a mailbox OAuth grant or IMAP/SMTP credential is expired or rejected.

    Only a human can fix this (reconnect OAuth or update the mailbox password/app-password).
    """

    def __init__(
        self,
        message: str,
        *,
        email: str = "",
        provider: str = "",
        status_code: int | None = None,
    ) -> None:
        super().__init__(message)
        self.email = email
        self.provider = provider
        self.status_code = status_code


def _extract_http_status(exc: BaseException) -> int | None:
    resp = getattr(exc, "response", None)
    status = getattr(resp, "status_code", None)
    return status if isinstance(status, int) else None


def raise_if_auth_expired(
    resp: Any,
    *,
    acc: dict[str, Any] | None = None,
    provider: str = "",
) -> Any:
    """Raise :class:`MailAuthExpiredError` if an HTTP response returned 401 Unauthorized."""
    status = getattr(resp, "status_code", None)
    if status == 401:
        email = str((acc or {}).get("email") or "")
        who = f" for {email}" if email else ""
        prov = f" ({provider})" if provider else ""
        raise MailAuthExpiredError(
            f"Mailbox authentication expired{who}{prov} (HTTP 401) — reconnect mailbox.",
            email=email,
            provider=provider,
            status_code=401,
        )
    return resp


def is_auth_expired_error(exc: BaseException) -> bool:
    """Return True iff *exc* is a structured mailbox authentication failure."""
    if isinstance(exc, MailAuthExpiredError):
        return True
    if isinstance(exc, smtplib.SMTPAuthenticationError):
        return True
    if _extract_http_status(exc) == 401:
        return True
    return False


def mail_error_result(exc: BaseException, *, retryable: bool = False) -> ActionResult:
    """Convert a handler exception into an :class:`ActionResult`.

    Auth-expired failures always emit ``code="AUTH_EXPIRED"`` with ``retryable=False``
    so the kernel (and SDK >=6.9) surfaces a structured ``needs_human`` signal.
    All other exceptions preserve the caller's ``retryable`` flag and message.
    """
    if is_auth_expired_error(exc):
        msg = str(exc).strip() or "Mailbox authentication expired — reconnect mailbox."
        return ActionResult.error(msg, retryable=False, code=AUTH_EXPIRED_CODE)
    return ActionResult.error(str(exc), retryable=retryable)
