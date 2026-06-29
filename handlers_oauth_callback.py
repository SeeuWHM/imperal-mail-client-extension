"""Mail Client — Google OAuth webhook callback + pending token processor.

Flow:
  1. connect()         — builds OAuth URL with ctx.webhook_url("callback") as redirect_uri
  2. Google callback   — @ext.webhook("callback") stores raw {code, user_id} in ctx.store
  3. Schedule (1 min)  — fans out via list_users(), exchanges code in user context
                         (secrets readable), writes account to user's ctx.store, then
                         writes tokens to ctx.secrets("google_tokens").
"""
from __future__ import annotations

import base64
import json as _json
import logging
import time

from app import ext
from providers.helpers import GOOGLE_TOKEN_URL, COLLECTION

log = logging.getLogger("mail")

_PENDING = "google_oauth_pending"


# ── State helpers ─────────────────────────────────────────────────────────────

def _decode_state(state_raw: str) -> dict:
    try:
        pad = state_raw + "=" * (4 - len(state_raw) % 4)
        return _json.loads(base64.urlsafe_b64decode(pad).decode())
    except Exception:
        return {}


# ── Webhook: receive Google's redirect, store raw code ───────────────────────

@ext.webhook("callback", method="GET")
async def google_oauth_callback(
    ctx, headers: dict, body: str, query_params: dict
) -> dict:
    """Receive Google OAuth redirect. Store pending code; exchange happens in schedule."""
    error = query_params.get("error", "")
    if error:
        log.warning(f"Google OAuth error from provider: {error}")
        return {
            "status_code": 400,
            "body": f"Google authorization failed: {error}. Return to Webbee and try again.",
        }

    code      = query_params.get("code", "")
    state_raw = query_params.get("state", "")

    if not code or not state_raw:
        return {"status_code": 400, "body": "Missing code or state. Return to Webbee and try again."}

    state    = _decode_state(state_raw)
    user_id  = state.get("user_id", "")
    provider = state.get("provider", "")

    if not user_id or provider != "oauth":
        log.warning(f"Invalid OAuth state: user_id={user_id!r} provider={provider!r}")
        return {"status_code": 400, "body": "Invalid state parameter. Return to Webbee and try again."}

    # Store the raw authorization code so the schedule can exchange it
    # with full user context (where client_secret is accessible via ctx.secrets).
    await ctx.store.create(_PENDING, {
        "user_id":      user_id,
        "provider":     "oauth",
        "code":         code,
        "redirect_uri": ctx.webhook_url("callback"),
        "received_at":  int(time.time()),
    })

    log.info(f"Google OAuth code stored for user_id={user_id}")
    return {
        "status_code": 200,
        "body": "Google account authorized! Return to Webbee — your account will appear within a minute.",
    }


# ── Schedule: exchange code in user context, write account + tokens ───────────

@ext.schedule("process_google_pending", cron="* * * * *")
async def process_google_pending(ctx) -> None:
    """Fan-out across users who have pending Google OAuth codes, exchange and persist accounts."""
    async for uid in ctx.store.list_users(_PENDING):
        uid_ctx  = ctx.as_user(uid)
        page     = await uid_ctx.store.query(_PENDING, where={"provider": "oauth"})
        if not page or not page.data:
            continue

        for rec in page.data:
            actual_user_id = rec.get("user_id", "")
            code           = rec.get("code", "")
            redirect_uri   = rec.get("redirect_uri", "")
            rec_id         = rec.id

            if not actual_user_id or not code:
                await uid_ctx.store.delete(_PENDING, rec_id)
                continue

            user_ctx = ctx.as_user(actual_user_id)

            client_id     = await user_ctx.secrets.get("google_client_id")
            client_secret = await user_ctx.secrets.get("google_client_secret")
            if not client_id or not client_secret:
                log.warning(f"Google credentials not configured for user={actual_user_id}")
                await uid_ctx.store.delete(_PENDING, rec_id)
                continue

            # Exchange authorization code for tokens
            resp = await user_ctx.http.post(GOOGLE_TOKEN_URL, data={
                "code":          code,
                "client_id":     client_id,
                "client_secret": client_secret,
                "redirect_uri":  redirect_uri,
                "grant_type":    "authorization_code",
            })

            if resp.status_code != 200:
                log.warning(
                    f"Google token exchange failed for user={actual_user_id}: "
                    f"{resp.status_code}"
                )
                await uid_ctx.store.delete(_PENDING, rec_id)
                continue

            tokens        = resp.json()
            access_token  = tokens.get("access_token", "")
            refresh_token = tokens.get("refresh_token", "")
            expires_in    = tokens.get("expires_in", 3600)

            if not access_token:
                log.warning(f"Google returned no access_token for user={actual_user_id}")
                await uid_ctx.store.delete(_PENDING, rec_id)
                continue

            # Fetch the connected account's email address
            info_resp = await user_ctx.http.get(
                "https://www.googleapis.com/oauth2/v1/userinfo",
                headers={"Authorization": f"Bearer {access_token}"},
            )
            if info_resp.status_code != 200:
                log.warning(f"Google userinfo failed for user={actual_user_id}: {info_resp.status_code}")
                await uid_ctx.store.delete(_PENDING, rec_id)
                continue

            email = info_resp.json().get("email", "")
            if not email:
                log.warning(f"Google userinfo returned no email for user={actual_user_id}")
                await uid_ctx.store.delete(_PENDING, rec_id)
                continue

            expires_at = int(time.time()) + expires_in

            # ── Create or update account record in ctx.store (tokens + metadata) ──────
            existing_accs = await user_ctx.store.query(
                COLLECTION, where={"email": email, "provider": "oauth"}
            )
            if existing_accs and existing_accs.data:
                acc_rec = existing_accs.data[0]
                await user_ctx.store.update(COLLECTION, acc_rec.id, {
                    **acc_rec.data,
                    "access_token":  access_token,
                    "refresh_token": refresh_token,
                    "expires_at":    expires_at,
                    "is_active":     True,
                })
            else:
                # Deactivate any currently active account, then create the new one
                all_accs = await user_ctx.store.query(COLLECTION)
                for acc in (all_accs.data or []):
                    if acc.get("is_active"):
                        await user_ctx.store.update(
                            COLLECTION, acc.id, {**acc.data, "is_active": False}
                        )
                await user_ctx.store.create(COLLECTION, {
                    "email":         email,
                    "provider":      "oauth",
                    "is_active":     True,
                    "access_token":  access_token,
                    "refresh_token": refresh_token,
                    "expires_at":    expires_at,
                })

            await uid_ctx.store.delete(_PENDING, rec_id)
            log.info(f"Google OAuth complete: user={actual_user_id} email={email}")
