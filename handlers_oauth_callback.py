"""Mail Client — Google OAuth webhook callback.

Flow:
  1. connect()         — builds OAuth URL; stores {nonce, status="waiting"} in user's store
  2. Google redirects  — @ext.webhook("callback") receives code + state
  3. Webhook           — exchanges code immediately (secrets available app-wide via portal);
                         writes account to user's store via ctx.as_user(user_id)
  4. Schedule fallback — if ctx.as_user() unavailable in webhook, schedule picks up via
                         list_users("google_oauth_pending") scanning real users' records
"""
from __future__ import annotations

import base64
import json as _json
import logging
import time

from imperal_sdk.chat.action_result import ActionResult

from app import ext, chat
from schemas import EmptyParams
from providers.helpers import GOOGLE_TOKEN_URL, COLLECTION

log = logging.getLogger("mail")

_PENDING = "google_oauth_pending"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _decode_state(state_raw: str) -> dict:
    try:
        pad = state_raw + "=" * (4 - len(state_raw) % 4)
        return _json.loads(base64.urlsafe_b64decode(pad).decode())
    except Exception:
        return {}


async def _write_account(store_ctx, email: str, access_token: str,
                         refresh_token: str, expires_at: int) -> None:
    """Create or update Google account record in ctx.store."""
    existing = await store_ctx.store.query(
        COLLECTION, where={"email": email, "provider": "oauth"}
    )
    if existing and existing.data:
        acc_rec = existing.data[0]
        await store_ctx.store.update(COLLECTION, acc_rec.id, {
            **acc_rec.data,
            "access_token":  access_token,
            "refresh_token": refresh_token,
            "expires_at":    expires_at,
            "is_active":     True,
        })
    else:
        all_accs = await store_ctx.store.query(COLLECTION)
        for acc in (all_accs.data or []):
            if acc.get("is_active"):
                await store_ctx.store.update(
                    COLLECTION, acc.id, {**acc.data, "is_active": False}
                )
        await store_ctx.store.create(COLLECTION, {
            "email":         email,
            "provider":      "oauth",
            "is_active":     True,
            "access_token":  access_token,
            "refresh_token": refresh_token,
            "expires_at":    expires_at,
        })


# ── Webhook ───────────────────────────────────────────────────────────────────

@ext.webhook("callback", method="GET")
async def google_oauth_callback(
    ctx, headers: dict, body: str, query_params: dict
) -> dict:
    """Receive Google OAuth redirect, exchange code, write account."""
    error = query_params.get("error", "")
    if error:
        return {"status_code": 400,
                "body": f"Google authorization failed: {error}. Return to Webbee and try again."}

    code      = query_params.get("code", "")
    state_raw = query_params.get("state", "")
    if not code or not state_raw:
        return {"status_code": 400, "body": "Missing code or state."}

    state    = _decode_state(state_raw)
    user_id  = state.get("user_id", "")
    provider = state.get("provider", "")

    if not user_id or provider != "oauth":
        return {"status_code": 400, "body": "Invalid state."}

    redirect_uri = ctx.webhook_url("callback")

    # Read app credentials — available because Developer Portal sets them app-wide
    client_id     = await ctx.secrets.get("google_client_id")
    client_secret = await ctx.secrets.get("google_client_secret")

    if not client_id or not client_secret:
        # Credentials unavailable in webhook context — store raw code for schedule
        log.warning("google_oauth: secrets not available in webhook context, storing pending")
        await ctx.store.create(_PENDING, {
            "user_id":      user_id,
            "provider":     "oauth",
            "code":         code,
            "redirect_uri": redirect_uri,
            "received_at":  int(time.time()),
        })
        return {"status_code": 200,
                "body": "Authorized! Return to Webbee — account will appear within a minute."}

    # Exchange code for tokens
    resp = await ctx.http.post(GOOGLE_TOKEN_URL, data={
        "code":          code,
        "client_id":     client_id,
        "client_secret": client_secret,
        "redirect_uri":  redirect_uri,
        "grant_type":    "authorization_code",
    })
    if resp.status_code != 200:
        log.warning(f"google_oauth: token exchange failed {resp.status_code}")
        return {"status_code": 502, "body": "Token exchange failed. Try again."}

    tokens        = resp.json()
    access_token  = tokens.get("access_token", "")
    refresh_token = tokens.get("refresh_token", "")
    expires_in    = tokens.get("expires_in", 3600)
    if not access_token:
        return {"status_code": 502, "body": "No access token returned."}

    # Fetch email
    info = await ctx.http.get(
        "https://www.googleapis.com/oauth2/v1/userinfo",
        headers={"Authorization": f"Bearer {access_token}"},
    )
    email = info.json().get("email", "") if info.status_code == 200 else ""
    if not email:
        return {"status_code": 502, "body": "Could not fetch email from Google."}

    expires_at = int(time.time()) + expires_in

    # Try to write directly to user's store via ctx.as_user()
    try:
        user_ctx = ctx.as_user(user_id)
        await _write_account(user_ctx, email, access_token, refresh_token, expires_at)
        log.info(f"google_oauth: account {email} written directly for user={user_id}")
        return {"status_code": 200,
                "body": "Google account connected! Return to Webbee."}
    except Exception as e:
        log.info(f"google_oauth: ctx.as_user() not available in webhook ({e}), storing result")

    # Fallback: store exchange result for schedule or connect_complete
    await ctx.store.create(_PENDING, {
        "user_id":       user_id,
        "provider":      "oauth",
        "email":         email,
        "access_token":  access_token,
        "refresh_token": refresh_token,
        "expires_at":    expires_at,
        "exchanged":     True,
    })
    return {"status_code": 200,
            "body": "Authorized! Return to Webbee — account will appear within a minute."}


