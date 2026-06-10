"""Mail Client · Accounts / Filters Panel (right slot, multi-tab)."""
from __future__ import annotations

import logging

from imperal_sdk import ui
from providers.helpers import _all_accounts

log = logging.getLogger(__name__)

PROVIDER_LABELS = {
    "oauth": "Google", "microsoft": "Microsoft",
    "yahoo": "Yahoo",  "imap": "IMAP",
}


# ── Tab navigation ────────────────────────────────────────────────────────────

def _tab_bar(active: str) -> ui.UINode:
    tabs = [
        ("accounts", "Accounts", "Users"),
        ("filters",  "Filters",  "Filter"),
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
        subtitle_text = PROVIDER_LABELS.get(provider, "Unknown")
        if is_active:
            subtitle_text = f"✓ Active — {subtitle_text}"
        items.append(ui.ListItem(
            id=email, title=email,
            subtitle=subtitle_text,
            avatar=ui.Avatar(fallback=email[0].upper(), size="sm"),
            badge=ui.Badge(f"✓ {unread}" if unread > 0 else "✓ Active", color="green") if is_active else (
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
    from providers.helpers import _active_account
    acc = await _active_account(ctx, "")
    active_email = acc.get("email", "") if acc else ""
    page = await ctx.store.query("mail_filters",
                                 where={"owner_id": ctx.user.imperal_id}, limit=20)
    page_data = [f for f in page.data
                 if not f.data.get("account_email") or
                 f.data.get("account_email") == active_email]
    if not page_data:
        return ui.Stack([
            ui.Empty(message="No smart filters yet", icon="Filter"),
            ui.Alert(message="Tell Webbee: 'create a filter for LinkedIn emails' or 'show emails from shop.com'",
                     type="info"),
        ], gap=2)

    COLOR_MAP = {"blue": "blue", "green": "green", "red": "red",
                 "yellow": "yellow", "purple": "purple", "orange": "orange"}
    items = []
    for f in page_data:
        d = f.data
        parts = []
        emails = d.get("criteria_from_emails") or []
        if emails:
            parts.append(f"from: {', '.join(emails)}")
        elif d.get("criteria_from"):
            parts.append(f"from: {d['criteria_from']}")
        if d.get("criteria_subject"): parts.append(f"subj: {d['criteria_subject']}")
        subtitle = " · ".join(parts) if parts else "no criteria set"
        color = COLOR_MAP.get(d.get("color", "blue"), "blue")
        items.append(ui.ListItem(
            id=f.id, title=d.get("name", "filter"),
            subtitle=subtitle,
            badge=ui.Badge("●", color=color),
            actions=[{"label": "Delete", "icon": "Trash2",
                      "on_click": ui.Call("delete_filter", filter_id=f.id)}],
        ))

    return ui.Stack([
        ui.Text(f"{len(page_data)} smart filter(s) for {active_email[:30]}", variant="caption"),
        ui.List(items=items),
    ], gap=2)


# ── Entry point ───────────────────────────────────────────────────────────────

async def build_accounts_panel(ctx, tab: str = "accounts", **kwargs) -> ui.UINode:
    """Render accounts/filters right panel with tab switching."""
    tab_bar = _tab_bar(tab)
    try:
        if tab == "filters":
            content = await _build_filters_tab(ctx)
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
