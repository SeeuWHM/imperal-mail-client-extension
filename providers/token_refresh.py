"""Token refresh and OAuth HTTP helpers for all mail providers."""
from __future__ import annotations

import base64
import logging
import time

from imperal_sdk import Context

from .helpers import (
    COLLECTION,
    GOOGLE_TOKEN_URL, GMAIL_CLIENT_ID, GMAIL_CLIENT_SECRET, GMAIL_API,
    MS_TOKEN_URL, MS_CLIENT_ID, MS_CLIENT_SECRET, MS_SCOPE, MS_GRAPH_BASE,
    YAHOO_CLIENT_ID, YAHOO_CLIENT_SECRET, YAHOO_TOKEN_URL,
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
    resp = await ctx.http.post(GOOGLE_TOKEN_URL, data={
        "client_id": GMAIL_CLIENT_ID, "client_secret": GMAIL_CLIENT_SECRET,
        "refresh_token": acc["refresh_token"], "grant_type": "refresh_token",
    })
    if resp.status_code != 200:
        log.warning(f"Google token refresh failed: {resp.status_code}"); return acc
    tokens = resp.json()
    acc["access_token"] = tokens["access_token"]
    acc["expires_at"]   = int(time.time()) + tokens.get("expires_in", 3600)
    doc_id = acc.pop("doc_id")
    await ctx.store.update(COLLECTION, doc_id, {k: v for k, v in acc.items()})
    acc["doc_id"] = doc_id
    return acc


async def _refresh_microsoft_token(ctx: Context, acc: dict) -> dict:
    resp = await ctx.http.post(MS_TOKEN_URL, data={
        "grant_type": "refresh_token", "client_id": MS_CLIENT_ID,
        "client_secret": MS_CLIENT_SECRET, "refresh_token": acc["refresh_token"],
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
    creds = base64.b64encode(f"{YAHOO_CLIENT_ID}:{YAHOO_CLIENT_SECRET}".encode()).decode()
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
