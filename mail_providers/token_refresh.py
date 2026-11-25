"""Token refresh and OAuth HTTP helpers for all mail providers."""
from __future__ import annotations

import base64
import logging
import time

from imperal_sdk import Context

from .errors import MailAuthExpiredError, raise_if_auth_expired
from .helpers import (
    COLLECTION,
    GOOGLE_TOKEN_URL, GMAIL_API,
    MS_TOKEN_URL, MS_SCOPE, MS_GRAPH_BASE,
    YAHOO_TOKEN_URL,
    _is_microsoft_account,
)

log = logging.getLogger(__name__)


async def _api_get(ctx: Context, path: str, acc: dict, **kwargs):
    acc = await _refresh_token_if_needed(ctx, acc)
    resp = await ctx.http.get(
        f"{GMAIL_API}/{path}",
        headers={"Authorization": f"Bearer {acc['access_token']}"},
        **kwargs,
    )
    return raise_if_auth_expired(resp, acc=acc, provider="google")


async def _api_post(ctx: Context, path: str, acc: dict, **kwargs):
    acc = await _refresh_token_if_needed(ctx, acc)
    resp = await ctx.http.post(
        f"{GMAIL_API}/{path}",
        headers={"Authorization": f"Bearer {acc['access_token']}"},
        **kwargs,
    )
    return raise_if_auth_expired(resp, acc=acc, provider="google")


async def _api_delete(ctx: Context, path: str, acc: dict, **kwargs):
    acc = await _refresh_token_if_needed(ctx, acc)
    resp = await ctx.http.delete(
        f"{GMAIL_API}/{path}",
        headers={"Authorization": f"Bearer {acc['access_token']}"},
        **kwargs,
    )
    return raise_if_auth_expired(resp, acc=acc, provider="google")


async def _graph_get(ctx: Context, path: str, acc: dict, **kwargs):
    acc = await _refresh_token_if_needed(ctx, acc)
    resp = await ctx.http.get(
        f"{MS_GRAPH_BASE}{path}",
        headers={"Authorization": f"Bearer {acc['access_token']}"},
        **kwargs,
    )
    return raise_if_auth_expired(resp, acc=acc, provider="microsoft")


async def _graph_post(ctx: Context, path: str, acc: dict, **kwargs):
    acc = await _refresh_token_if_needed(ctx, acc)
    resp = await ctx.http.post(
        f"{MS_GRAPH_BASE}{path}",
        headers={"Authorization": f"Bearer {acc['access_token']}"},
        **kwargs,
    )
    return raise_if_auth_expired(resp, acc=acc, provider="microsoft")


async def _graph_patch(ctx: Context, path: str, acc: dict, **kwargs):
    acc = await _refresh_token_if_needed(ctx, acc)
    resp = await ctx.http.patch(
        f"{MS_GRAPH_BASE}{path}",
        headers={"Authorization": f"Bearer {acc['access_token']}"},
        **kwargs,
    )
    return raise_if_auth_expired(resp, acc=acc, provider="microsoft")


_OAUTH_USER_GRANT_ERRORS = frozenset({
    "invalid_grant",
    "invalid_token",
    "interaction_required",
    "consent_required",
    "login_required",
})
_OAUTH_CLIENT_ERRORS = frozenset({
    "invalid_client",
    "unauthorized_client",
    "invalid_request",
    "unsupported_grant_type",
    "invalid_scope",
})


def _extract_oauth_error_code(resp) -> str:
    """Extract RFC 6749 OAuth token-endpoint ``error`` code (lowercased) if present."""
    try:
        body = resp.json()
    except Exception:
        return ""
    if not isinstance(body, dict):
        return ""
    err = body.get("error")
    if isinstance(err, str):
        return err.strip().lower()
    if isinstance(err, dict):
        code = err.get("code") or err.get("error")
        if isinstance(code, str):
            return code.strip().lower()
    return ""


def _is_oauth_user_grant_expired(resp) -> tuple[bool, str]:
    """Distinguish expired/revoked user OAuth grant from OAuth client errors.

    On HTTP 400 from Google/Microsoft/Yahoo token endpoints, only an explicit
    user-grant error (e.g. ``invalid_grant``) means the user must reconnect
    their mailbox. Client-side OAuth failures (``invalid_client``,
    ``unauthorized_client``, ``invalid_request``, etc.) indicate a broken app
    secret/config on our side and must NEVER ask every user to reconnect.
    """
    err_code = _extract_oauth_error_code(resp)
    if err_code in _OAUTH_USER_GRANT_ERRORS:
        return True, err_code
    if err_code in _OAUTH_CLIENT_ERRORS:
        return False, err_code
    status = getattr(resp, "status_code", None)
    if status == 400:
        return False, err_code
    if status == 401:
        return (not err_code), err_code
    return False, err_code


