"""Mail Client — SDL builders for filters, rules and preferences (SDK 5.2.0)."""
from __future__ import annotations

from schemas_sdl_rules import (
    MailFilter, MailFilterPage, RuleOpResult, MailPrefsResult,
    MailFoldersResult,
)


def build_mail_filter(doc_id: str, data: dict) -> MailFilter:
    """Convert store document dict → MailFilter SDL entity."""
    return MailFilter(
        id=doc_id,
        title=data.get("name", "filter"),
        kind="mail_filter",
        criteria_from=data.get("criteria_from") or None,
        criteria_subject=data.get("criteria_subject") or None,
        criteria_folder=data.get("criteria_folder") or None,
        color=data.get("color") or None,
        enabled=bool(data.get("enabled", True)),
        tags=[data["name"]] if data.get("name") else None,
    )


def build_mail_filter_page(docs: list) -> MailFilterPage:
    """Convert list of store documents → MailFilterPage SDL entity list."""
    items = [build_mail_filter(d.id, d.data) for d in docs]
    return MailFilterPage(items=items, total=len(items))


def build_rule_op(entity_id: str, name: str, enabled: bool | None = None) -> RuleOpResult:
    """Build a rule/filter operation confirmation SDL entity."""
    return RuleOpResult(
        id=entity_id,
        title=name,
        kind="rule_op",
        rule_id=entity_id,
        op_enabled=enabled,
    )


def build_mail_prefs(visible_folders: list[str], hidden_folders: list[str]) -> MailPrefsResult:
    """Build a mail preferences SDL entity."""
    return MailPrefsResult(
        id="mail_prefs",
        title="Mail Preferences",
        kind="mail_prefs",
        visible_folders=visible_folders or None,
        hidden_folders=hidden_folders or None,
    )


def build_mail_folders(all_keys: list[str], visible: list[str], hidden: list[str]) -> MailFoldersResult:
    """Build MailFoldersResult SDL entity for list_mail_folders()."""
    shown = [k for k in all_keys if k not in hidden]
    summary_title = f"Visible: {', '.join(shown) or 'all'}"
    return MailFoldersResult(
        id="mail_folders",
        title=summary_title,
        kind="mail_folders",
        all_folders=all_keys or None,
        visible_folders=shown or None,
        hidden_folders=hidden or None,
    )
