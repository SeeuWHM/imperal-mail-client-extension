"""Mail Client — SDL entities for filters, rules and preferences (SDK 5.2.0)."""
from __future__ import annotations

from imperal_sdk import sdl
from imperal_sdk.sdl import field as sdl_field


# ── Smart filter (virtual mailbox) ────────────────────────────────────────────

class MailFilter(sdl.Entity, sdl.Categorized, sdl.Lifecycle):
    """Smart mailbox — virtual folder defined by search criteria stored locally."""

    kind: str = "mail_filter"
    criteria_from: str | None = sdl_field(role="mail.criteria_from")
    criteria_subject: str | None = sdl_field(role="mail.criteria_subject")
    criteria_folder: str | None = sdl_field(role="mail.criteria_folder")
    color: str | None = sdl_field(role="mail.color")
    enabled: bool = sdl_field(role="mail.enabled", default=True)


class MailFilterPage(sdl.EntityList[MailFilter]):
    """Paginated list of smart mailbox filters — returned by list_filters()."""

    pass


# ── Automation rule (forwarder + auto-responder) ──────────────────────────────

class MailRule(sdl.Entity):
    """Mail automation rule — forward matching emails or send automatic replies."""

    kind: str = "mail_rule"
    rule_type: str | None = sdl_field(role="mail.rule_type")       # "forward" | "autoreply"
    enabled: bool = sdl_field(role="mail.enabled", default=True)
    criteria_from: str | None = sdl_field(role="mail.criteria_from")
    criteria_subject: str | None = sdl_field(role="mail.criteria_subject")
    forward_to: str | None = sdl_field(role="mail.forward_to")
    reply_template: str | None = sdl_field(role="mail.reply_template")
    subject_prefix: str | None = sdl_field(role="mail.subject_prefix")
    schedule_type: str | None = sdl_field(role="mail.schedule_type")  # always | time_window
    schedule_days: list[int] | None = sdl_field(role="mail.schedule_days")
    schedule_start: str | None = sdl_field(role="mail.schedule_start")  # "HH:MM"
    schedule_end: str | None = sdl_field(role="mail.schedule_end")      # "HH:MM"
    timezone: str | None = sdl_field(role="mail.timezone")
    last_run_at: str | None = sdl_field(role="mail.last_run_at")


class MailRulePage(sdl.EntityList[MailRule]):
    """Paginated list of automation rules — returned by list_rules()."""

    pass


# ── Operation result ──────────────────────────────────────────────────────────

class RuleOpResult(sdl.Entity):
    """Filter/rule create, update, toggle or delete confirmation."""

    kind: str = "rule_op"
    rule_id: str | None = sdl_field(role="mail.rule_id")
    op_enabled: bool | None = sdl_field(role="mail.enabled")


# ── Folder preferences ────────────────────────────────────────────────────────

class MailPrefsResult(sdl.Entity):
    """User mail preferences — visible folders, display settings."""

    kind: str = "mail_prefs"
    visible_folders: list[str] | None = sdl_field(role="mail.visible_folders")
    hidden_folders: list[str] | None = sdl_field(role="mail.hidden_folders")


class MailFoldersResult(sdl.Entity):
    """All available mail folders + visibility — returned by list_mail_folders()."""

    kind: str = "mail_folders"
    all_folders: list[str] | None = sdl_field(role="mail.all_folders")
    visible_folders: list[str] | None = sdl_field(role="mail.visible_folders")
    hidden_folders: list[str] | None = sdl_field(role="mail.hidden_folders")
