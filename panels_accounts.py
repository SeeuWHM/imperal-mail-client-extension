"""Mail Client · Accounts/Filters/Rules Panel (right slot, multi-tab)."""
from __future__ import annotations

import logging

from imperal_sdk import ui
from providers.helpers import _all_accounts

log = logging.getLogger(__name__)

PROVIDER_LABELS = {
    "oauth": "Google", "microsoft": "Microsoft",
    "yahoo": "Yahoo",  "imap": "IMAP",
}

RULE_TYPE_LABELS = {"forward": "Forwarder", "autoreply": "Auto-reply"}
RULE_TYPE_ICONS  = {"forward": "Forward", "autoreply": "MessageSquareReply"}


# ── Tab navigation ────────────────────────────────────────────────────────────

def _tab_bar(active: str) -> ui.UINode:
    tabs = [
        ("accounts", "Accounts", "Users"),
        ("filters",  "Filters",  "Filter"),
        ("rules",    "Rules",    "Bot"),
    ]
    buttons = [
        ui.Button(
            label=label, icon=icon,
            variant="primary" if active == key else "outline",
            on_click=ui.Call("__panel__accounts", tab=key),
        )
        for key, label, icon in tabs
    ]
    return ui.Stack(buttons, direction="h", gap=1)


# ── Accounts tab ──────────────────────────────────────────────────────────────

async def _build_accounts_tab(ctx) -> ui.UINode:
    accounts = await _all_accounts(ctx)
    if not accounts:
        return ui.Stack([
            ui.Empty(message="No email accounts connected", icon="Mail"),
            ui.Button("Add Account", icon="Plus", variant="primary",
                      on_click=ui.Call("__panel__add_account")),
        ], gap=2)

    total_unread = sum(int(a.get("unread_count", 0) or 0) for a in accounts)
    items = []
    for acc in accounts:
        email     = acc.get("email", "?")
        provider  = acc.get("provider", "oauth")
        is_active = acc.get("is_active", False)
        unread    = int(acc.get("unread_count", 0) or 0)
        items.append(ui.ListItem(
            id=email, title=email,
            subtitle=PROVIDER_LABELS.get(provider, "Unknown"),
            avatar=ui.Avatar(fallback=email[0].upper(), size="sm"),
            badge=ui.Badge("Active", color="green") if is_active else (
                ui.Badge(str(unread), color="blue") if unread > 0 else None),
            on_click=ui.Call("switch_account", account=email),
            actions=[{"label": "Remove", "icon": "Trash2",
                      "on_click": ui.Call("disconnect", account=email)}],
        ))

    return ui.Stack([
        ui.Stats([
            ui.Stat(label="Unread",   value=total_unread, color="blue" if total_unread else ""),
            ui.Stat(label="Accounts", value=len(accounts)),
        ], columns=2),
        ui.Divider(),
        ui.List(items=items),
        ui.Divider(),
        ui.Button("Add Account", icon="Plus", variant="outline",
                  on_click=ui.Call("__panel__add_account")),
    ], gap=2)


# ── Filters tab ───────────────────────────────────────────────────────────────

async def _build_filters_tab(ctx) -> ui.UINode:
    page = await ctx.store.query("mail_filters",
                                 where={"owner_id": ctx.user.imperal_id}, limit=20)
    if not page.data:
        return ui.Stack([
            ui.Empty(message="No smart filters yet", icon="Filter"),
            ui.Alert(message="Tell Webbee: 'create a filter for LinkedIn emails' or 'show emails from shop.com'",
                     type="info"),
        ], gap=2)

    COLOR_MAP = {"blue": "blue", "green": "green", "red": "red",
                 "yellow": "yellow", "purple": "purple", "orange": "orange"}
    items = []
    for f in page.data:
        d = f.data
        parts = []
        if d.get("criteria_from"):    parts.append(f"from: {d['criteria_from']}")
        if d.get("criteria_subject"): parts.append(f"subj: {d['criteria_subject']}")
        subtitle = " · ".join(parts) if parts else "match all"
        color = COLOR_MAP.get(d.get("color", "blue"), "blue")
        items.append(ui.ListItem(
            id=f.id, title=d.get("name", "filter"),
            subtitle=subtitle,
            badge=ui.Badge("●", color=color),
            # NOT clickable — only delete action on the right
            actions=[{"label": "Delete", "icon": "Trash2",
                      "on_click": ui.Call("delete_filter", filter_id=f.id)}],
        ))

    return ui.Stack([
        ui.Text(f"{len(page.data)} smart filter(s)", variant="caption"),
        ui.List(items=items),
    ], gap=2)


# ── Rules tab ─────────────────────────────────────────────────────────────────

async def _build_rules_tab(ctx) -> ui.UINode:
    page = await ctx.store.query("mail_rules",
                                 where={"owner_id": ctx.user.imperal_id}, limit=20)
    if not page.data:
        return ui.Stack([
            ui.Empty(message="No automation rules", icon="Bot"),
            ui.Alert(message="Tell Webbee: 'forward emails from X to Y' or 'set up out-of-office reply'",
                     type="info"),
        ], gap=2)

    items = []
    for r in page.data:
        d = r.data
        rtype = d.get("rule_type", "forward")
        enabled = bool(d.get("enabled", True))
        if rtype == "forward":
            subtitle = f"→ {d.get('forward_to', '?')}"
            if d.get("criteria_from"): subtitle += f" (from: {d['criteria_from']})"
        else:
            stype = d.get("schedule_type", "always")
            if stype == "always":
                subtitle = "Active always"
            else:
                t_start = d.get("schedule_start", "09:00")
                t_end = d.get("schedule_end", "18:00")
                subtitle = f"Outside {t_start}–{t_end}"
        items.append(ui.ListItem(
            id=r.id, title=d.get("name", "rule"),
            subtitle=f"{RULE_TYPE_LABELS.get(rtype, rtype)} · {subtitle}",
            badge=ui.Badge("ON", color="green") if enabled else ui.Badge("OFF", color="gray"),
            actions=[
                {"label": "Disable" if enabled else "Enable", "icon": "Power",
                 "on_click": ui.Call("toggle_rule", rule_id=r.id, enabled=not enabled)},
                {"label": "Delete", "icon": "Trash2",
                 "on_click": ui.Call("delete_rule", rule_id=r.id)},
            ],
        ))

    return ui.Stack([
        ui.Text(f"{len(page.data)} rule(s) — runs every 5 min", variant="caption"),
        ui.List(items=items),
    ], gap=2)


# ── Entry point ───────────────────────────────────────────────────────────────

async def build_accounts_panel(ctx, tab: str = "accounts", **kwargs) -> ui.UINode:
    """Render accounts/filters/rules right panel with tab switching."""
    tab_bar = _tab_bar(tab)
    try:
        if tab == "filters":
            content = await _build_filters_tab(ctx)
        elif tab == "rules":
            content = await _build_rules_tab(ctx)
        else:
            content = await _build_accounts_tab(ctx)
    except Exception as exc:
        log.error(f"accounts panel tab={tab} error: {exc}")
        content = ui.Alert(message=f"Error loading panel: {exc}", type="error")

    return ui.Stack([
        ui.Header(text="Mail", level=3),
        tab_bar,
        ui.Divider(),
        content,
    ], gap=2, className="pb-4")
