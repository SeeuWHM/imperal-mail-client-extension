"""Mail Client · Forwarding + auto-reply rules @chat.function handlers (SDK 5.2.0 / SDL).

Rules are stored in ctx.store and executed by the @ext.schedule runner (handlers_rule_runner.py)
every 5 minutes. Auto-reply respects a configurable business-hours schedule.
"""
from __future__ import annotations

import datetime
import logging

from app import chat
from imperal_sdk.chat.action_result import ActionResult
import logging as _logging
from schemas_params import (
    CreateForwardRuleParams, CreateAutoreplyParams,
    RuleIdParam, ToggleRuleParams, EmptyParams,
)

_log = _logging.getLogger("mail")
from schemas_sdl_builders_rules import (
    MailRule, MailRulePage, RuleOpResult,
    build_mail_rule, build_mail_rule_page, build_rule_op,
)

RULES_COLLECTION = "mail_rules"

log = logging.getLogger("mail")


async def _resolve_rule(ctx, rule_id: str) -> tuple:
    """Resolve a rule by store ID or by name. Returns (doc_id, doc_data) or (None, None)."""
    uid = ctx.user.imperal_id
    if rule_id:
        try:
            doc = await ctx.store.get(RULES_COLLECTION, rule_id)
            if doc and doc.data.get("owner_id") == uid:
                return doc.id, doc.data
        except Exception:
            pass
    page = await ctx.store.query(RULES_COLLECTION, where={"owner_id": uid}, limit=20)
    for d in page.data:
        if d.data.get("name", "").lower() == rule_id.lower():
            return d.id, d.data
    return None, None


# ── Forwarding rules ──────────────────────────────────────────────────────────

@chat.function("create_forward_rule", action_type="write", event="rule.created",
               effects=["create:mail_rule"],
               data_model=MailRule,
               description="Create a FORWARDING rule — silently forward matching emails to another address with NO reply sent. Use this when user says 'forward', 'пересылай', 'переслать'. Do NOT create an autoreply rule at the same time unless explicitly asked. Example: 'forward emails from migrations@webhostmost.com to denis@webhostmost.com'.")
async def fn_create_forward_rule(ctx, params: CreateForwardRuleParams) -> ActionResult:
    """Create a forwarding automation rule."""
    try:
        if not params.to_address or "@" not in params.to_address:
            return ActionResult.error("Valid destination email address required.", retryable=False)
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        doc = await ctx.store.create(RULES_COLLECTION, {
            "owner_id": ctx.user.imperal_id,
            "name": params.name.strip()[:60],
            "rule_type": "forward",
            "enabled": True,
            "criteria_from": params.from_contains.strip(),
            "criteria_subject": params.subject_contains.strip(),
            "forward_to": params.to_address.strip().lower(),
            "comment": params.comment.strip(),
            "last_run_at": now,
            "created_at": now,
        })
        return ActionResult.success(
            data=build_mail_rule(doc.id, doc.data),
            summary=f"Forwarding rule '{params.name}' created — runs every 5 min.",
        )
    except Exception as e:
        return ActionResult.error(str(e), retryable=False)


# ── Auto-reply rules ──────────────────────────────────────────────────────────

@chat.function("create_autoreply", action_type="write", event="rule.created",
               effects=["create:mail_rule"],
               data_model=MailRule,
               description="Create an AUTO-REPLY rule — send an automatic text response to matching emails. Use when user says 'автоответчик', 'отвечай автоматически', 'auto-reply', 'out-of-office'. This does NOT forward the email — for forwarding use create_forward_rule instead. Supports 'always' or 'time_window' (OUTSIDE business hours) modes.")
async def fn_create_autoreply(ctx, params: CreateAutoreplyParams) -> ActionResult:
    """Create an auto-reply automation rule with optional business-hours schedule."""
    try:
        if not params.template.strip():
            return ActionResult.error("Reply template text is required.", retryable=False)
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        doc = await ctx.store.create(RULES_COLLECTION, {
            "owner_id": ctx.user.imperal_id,
            "name": params.name.strip()[:60],
            "rule_type": "autoreply",
            "enabled": True,
            "criteria_from": params.from_contains.strip(),
            "reply_template": params.template.strip(),
            "subject_prefix": params.subject_prefix.strip() or "Auto: ",
            "schedule_type": params.schedule_type,
            "schedule_days": params.days,
            "schedule_start": params.start_time,
            "schedule_end": params.end_time,
            "timezone": params.timezone or "UTC",
            "last_run_at": now,
            "created_at": now,
        })
        if params.schedule_type == "time_window":
            days_str = ",".join(["Mon","Tue","Wed","Thu","Fri","Sat","Sun"][d] for d in sorted(params.days))
            summary = (f"Auto-reply '{params.name}' active OUTSIDE "
                       f"{params.start_time}–{params.end_time} on {days_str} ({params.timezone}).")
        else:
            summary = f"Auto-reply '{params.name}' always active — runs every 5 min."
        return ActionResult.success(
            data=build_mail_rule(doc.id, doc.data),
            summary=summary,
        )
    except Exception as e:
        return ActionResult.error(str(e), retryable=False)