async def _handle_oauth_refresh_failure(
    ctx: Context,
    acc: dict,
    resp,
    *,
    provider: str,
    label: str,
) -> dict:
    """Handle non-200 OAuth token refresh response uniformly across providers."""
    status = getattr(resp, "status_code", 0)
    is_user_grant, err_code = _is_oauth_user_grant_expired(resp)
    detail = f" ({err_code})" if err_code else ""
    log.warning(f"{label} token refresh failed: {status}{detail}")
    if is_user_grant:
        acc["_needs_reauth"] = True
        doc_id = acc.get("doc_id")
        if doc_id:
            try:
                await ctx.store.update(COLLECTION, doc_id, {"_needs_reauth": True})
            except Exception:
                pass
        email = str(acc.get("email") or "")
        who = f" for {email}" if email else ""
        raise MailAuthExpiredError(
            f"{label} mailbox token expired{who} (HTTP {status}) — reconnect mailbox.",
            email=email,
            provider=provider,
            status_code=status,
        )
    if status in (400, 401):
        # OAuth client/config error (e.g. invalid_client): abort immediately so
        # we do NOT proceed with a stale access_token and trigger a misleading
        # HTTP 401 -> MailAuthExpiredError on the provider API.
        raise RuntimeError(
            f"{label} OAuth token refresh failed (HTTP {status}{detail}) — OAuth client error."
        )
    return acc


async def _refresh_google_token(ctx: Context, acc: dict) -> dict:
    client_id     = await ctx.secrets.get("google_client_id")
    client_secret = await ctx.secrets.get("google_client_secret")
    if not client_id or not client_secret:
        log.warning("Google OAuth credentials not set in secrets — cannot refresh token")
        return acc
    resp = await ctx.http.post(GOOGLE_TOKEN_URL, data={
        "client_id":     client_id,
        "client_secret": client_secret,
        "refresh_token": acc["refresh_token"],
        "grant_type":    "refresh_token",
    })
    if resp.status_code != 200:
        return await _handle_oauth_refresh_failure(
            ctx, acc, resp, provider="google", label="Google",
        )
    tokens = resp.json()
    acc["access_token"] = tokens["access_token"]
    acc["expires_at"]   = int(time.time()) + tokens.get("expires_in", 3600)
    doc_id = acc.pop("doc_id")
    await ctx.store.update(COLLECTION, doc_id, {k: v for k, v in acc.items()})
    acc["doc_id"] = doc_id
    return acc


async def _refresh_microsoft_token(ctx: Context, acc: dict) -> dict:
    client_id     = await ctx.secrets.get("microsoft_client_id")
    client_secret = await ctx.secrets.get("microsoft_client_secret")
    if not client_id or not client_secret:
        log.warning("Microsoft OAuth credentials not set in secrets — cannot refresh token")
        return acc
    resp = await ctx.http.post(MS_TOKEN_URL, data={
        "grant_type": "refresh_token", "client_id": client_id,
        "client_secret": client_secret, "refresh_token": acc["refresh_token"],
        "scope": MS_SCOPE,
    })
    if resp.status_code != 200:
        return await _handle_oauth_refresh_failure(
            ctx, acc, resp, provider="microsoft", label="Microsoft",
        )
    tokens = resp.json()
    acc["access_token"] = tokens["access_token"]
    acc["expires_at"]   = int(time.time()) + tokens.get("expires_in", 3600)
    if "refresh_token" in tokens: acc["refresh_token"] = tokens["refresh_token"]
    acc.pop("_needs_reauth", None)
    doc_id = acc.pop("doc_id")
    await ctx.store.update(COLLECTION, doc_id, {k: v for k, v in acc.items()})
    acc["doc_id"] = doc_id
    return acc


async def _refresh_yahoo_token(ctx: Context, acc: dict) -> dict:
    client_id     = await ctx.secrets.get("yahoo_client_id")
    client_secret = await ctx.secrets.get("yahoo_client_secret")
    if not client_id or not client_secret:
        log.warning("Yahoo OAuth credentials not set in secrets — cannot refresh token")
        return acc
    creds = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
    resp  = await ctx.http.post(YAHOO_TOKEN_URL,
        data={"grant_type": "refresh_token", "refresh_token": acc["refresh_token"]},
        headers={"Authorization": f"Basic {creds}"},
    )
    if resp.status_code != 200:
        return await _handle_oauth_refresh_failure(
            ctx, acc, resp, provider="yahoo", label="Yahoo",
        )
    tokens = resp.json()
    acc["access_token"] = tokens["access_token"]
    acc["expires_at"]   = int(time.time()) + tokens.get("expires_in", 3600)
    if "refresh_token" in tokens: acc["refresh_token"] = tokens["refresh_token"]
    doc_id = acc.pop("doc_id")
    await ctx.store.update(COLLECTION, doc_id, {k: v for k, v in acc.items()})
    acc["doc_id"] = doc_id
    return acc


async def _refresh_token_if_needed(ctx: Context, acc: dict) -> dict:
    if acc.get("expires_at", 0) > time.time() + 120:
        return acc
    p = acc.get("provider", "oauth")
    if p == "yahoo":
        return await _refresh_yahoo_token(ctx, acc)
    if _is_microsoft_account(acc):
        return await _refresh_microsoft_token(ctx, acc)
    return await _refresh_google_token(ctx, acc)
