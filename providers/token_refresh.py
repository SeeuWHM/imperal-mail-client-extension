"""Token refresh and OAuth HTTP helpers for all mail providers."""
from __future__ import annotations

import base64
import logging
import os
import time

from imperal_sdk import Context

from .helpers import (
    COLLECTION,
    GOOGLE_TOKEN_URL, GMAIL_API,
    MS_TOKEN_URL, MS_SCOPE, MS_GRAPH_BASE,
    YAHOO_TOKEN_URL,
)

log = logging.getLogger(__name__)


async def _api_get(ctx: Context, path: str, acc: dict, **kwargs):
    acc = await _refresh_token_if_needed(ctx, acc)
    return await ctx.http.get(
        f"{GMAIL_API}/{path}",
        headers={"Authorization": f"Bearer {acc['access_token']}"},
        **kwargs,
    )


async def _api_post(ctx: Context, path: str, acc: dict, **kwargs):
    acc = await _refresh_token_if_needed(ctx, acc)
    return await ctx.http.post(
        f"{GMAIL_API}/{path}",
        headers={"Authorization": f"Bearer {acc['access_token']}"},
        **kwargs,
    )


async def _graph_get(ctx: Context, path: str, acc: dict, **kwargs):
    acc = await _refresh_token_if_needed(ctx, acc)
    return await ctx.http.get(
        f"{MS_GRAPH_BASE}{path}",
        headers={"Authorization": f"Bearer {acc['access_token']}"},
        **kwargs,
    )


async def _graph_post(ctx: Context, path: str, acc: dict, **kwargs):
    acc = await _refresh_token_if_needed(ctx, acc)
    return await ctx.http.post(
        f"{MS_GRAPH_BASE}{path}",
        headers={"Authorization": f"Bearer {acc['access_token']}"},
        **kwargs,
    )


async def _graph_patch(ctx: Context, path: str, acc: dict, **kwargs):
    acc = await _refresh_token_if_needed(ctx, acc)
    return await ctx.http.patch(
        f"{MS_GRAPH_BASE}{path}",
        headers={"Authorization": f"Bearer {acc['access_token']}"},
        **kwargs,
    )


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
        log.warning(f"Google token refresh failed: {resp.status_code}")
        return acc
    tokens = resp.json()
    acc["access_token"] = tokens["access_token"]
    acc["expires_at"]   = int(time.time()) + tokens.get("expires_in", 3600)
    doc_id = acc.pop("doc_id")
    await ctx.store.update(COLLECTION, doc_id, {k: v for k, v in acc.items()})
    acc["doc_id"] = doc_id
    return acc


async def _refresh_microsoft_token(ctx: Context, acc: dict) -> dict:
    client_id     = await ctx.secrets.get("microsoft_client_id") or os.getenv("MICROSOFT_CLIENT_ID", "")
    client_secret = await ctx.secrets.get("microsoft_client_secret") or os.getenv("MICROSOFT_CLIENT_SECRET", "")
    if not client_id or not client_secret:
        log.warning("Microsoft OAuth credentials not set in secrets — cannot refresh token")
        return acc
    resp = await ctx.http.post(MS_TOKEN_URL, data={
        "grant_type": "refresh_token", "client_id": client_id,
        "client_secret": client_secret, "refresh_token": acc["refresh_token"],
        "scope": MS_SCOPE,
    })
    if resp.status_code != 200:
        try:
            err_body = resp.json()
        except Exception:
            err_body = resp.text[:200] if hasattr(resp, 'text') else "unknown"
        log.warning(f"Microsoft token refresh failed: {resp.status_code} — {err_body}")
        if resp.status_code == 400:
            acc["_needs_reauth"] = True
            doc_id = acc.get("doc_id")
            if doc_id:
                try:
                    await ctx.store.update(COLLECTION, doc_id, {"_needs_reauth": True})
                except Exception:
                    pass
        return acc
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
    client_id     = await ctx.secrets.get("yahoo_client_id") or os.getenv("YAHOO_CLIENT_ID", "")
    client_secret = await ctx.secrets.get("yahoo_client_secret") or os.getenv("YAHOO_CLIENT_SECRET", "")
    if not client_id or not client_secret:
        log.warning("Yahoo OAuth credentials not set in secrets — cannot refresh token")
        return acc
    creds = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
    resp  = await ctx.http.post(YAHOO_TOKEN_URL,
        data={"grant_type": "refresh_token", "refresh_token": acc["refresh_token"]},
        headers={"Authorization": f"Basic {creds}"},
    )
    if resp.status_code != 200:
        log.warning(f"Yahoo token refresh failed: {resp.status_code}"); return acc
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
    if p == "oauth":      return await _refresh_google_token(ctx, acc)
    if p == "microsoft":  return await _refresh_microsoft_token(ctx, acc)
    if p == "yahoo":      return await _refresh_yahoo_token(ctx, acc)
    return acc
