"""Google Mail Provider — filter operations (Gmail settings/filters API).

Implements list_filters, create_filter, delete_filter via Gmail REST API:
GET/POST/DELETE https://gmail.googleapis.com/gmail/v1/users/me/settings/filters
"""
from __future__ import annotations

import logging
from imperal_sdk import Context

from .helpers import _api_get, _api_post, _api_delete
from mail_providers.errors import MailAuthExpiredError

log = logging.getLogger("mail")


class GoogleFilterMixin:
    """Gmail filter management via users.settings.filters API."""

    async def list_filters(self, ctx: Context, acc: dict) -> list[dict]:
        """Fetch native Gmail filters from Gmail settings API."""
        try:
            resp = await _api_get(ctx, "settings/filters", acc)
            if resp.status_code in (403, 404):
                return []
            resp.raise_for_status()
            data = resp.json()
            raw_filters = data.get("filter", []) or []

            normalized = []
            for f in raw_filters:
                fid = f.get("id", "")
                crit = f.get("criteria", {}) or {}
                act = f.get("action", {}) or {}

                parts = []
                if crit.get("from"):
                    parts.append(f"From: {crit['from']}")
                if crit.get("subject"):
                    parts.append(f"Subject: {crit['subject']}")
                if crit.get("query"):
                    parts.append(f"Query: {crit['query']}")
                if crit.get("to"):
                    parts.append(f"To: {crit['to']}")
                name = " | ".join(parts) if parts else f"Gmail Filter {fid[:8]}"

                normalized.append({
                    "id": fid,
                    "name": name,
                    "criteria_from": crit.get("from", ""),
                    "criteria_subject": crit.get("subject", ""),
                    "criteria_query": crit.get("query", ""),
                    "criteria_to": crit.get("to", ""),
                    "action_add_labels": act.get("addLabelIds", []),
                    "action_remove_labels": act.get("removeLabelIds", []),
                    "action_forward": act.get("forward", ""),
                    "is_native": True,
                    "account_email": acc.get("email", ""),
                })
            return normalized
        except MailAuthExpiredError:
            raise
        except Exception as e:
            log.warning("list_filters failed for %s: %s", acc.get("email", "?"), e)
            return []

    async def create_filter(
        self, ctx: Context, acc: dict, criteria: dict, action: dict | None = None
    ) -> dict:
        """Create a native Gmail filter via users.settings.filters.create."""
        try:
            payload = {
                "criteria": criteria,
                "action": action or {},
            }
            resp = await _api_post(ctx, "settings/filters", acc, json=payload)
            if resp.status_code == 403:
                return self.err("Gmail settings scope not granted or denied by Google.")
            if resp.status_code not in (200, 201):
                return self.err(f"Gmail create filter error {resp.status_code}: {resp.text[:200]}")
            data = resp.json()
            return self.ok(
                filter_id=data.get("id", ""),
                criteria=data.get("criteria", {}),
                action=data.get("action", {}),
            )
        except MailAuthExpiredError:
            raise
        except Exception as e:
            return self.err(f"Create filter failed: {e}")

    async def delete_filter(self, ctx: Context, acc: dict, filter_id: str) -> dict:
        """Delete a native Gmail filter via users.settings.filters.delete."""
        try:
            resp = await _api_delete(ctx, f"settings/filters/{filter_id}", acc)
            if resp.status_code == 403:
                return self.err("Gmail settings scope not granted or denied by Google.")
            if resp.status_code not in (200, 204):
                return self.err(f"Gmail delete filter error {resp.status_code}: {resp.text[:200]}")
            return self.ok(deleted=True, filter_id=filter_id)
        except MailAuthExpiredError:
            raise
        except Exception as e:
            return self.err(f"Delete filter failed: {e}")
