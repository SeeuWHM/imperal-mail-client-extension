"""Mail Client · Automation rule runner — @ext.schedule fan-out (SDK 5.2.0).

Runs every 5 minutes in system context.
Fan-out pattern per SDK docs: ctx.store.list_users() → ctx.as_user(uid) per user.
Executes forwarding and auto-reply rules for all users.
"""
from __future__ import annotations

import datetime
import logging

from app import ext
from providers import get_provider
from providers.helpers import _all_accounts, _refresh_token_if_needed

RULES_COLLECTION = "mail_rules"
REPLIED_COLLECTION = "mail_autoreply_sent"

log = logging.getLogger("mail")


# ─── Schedule ─────────────────────────────────────────────────────────────────

@ext.schedule("mail_rule_runner", cron="*/5 * * * *")
async def run_mail_rules(ctx) -> None:
    """Fan-out across all users with mail rules, execute matching rules."""
    executed = 0
    async for user_id in ctx.store.list_users(RULES_COLLECTION):
        user_ctx = ctx.as_user(user_id)
        try:
            executed += await _process_user_rules(user_ctx)
        except Exception as exc:
            log.warning(f"mail_rules: user {user_id} failed: {exc}")
    if executed:
        log.info(f"mail_rules: executed {executed} rule action(s)")


# ─── Per-user processing ──────────────────────────────────────────────────────

async def _process_user_rules(ctx) -> int:
    """Process all enabled rules for one user. Returns count of actions taken."""
    rules_page = await ctx.store.query(RULES_COLLECTION,
                                       where={"owner_id": ctx.user.imperal_id,
                                              "enabled": True},
                                       limit=20)
    if not rules_page.data:
        return 0

    accounts = await _all_accounts(ctx)
    if not accounts:
        return 0

    executed = 0
    for rule in rules_page.data:
        try:
            executed += await _run_rule(ctx, rule, accounts)
        except Exception as exc:
            log.warning(f"mail_rules: rule {rule.id} ({rule.data.get('name')}) error: {exc}")
    return executed


async def _run_rule(ctx, rule, accounts: list) -> int:
    """Execute one rule against all accounts. Returns count of actions taken."""
    rule_type = rule.data.get("rule_type")
    last_run = rule.data.get("last_run_at")
    now = datetime.datetime.now(datetime.timezone.utc)
    now_str = now.isoformat()

    if rule_type == "autoreply" and not _is_autoreply_active(rule.data, now):
        return 0

    executed = 0
    for acc_raw in accounts:
        try:
            acc = await _refresh_token_if_needed(ctx, acc_raw)
            provider = get_provider(acc)
            messages, _, _ = await provider.fetch_page(ctx, acc, "INBOX", 20, None)

            for msg in messages:
                msg_id = msg.get("id") or msg.get("message_id") or ""
                msg_date_str = msg.get("date") or msg.get("received_at") or ""
                if not msg_id:
                    continue
                if last_run and msg_date_str and msg_date_str < last_run:
                    continue
                if not _matches_criteria(msg, rule.data):
                    continue

                if rule_type == "forward":
                    await _do_forward(ctx, acc, provider, msg_id, rule.data)
                    executed += 1
                elif rule_type == "autoreply":
                    sent = await _do_autoreply(ctx, acc, provider, msg, rule)
                    if sent:
                        executed += 1
        except Exception as exc:
            log.debug(f"mail_rules: account {acc_raw.get('email')} error: {exc}")

    if executed:
        await ctx.store.update(RULES_COLLECTION, rule.id,
                               {**rule.data, "last_run_at": now_str})
    return executed


def _matches_criteria(msg: dict, rule_data: dict) -> bool:
    """Check if an email matches the rule's criteria."""
    from_filter = (rule_data.get("criteria_from") or "").lower()
    subj_filter = (rule_data.get("criteria_subject") or "").lower()
    sender = (msg.get("from") or "").lower()
    subject = (msg.get("subject") or "").lower()
    if from_filter and from_filter not in sender:
        return False
    if subj_filter and subj_filter not in subject:
        return False
    return True


def _is_autoreply_active(rule_data: dict, now: datetime.datetime) -> bool:
    """Return True if autoreply should fire NOW (outside business hours for time_window)."""
    if rule_data.get("schedule_type") == "always":
        return True
    try:
        import zoneinfo
        tz = zoneinfo.ZoneInfo(rule_data.get("timezone") or "UTC")
    except Exception:
        tz = datetime.timezone.utc
    local = now.astimezone(tz)
    days = rule_data.get("schedule_days") or [0, 1, 2, 3, 4]
    start_str = rule_data.get("schedule_start") or "09:00"
    end_str = rule_data.get("schedule_end") or "18:00"
    try:
        sh, sm = map(int, start_str.split(":"))
        eh, em = map(int, end_str.split(":"))
    except Exception:
        return True
    in_business_day = local.weekday() in days
    start_t = datetime.time(sh, sm)
    end_t = datetime.time(eh, em)
    in_hours = start_t <= local.time() < end_t
    # Autoreply fires OUTSIDE business hours
    return not (in_business_day and in_hours)


async def _do_forward(ctx, acc: dict, provider, message_id: str, rule_data: dict) -> None:
    """Forward a single message per the rule."""
    to = rule_data.get("forward_to", "")
    comment = rule_data.get("comment", "")
    if not to:
        return
    result = await provider.forward(ctx, acc, message_id=message_id, to=to, comment=comment)
    if result.get("RESULT") == "ERROR":
        log.warning(f"mail_rules forward failed: {result.get('error')}")


async def _do_autoreply(ctx, acc: dict, provider, msg: dict, rule) -> bool:
    """Send auto-reply if not already replied. Returns True if sent."""
    msg_id = msg.get("id") or msg.get("message_id") or ""
    sender = msg.get("from") or ""
    if not msg_id or not sender:
        return False

    # Check dedup — skip if already replied to this message
    existing = await ctx.store.query(REPLIED_COLLECTION,
                                     where={"message_id": msg_id, "rule_id": rule.id},
                                     limit=1)
    if existing.data:
        return False

    # Don't reply to auto-generated emails (avoid loops)
    subj = (msg.get("subject") or "").lower()
    auto_markers = ["auto:", "automatic", "noreply", "no-reply", "mailer-daemon", "postmaster"]
    if any(m in subj or m in sender.lower() for m in auto_markers):
        return False

    template = rule.data.get("reply_template", "")
    prefix = rule.data.get("subject_prefix") or "Auto: "
    if not template:
        return False

    result = await provider.reply(ctx, acc, message_id=msg_id, body=template, to="", cc="", bcc="")
    if result.get("RESULT") == "ERROR":
        log.warning(f"mail_rules autoreply failed: {result.get('error')}")
        return False

    await ctx.store.create(REPLIED_COLLECTION, {
        "owner_id": ctx.user.imperal_id,
        "message_id": msg_id,
        "rule_id": rule.id,
        "replied_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    })
    return True
