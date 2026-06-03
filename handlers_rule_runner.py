"""Mail Client · Automation rule runner — @ext.schedule fan-out (SDK 5.2.0).

Runs every 5 minutes in system context.
Fan-out pattern per SDK docs: ctx.store.list_users() → ctx.as_user(uid) per user.
Executes forwarding and auto-reply rules for all users.
"""
from __future__ import annotations

import datetime
import logging
import re

from app import ext
from providers import get_provider
from providers.helpers import _all_accounts, _refresh_token_if_needed

RULES_COLLECTION = "mail_rules"
REPLIED_COLLECTION = "mail_autoreply_sent"

log = logging.getLogger("mail")

_EMAIL_RE = re.compile(r'<([^>]+)>')


def _extract_email(addr: str) -> str:
    """Extract bare email address from 'Name <email>' or plain 'email'."""
    m = _EMAIL_RE.search(addr)
    return m.group(1).strip().lower() if m else addr.strip().lower()


def _parse_date(date_str: str) -> datetime.datetime | None:
    """Parse RFC2822 or ISO datetime string → UTC datetime. Returns None on failure."""
    if not date_str:
        return None
    # ISO format (our own timestamps)
    try:
        dt = datetime.datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        return dt.astimezone(datetime.timezone.utc)
    except (ValueError, AttributeError):
        pass
    # RFC2822 (provider message dates)
    try:
        from email.utils import parsedate_to_datetime
        return parsedate_to_datetime(date_str).astimezone(datetime.timezone.utc)
    except Exception:
        return None


# ─── Schedule ─────────────────────────────────────────────────────────────────

@ext.schedule("mail_rule_runner", cron="*/5 * * * *")
async def run_mail_rules(ctx) -> None:
    """Fan-out across all users with mail rules, execute matching rules."""
    executed = 0
    try:
        async for user_id in ctx.store.list_users(RULES_COLLECTION):
            user_ctx = ctx.as_user(user_id)
            try:
                executed += await _process_user_rules(user_ctx)
            except Exception as exc:
                log.warning(f"mail_rules: user {user_id} failed: {exc}")
    except Exception as exc:
        log.error(f"mail_rules: schedule run failed: {exc}")
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
    last_run_str = rule.data.get("last_run_at")
    now = datetime.datetime.now(datetime.timezone.utc)
    now_str = now.isoformat()

    if rule_type == "autoreply" and not _is_autoreply_active(rule.data, now):
        return 0

    # Parse last_run properly — avoids RFC2822 vs ISO string comparison bug
    last_run_dt = _parse_date(last_run_str) if last_run_str else None

    executed = 0
    for acc_raw in accounts:
        try:
            acc = await _refresh_token_if_needed(ctx, acc_raw)
            provider = get_provider(acc)
            messages, _, _ = await provider.fetch_page(ctx, acc, "INBOX", 30, None)

            for msg in messages:
                msg_id = msg.get("id") or msg.get("message_id") or ""
                if not msg_id:
                    continue

                # Compare as datetime objects — avoids RFC2822 vs ISO string comparison bug
                if last_run_dt:
                    msg_date = _parse_date(msg.get("date") or msg.get("received_at") or "")
                    if msg_date and msg_date <= last_run_dt:
                        continue  # email predates last run, skip

                if not _matches_criteria(msg, rule.data):
                    continue

                if rule_type == "forward":
                    ok = await _do_forward(ctx, acc, provider, msg_id, rule.data)
                    if ok:
                        executed += 1
                elif rule_type == "autoreply":
                    sent = await _do_autoreply(ctx, acc, provider, msg, rule)
                    if sent:
                        executed += 1
        except Exception as exc:
            log.warning(f"mail_rules: account {acc_raw.get('email')} error: {exc}")

    # Always update last_run_at so next iteration only processes new emails
    try:
        await ctx.store.update(RULES_COLLECTION, rule.id,
                               {**rule.data, "last_run_at": now_str})
    except Exception as exc:
        log.debug(f"mail_rules: last_run_at update failed for {rule.id}: {exc}")

    return executed


