"""Mail Client — Google OAuth webhook callback + schedule processor.

SDK-correct flow per EXT-SECRETS-V1 and @ext.webhook docs:
  1. connect()     — builds OAuth URL; redirect_uri = ctx.webhook_url("callback")
  2. Webhook       — receives code, stores raw {user_id, code} in __webhook__ store
  3. Schedule      — reads __webhook__ store via ctx.as_user("__webhook__");
                     exchanges code in real user context (secrets accessible);
                     writes account to user's ctx.store.
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


def _decode_state(state_raw: str) -> dict:
    try:
        pad = state_raw + "=" * (4 - len(state_raw) % 4)
        return _json.loads(base64.urlsafe_b64decode(pad).decode())
    except Exception:
        return {}


# ── Webhook — stores raw code for schedule to process ────────────────────────

@ext.webhook("callback", method="GET")
async def google_oauth_callback(
    ctx, headers: dict, body: str, query_params: dict
) -> dict:
    """Receive Google OAuth redirect and store the authorization code."""
    error = query_params.get("error", "")
    if error:
        log.warning(f"google_oauth: provider error: {error}")
        return {"status_code": 400,
                "body": f"Authorization failed: {error}. Return to Webbee."}

    code      = query_params.get("code", "")
    state_raw = query_params.get("state", "")

    if not code or not state_raw:
        return {"status_code": 400, "body": "Missing code or state."}

    state    = _decode_state(state_raw)
    user_id  = state.get("user_id", "")
    provider = state.get("provider", "")

    if not user_id or provider != "oauth":
        return {"status_code": 400, "body": "Invalid state."}

    # Store code in __webhook__ store — schedule reads this via ctx.as_user("__webhook__")
    await ctx.store.create(_PENDING, {
        "user_id":      user_id,
        "provider":     "oauth",
        "code":         code,
        "redirect_uri": ctx.webhook_url("callback"),
        "received_at":  int(time.time()),
    })

    log.info(f"google_oauth: code stored for user_id={user_id}")
    return {"status_code": 200,
            "body": "Google account authorized! Return to Webbee — account will appear within a minute."}


# ── Schedule — exchanges code in user context, writes account ─────────────────

@ext.schedule("process_google_pending", cron="* * * * *")
async def process_google_pending(ctx) -> None:
    """Exchange pending Google OAuth codes and create accounts in user context."""

    # Read records from __webhook__ store directly (schedule has __system__ context)
    webhook_ctx = ctx.as_user("__webhook__")
    page = await webhook_ctx.store.query(_PENDING)

    if not page or not page.data:
        return

    for rec in page.data:
        # Filter: only Google OAuth pending
        if rec.get("provider") != "oauth":
            continue

        actual_user_id = rec.get("user_id", "")
        code           = rec.get("code", "")
        redirect_uri   = rec.get("redirect_uri", "")
        rec_id         = rec.id

        if not actual_user_id or not code:
            await webhook_ctx.store.delete(_PENDING, rec_id)
            continue

        # Expire stale records — OAuth code is only valid ~10 minutes
        received_at = rec.get("received_at", 0)
        if int(time.time()) - received_at > 600:
            log.warning(f"google_pending: record expired for user={actual_user_id}, deleting")
            await webhook_ctx.store.delete(_PENDING, rec_id)
            continue

        # App-scope secrets readable from any ctx — no need to switch to user context for credentials
        client_id     = await ctx.secrets.get("google_client_id")
        client_secret = await ctx.secrets.get("google_client_secret")

        if not client_id or not client_secret:
            log.warning("google_pending: google_client_id/secret not configured in Dev Portal Secrets")
            await webhook_ctx.store.delete(_PENDING, rec_id)
            continue

        # Switch to real user context for store operations
        user_ctx = ctx.as_user(actual_user_id)

        # Exchange authorization code for tokens (permanent failure — delete on any non-200)
        resp = await ctx.http.post(GOOGLE_TOKEN_URL, data={
            "code":          code,
            "client_id":     client_id,
            "client_secret": client_secret,
            "redirect_uri":  redirect_uri,
            "grant_type":    "authorization_code",
        })

        if resp.status_code != 200:
            log.warning(f"google_pending: token exchange failed HTTP {resp.status_code} for user={actual_user_id}")
            await webhook_ctx.store.delete(_PENDING, rec_id)
            continue

        tokens        = resp.json()
        access_token  = tokens.get("access_token", "")
        refresh_token = tokens.get("refresh_token", "")
        expires_in    = tokens.get("expires_in", 3600)

        if not access_token:
            log.warning(f"google_pending: no access_token in response for user={actual_user_id}")
            await webhook_ctx.store.delete(_PENDING, rec_id)
            continue

        # Fetch email via Gmail profile API — uses existing gmail.modify scope, no re-consent needed
        profile_resp = await ctx.http.get(
            "https://gmail.googleapis.com/gmail/v1/users/me/profile",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        if profile_resp.status_code != 200:
            # Transient failure (5xx / rate-limit) — keep record, retry next cron run
            log.warning(
                f"google_pending: profile fetch HTTP {profile_resp.status_code} "
                f"for user={actual_user_id} — will retry next run"
            )
            continue

        email = profile_resp.json().get("emailAddress", "")
        if not email:
            log.warning(f"google_pending: empty emailAddress in profile for user={actual_user_id}")
            await webhook_ctx.store.delete(_PENDING, rec_id)
            continue

        expires_at = int(time.time()) + expires_in

        # Write account to user's store
        existing = await user_ctx.store.query(
            COLLECTION, where={"email": email, "provider": "oauth"}
        )
        if existing and existing.data:
            acc = existing.data[0]
            await user_ctx.store.update(COLLECTION, acc.id, {
                **acc.data,
                "access_token":  access_token,
                "refresh_token": refresh_token,
                "expires_at":    expires_at,
                "is_active":     True,
            })
        else:
            all_accs = await user_ctx.store.query(COLLECTION)
            for a in (all_accs.data or []):
                if a.get("is_active"):
                    await user_ctx.store.update(COLLECTION, a.id, {**a.data, "is_active": False})
            await user_ctx.store.create(COLLECTION, {
                "email":         email,
                "provider":      "oauth",
                "is_active":     True,
                "access_token":  access_token,
                "refresh_token": refresh_token,
                "expires_at":    expires_at,
            })

        # Clean up pending record
        await webhook_ctx.store.delete(_PENDING, rec_id)
        log.info(f"google_pending: account {email} created for user={actual_user_id}")
