"""Mail Client · Event-driven rule processor (SDK 5.2.0).

Called from app.on_email_received which fires on every incoming email.
The email.received event is confirmed active in prod logs.
This is the primary rule execution path — real-time, no polling needed.
@ext.schedule (*/5 * * * *) stays as backup.
"""
from __future__ import annotations

import datetime
import logging

from providers import get_provider
from providers.helpers import _all_accounts, _refresh_token_if_needed
from handlers_rule_runner import (
    RULES_COLLECTION,
    _process_user_rules,
    _is_autoreply_active,
    _matches_criteria,
    _do_forward,
    _do_autoreply,
)

log = logging.getLogger("mail")


async def process_event_email(ctx, event: dict) -> int:
    """Apply all enabled rules to the email that just arrived.

    ctx is already user-scoped (from on_email_received).
    Uses event payload (message_id, from, subject) directly — no extra inbox API call.
    Falls back to _process_user_rules (fetches inbox) if event has no message_id.
    """
    uid = ctx.user.imperal_id if hasattr(ctx, "user") and ctx.user else ""
    rules_page = await ctx.store.query(RULES_COLLECTION,
                                       where={"owner_id": uid, "enabled": True},
                                       limit=20)
    if not rules_page.data:
        return 0

    # Build message dict from event — normalise all known key names
    msg = {
        "id":         event.get("message_id") or event.get("id") or "",
        "message_id": event.get("message_id") or event.get("id") or "",
        "from":       event.get("from") or event.get("sender") or event.get("from_email") or "",
        "subject":    event.get("subject") or "",
        "date":       event.get("date") or event.get("received_at") or "",
    }

    if not msg["id"]:
        # Event payload has no usable message ID — fall back to inbox polling
        log.debug("mail event: no message_id in event, falling back to poll")
        return await _process_user_rules(ctx)

    accounts = await _all_accounts(ctx)
    if not accounts:
        return 0

    acc_raw = next((a for a in accounts if a.get("is_active")), accounts[0])
    acc = await _refresh_token_if_needed(ctx, acc_raw)
    provider = get_provider(acc)

    executed = 0
    now = datetime.datetime.now(datetime.timezone.utc)
    now_str = now.isoformat()

    for rule in rules_page.data:
        try:
            rule_type = rule.data.get("rule_type")
            if rule_type == "autoreply" and not _is_autoreply_active(rule.data, now):
                continue
            if not _matches_criteria(msg, rule.data):
                continue
            if rule_type == "forward":
                ok = await _do_forward(ctx, acc, provider, msg["id"], rule.data)
                if ok:
                    executed += 1
            elif rule_type == "autoreply":
                sent = await _do_autoreply(ctx, acc, provider, msg, rule)
                if sent:
                    executed += 1
            # Update last_run_at so schedule-based backup doesn't re-process
            await ctx.store.update(RULES_COLLECTION, rule.id,
                                   {**rule.data, "last_run_at": now_str})
        except Exception as exc:
            log.warning(f"mail event: rule {rule.id} ({rule.data.get('name')}) error: {exc}")

    return executed
