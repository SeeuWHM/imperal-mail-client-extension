"""Mail Client · Accounts / Filters Panel (right slot, multi-tab)."""
from __future__ import annotations

import logging

from imperal_sdk import ui
from mail_providers.helpers import _all_accounts, _is_microsoft_account, _active_account

log = logging.getLogger(__name__)

PROVIDER_LABELS = {
    "oauth": "Google", "google": "Google", "microsoft": "Microsoft",
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
        if _is_microsoft_account(acc):
            subtitle_text = "Microsoft"
        else:
            subtitle_text = PROVIDER_LABELS.get(provider, "Unknown")
        if is_active:
            subtitle_text = f"✓ Active — {subtitle_text}"
        items.append(ui.ListItem(
            id=email, title=email,
            subtitle=subtitle_text,
            icon="Mail",
            avatar=ui.Avatar(fallback=email[0].upper(), size="sm"),
            badge=ui.Badge(f"✓ {unread}" if unread > 0 else "✓ Active", color="green") if is_active else (
                ui.Badge(str(unread), color="blue") if unread > 0 else None),
            on_click=ui.Call("switch_account", account=email),
            actions=[{"label": "Remove", "icon": "Trash2",
                      "on_click": ui.Call("disconnect", account=email)}],
        ))

    # Accounts get a blue/green identity (mailboxes you own) vs. Filters'
    # purple/orange (rules you've written) — the two tabs should read as
    # different modes at a glance, not just a relabeled list underneath.
    return ui.Stack([
        ui.Stats([
            ui.Stat(label="Accounts", value=len(accounts), color="blue", icon="Mail"),
            ui.Stat(label="Unread",   value=total_unread, color="green" if total_unread else "gray"),
        ], columns=2),
        ui.Divider(label="Mailboxes"),
        ui.List(items=items),
        ui.Divider(),
        ui.Button("Add Account", icon="Plus", variant="outline",
                  on_click=ui.Call("__panel__add_account")),
    ], gap=2)


# ── Filters tab ───────────────────────────────────────────────────────────────

async def _build_filters_tab(ctx) -> ui.UINode:
    acc = await _active_account(ctx, "")
    active_email = acc.get("email", "") if acc else ""

    # Load ALL filters for this user, show only those matching active account
    page = await ctx.store.query("mail_filters",
                                 where={"owner_id": ctx.user.imperal_id}, limit=50)
    page_data = [f for f in page.data
                 if not f.data.get("account_email") or
                 f.data.get("account_email") == active_email]

    if not page_data:
        return ui.Stack([
            ui.Text(f"Mailbox: {active_email}", variant="caption"),
            ui.Empty(message="No smart filters for this account", icon="Filter"),
            ui.Alert(
                message="Tell Webbee: 'create a filter for LinkedIn emails' or 'show emails from shop.com'",
                type="info",
            ),
        ], gap=2)

    COLOR_MAP = {"blue": "blue", "green": "green", "red": "red",
                 "yellow": "yellow", "purple": "purple", "orange": "orange"}
    items = []
    colors_in_use: set[str] = set()
    for f in page_data:
        d = f.data
        # Criteria subtitle
        parts = []
        emails = d.get("criteria_from_emails") or []
        if emails:
            parts.append(f"from: {', '.join(emails)}")
        elif d.get("criteria_from"):
            parts.append(f"from: {d['criteria_from']}")
        if d.get("criteria_subject"):
            parts.append(f"subj: {d['criteria_subject']}")
        criteria_str = " · ".join(parts) if parts else "no criteria set"

        # Show account email on the filter if it differs from active (e.g. legacy/untagged)
        filter_account = d.get("account_email", "")
        subtitle = criteria_str
        if filter_account and filter_account != active_email:
            subtitle = f"{filter_account[:28]} · {criteria_str}"

        color = COLOR_MAP.get(d.get("color", "blue"), "blue")
        colors_in_use.add(color)
        items.append(ui.ListItem(
            id=f.id,
            title=d.get("name", "filter"),
            subtitle=subtitle,
            icon="Filter",
            badge=ui.Badge(d.get("color", "blue").capitalize(), color=color, dot=True),
            actions=[{"label": "Delete", "icon": "Trash2",
                      "on_click": ui.Call("delete_filter", filter_id=f.id)}],
        ))

    # Filters get their own purple/amber identity (vs. blue/green for Accounts)
    # so the two tabs read as visually distinct modes, not just a relabeled list.
    return ui.Stack([
        ui.Stats([
            ui.Stat(label="Filters", value=len(page_data), color="purple", icon="Filter"),
            ui.Stat(label="Colors used", value=len(colors_in_use), color="orange"),
        ], columns=2),
        ui.Text(f"Mailbox: {active_email}", variant="caption"),
        ui.Divider(label="Smart Filters"),
        ui.List(items=items),
    ], gap=2)


# ── Entry point ───────────────────────────────────────────────────────────────

async def build_accounts_panel(ctx, tab: str = "accounts", **kwargs) -> ui.UINode:
    """Render accounts/filters right panel with tab switching.

    The header text/subtitle change with the active tab (not a static "Mail"
    for both) — together with each tab's own stat-card colour identity
    (blue/green for Accounts, purple/orange for Filters) this makes the two
    modes read as visually distinct at a glance, since switching between them
    is a single click away.
    """
    tab_bar = _tab_bar(tab)
    try:
        if tab == "filters":
            content = await _build_filters_tab(ctx)
            header_title, header_subtitle = "Smart Filters", "Rules that sort mail automatically"
        else:
            content = await _build_accounts_tab(ctx)
            header_title, header_subtitle = "Mailboxes", "Accounts connected to this mail client"
    except Exception as exc:
        log.error(f"accounts panel tab={tab} error: {exc}")
        content = ui.Alert(message=f"Error loading panel: {exc}", type="error")
        header_title, header_subtitle = "Mail", ""

    return ui.Stack([
        ui.Header(text=header_title, level=3, subtitle=header_subtitle),
        tab_bar,
        ui.Divider(),
        content,
    ], gap=2, className="pb-4")