# ── Schedule fallback ─────────────────────────────────────────────────────────

@ext.schedule("process_google_pending", cron="* * * * *")
async def process_google_pending(ctx) -> None:
    """Fallback: process pending Google OAuth records that webhook couldn't write directly."""
    # Scan users who have a pending record in THEIR OWN store
    async for uid in ctx.store.list_users(_PENDING):
        uid_ctx = ctx.as_user(uid)
        page    = await uid_ctx.store.query(_PENDING, where={"provider": "oauth"})
        if not page or not page.data:
            continue

        for rec in page.data:
            actual_user_id = rec.get("user_id", uid)
            email          = rec.get("email", "")
            rec_id         = rec.id

            if rec.get("exchanged") and email:
                # Already exchanged in webhook — just write the account
                user_ctx = ctx.as_user(actual_user_id)
                await _write_account(
                    user_ctx, email,
                    rec.get("access_token", ""),
                    rec.get("refresh_token", ""),
                    rec.get("expires_at", 0),
                )
                await uid_ctx.store.delete(_PENDING, rec_id)
                log.info(f"google_pending: wrote account {email} for user={actual_user_id}")

            else:
                # Raw code — exchange using user's secrets
                code         = rec.get("code", "")
                redirect_uri = rec.get("redirect_uri", "")
                if not code:
                    await uid_ctx.store.delete(_PENDING, rec_id)
                    continue

                user_ctx      = ctx.as_user(actual_user_id)
                client_id     = await user_ctx.secrets.get("google_client_id")
                client_secret = await user_ctx.secrets.get("google_client_secret")
                if not client_id or not client_secret:
                    log.warning(f"google_pending: no credentials for user={actual_user_id}")
                    await uid_ctx.store.delete(_PENDING, rec_id)
                    continue

                resp = await user_ctx.http.post(GOOGLE_TOKEN_URL, data={
                    "code":          code,
                    "client_id":     client_id,
                    "client_secret": client_secret,
                    "redirect_uri":  redirect_uri,
                    "grant_type":    "authorization_code",
                })
                if resp.status_code != 200:
                    log.warning(f"google_pending: exchange failed {resp.status_code}")
                    await uid_ctx.store.delete(_PENDING, rec_id)
                    continue

                tokens = resp.json()
                at = tokens.get("access_token", "")
                rt = tokens.get("refresh_token", "")
                ea = int(time.time()) + tokens.get("expires_in", 3600)

                info = await user_ctx.http.get(
                    "https://www.googleapis.com/oauth2/v1/userinfo",
                    headers={"Authorization": f"Bearer {at}"},
                )
                em = info.json().get("email", "") if info.status_code == 200 else ""
                if em:
                    await _write_account(user_ctx, em, at, rt, ea)
                    log.info(f"google_pending: account {em} for user={actual_user_id}")
                await uid_ctx.store.delete(_PENDING, rec_id)