def _matches_criteria(msg: dict, rule_data: dict) -> bool:
    """Check if an email matches the rule's criteria (case-insensitive substring match)."""
    from_filter = (rule_data.get("criteria_from") or "").strip().lower()
    subj_filter = (rule_data.get("criteria_subject") or "").strip().lower()
    sender = (msg.get("from") or "").lower()
    subject = (msg.get("subject") or "").lower()
    if from_filter and from_filter not in sender:
        return False
    if subj_filter and subj_filter not in subject:
        return False
    return True


def _is_autoreply_active(rule_data: dict, now: datetime.datetime) -> bool:
    """Return True if autoreply should fire NOW.

    'always': fires any time.
    'time_window': fires OUTSIDE business hours on specified days.
    """
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
    in_hours = datetime.time(sh, sm) <= local.time() < datetime.time(eh, em)
    return not (in_business_day and in_hours)


async def _do_forward(ctx, acc: dict, provider, message_id: str, rule_data: dict) -> bool:
    """Forward a single message per the rule. Returns True on success."""
    to = (rule_data.get("forward_to") or "").strip()
    if not to:
        log.warning("mail_rules forward: no forward_to address in rule")
        return False
    comment = rule_data.get("comment") or ""
    try:
        result = await provider.forward(ctx, acc, message_id=message_id, to=to, comment=comment)
        if result.get("RESULT") == "ERROR":
            log.warning(f"mail_rules forward failed: {result.get('error')}")
            return False
        log.info(f"mail_rules forwarded {message_id[:16]} to {to}")
        return True
    except Exception as exc:
        log.warning(f"mail_rules forward exception: {exc}")
        return False


async def _do_autoreply(ctx, acc: dict, provider, msg: dict, rule) -> bool:
    """Send auto-reply if not already replied. Returns True if sent.

    Uses provider.send() (not reply()) for reliability — reply() requires
    reading thread headers; send() with explicit To is always safe.
    """
    msg_id = msg.get("id") or msg.get("message_id") or ""
    raw_sender = msg.get("from") or ""
    if not msg_id or not raw_sender:
        return False

    to_addr = _extract_email(raw_sender)
    if not to_addr or "@" not in to_addr:
        return False

    # Dedup — never reply twice to the same message with the same rule
    try:
        existing = await ctx.store.query(REPLIED_COLLECTION,
                                         where={"message_id": msg_id, "rule_id": rule.id},
                                         limit=1)
        if existing.data:
            return False
    except Exception:
        pass

    # Loop protection — skip auto-generated or no-reply senders
    subj = (msg.get("subject") or "").lower()
    sender_lower = raw_sender.lower()
    auto_markers = ["auto:", "automatic reply", "noreply", "no-reply",
                    "mailer-daemon", "postmaster", "do-not-reply", "donotreply"]
    if any(m in subj or m in sender_lower for m in auto_markers):
        log.debug(f"mail_rules autoreply: skipping auto-generated from {to_addr}")
        return False

    template = (rule.data.get("reply_template") or "").strip()
    prefix = (rule.data.get("subject_prefix") or "Auto: ").strip()
    if not template:
        return False

    orig_subject = msg.get("subject") or ""
    reply_subject = f"{prefix}{orig_subject}"

    try:
        # Use send() for reliability — reply() requires thread info loading
        result = await provider.send(ctx, acc,
                                     to=to_addr,
                                     subject=reply_subject,
                                     body=template)
        if result.get("RESULT") == "ERROR":
            log.warning(f"mail_rules autoreply send failed: {result.get('error')}")
            return False

        await ctx.store.create(REPLIED_COLLECTION, {
            "owner_id": ctx.user.imperal_id,
            "message_id": msg_id,
            "rule_id": rule.id,
            "replied_to": to_addr,
            "replied_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        })
        log.info(f"mail_rules auto-replied to {to_addr} re: {orig_subject[:40]}")
        return True
    except Exception as exc:
        log.warning(f"mail_rules autoreply exception: {exc}")
        return False