# ── Rules management ──────────────────────────────────────────────────────────

@chat.function("list_rules", action_type="read",
               data_model=MailRulePage,
               description="List all automation rules (forwarding + auto-reply). Shows type, enabled status, criteria and schedule. Use rule_id with toggle_rule() or delete_rule().")
async def fn_list_rules(ctx, params: EmptyParams) -> ActionResult:
    """List all forwarding and auto-reply automation rules."""
    try:
        page = await ctx.store.query(RULES_COLLECTION,
                                     where={"owner_id": ctx.user.imperal_id}, limit=20)
        return ActionResult.success(
            data=build_mail_rule_page(page.data),
            summary=f"{len(page.data)} automation rule(s).",
        )
    except Exception as e:
        return ActionResult.error(str(e), retryable=False)


@chat.function("toggle_rule", action_type="write", event="rule.toggled",
               effects=["update:mail_rule"],
               data_model=RuleOpResult,
               id_projection="rule_id",
               description="Enable or disable an automation rule without deleting it. Pass rule_id OR rule name — both work.")
async def fn_toggle_rule(ctx, params: ToggleRuleParams) -> ActionResult:
    """Enable or disable an automation rule by ID or name."""
    try:
        doc_id, doc_data = await _resolve_rule(ctx, params.rule_id)
        if not doc_id:
            return ActionResult.error(
                f"Rule '{params.rule_id}' not found. Use list_rules() to see your rules.",
                retryable=False)
        await ctx.store.update(RULES_COLLECTION, doc_id, {**doc_data, "enabled": params.enabled})
        name = doc_data.get("name", "rule")
        state = "enabled" if params.enabled else "disabled"
        return ActionResult.success(
            data=build_rule_op(doc_id, f"Rule '{name}' {state}", enabled=params.enabled),
            summary=f"Rule '{name}' {state}.",
        )
    except Exception as e:
        return ActionResult.error(str(e), retryable=False)


@chat.function("delete_rule", action_type="destructive", event="rule.deleted",
               effects=["delete:mail_rule"],
               data_model=RuleOpResult,
               id_projection="rule_id",
               description="Permanently delete an automation rule. Pass rule_id OR rule name — both work.")
async def fn_delete_rule(ctx, params: RuleIdParam) -> ActionResult:
    """Permanently delete an automation rule by ID or name."""
    try:
        doc_id, doc_data = await _resolve_rule(ctx, params.rule_id)
        if not doc_id:
            return ActionResult.error(
                f"Rule '{params.rule_id}' not found. Use list_rules() to see your rules.",
                retryable=False)
        name = doc_data.get("name", "rule")
        await ctx.store.delete(RULES_COLLECTION, doc_id)
        return ActionResult.success(
            data=build_rule_op(doc_id, f"Deleted rule '{name}'"),
            summary=f"Automation rule '{name}' deleted.",
        )
    except Exception as e:
        return ActionResult.error(str(e), retryable=False)


@chat.function("trigger_rules_now", action_type="write", event="rules.triggered",
               effects=["create:email"],
               data_model=RuleOpResult,
               description="Manually trigger all enabled mail automation rules NOW — checks last 30 inbox emails against all rules and executes matching forward/autoreply actions. Use to test rules or force immediate execution without waiting for the 5-minute schedule. Also shows debug info about what was found.")
async def fn_trigger_rules_now(ctx, params: EmptyParams) -> ActionResult:
    """Manually trigger rule processing and return detailed debug info."""
    try:
        from handlers_rule_runner import _process_user_rules, RULES_COLLECTION as RC
        uid = ctx.user.imperal_id

        # Show what rules exist
        rules_page = await ctx.store.query(RC, where={"owner_id": uid, "enabled": True}, limit=20)
        rule_count = len(rules_page.data)
        _log.info(f"trigger_rules_now: user={uid} found {rule_count} enabled rule(s)")

        if not rules_page.data:
            return ActionResult.success(
                data=build_rule_op("none", "No enabled rules found"),
                summary=f"No enabled rules found for user {uid}. Create a rule first with create_forward_rule or create_autoreply.",
            )

        executed = await _process_user_rules(ctx)
        _log.info(f"trigger_rules_now: executed {executed} action(s)")
        rule_names = [r.data.get("name", r.id) for r in rules_page.data]
        summary = (f"Triggered {rule_count} rule(s): {', '.join(rule_names)}. "
                   f"Executed {executed} action(s).")
        return ActionResult.success(
            data=build_rule_op("triggered", summary, enabled=True),
            summary=summary,
        )
    except Exception as e:
        _log.error(f"trigger_rules_now failed: {e}")
        return ActionResult.error(f"Rule trigger failed: {e}", retryable=True)
