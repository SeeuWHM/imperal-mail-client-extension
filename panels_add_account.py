"""Mail Client · Add Account Panel (3-step wizard)."""
from __future__ import annotations

import logging

from imperal_sdk import ui

from providers.helpers import _detect_imap_settings, _imap_hint, IMAP_PROVIDERS

log = logging.getLogger(__name__)


async def build_add_account_panel(
    ctx, step: str = "providers", email: str = "", error: str = "",
) -> ui.UINode:
    if step == "providers":
        return _step_providers()
    elif step == "password":
        return _step_password(email, error)
    elif step == "advanced":
        return _step_advanced(email, error)
    return ui.Empty(message="Unknown step")


def _step_providers() -> ui.UINode:
    return ui.Stack([
        ui.Header(text="Add Email Account", level=3),
        ui.Button("Connect Google", icon="Mail", variant="outline",
                  on_click=ui.Send("Connect my Google Gmail account")),
        ui.Button("Connect Microsoft", icon="Mail", variant="outline",
                  on_click=ui.Send("Connect my Microsoft Outlook account")),
        ui.Divider(label="or connect manually"),
        ui.Form(
            children=[ui.Input(placeholder="Enter email address", param_name="email")],
            action="__panel__add_account",
            submit_label="Next",
            defaults={"step": "password"},
        ),
        ui.Button("Cancel", variant="ghost", on_click=ui.Call("__panel__accounts")),
    ])


def _step_password(email: str, error: str) -> ui.UINode:
    detected = _detect_imap_settings(email)
    domain   = email.split("@")[-1].lower() if "@" in email else ""

    children: list = [ui.Header(text=f"Connect {email}", level=3)]

    if domain in IMAP_PROVIDERS:
        hint = _imap_hint(email)
        if hint:
            children.append(ui.Alert(message=hint, type="info"))

    if error:
        children.append(ui.Alert(message=error, type="error"))

    children.append(ui.Form(
        children=[ui.Input(placeholder="Password or App Password", param_name="password")],
        action="add_imap",
        submit_label="Connect",
        defaults={
            "email": email,
            "imap_host": detected.get("imap_host", ""),
            "smtp_host": detected.get("smtp_host", ""),
            "imap_port": detected.get("imap_port", 993),
            "smtp_port": detected.get("smtp_port", 587),
        },
    ))

    children.append(ui.Button("Advanced Settings", variant="ghost",
                               on_click=ui.Call("__panel__add_account", step="advanced", email=email)))
    children.append(ui.Button("Back", variant="ghost",
                               on_click=ui.Call("__panel__add_account", step="providers")))
    return ui.Stack(children)


def _step_advanced(email: str, error: str) -> ui.UINode:
    detected = _detect_imap_settings(email)
    children: list = [ui.Header(text=f"Advanced Settings — {email}", level=3)]

    if error:
        children.append(ui.Alert(message=error, type="error"))

    children.append(ui.Form(
        children=[
            ui.Input(placeholder="Password", param_name="password"),
            ui.Input(placeholder="IMAP Host", value=detected.get("imap_host", ""), param_name="imap_host"),
            ui.Input(placeholder="IMAP Port", value=str(detected.get("imap_port", 993)), param_name="imap_port"),
            ui.Input(placeholder="SMTP Host", value=detected.get("smtp_host", ""), param_name="smtp_host"),
            ui.Input(placeholder="SMTP Port", value=str(detected.get("smtp_port", 587)), param_name="smtp_port"),
        ],
        action="add_imap",
        submit_label="Connect",
        defaults={"email": email},
    ))

    children.append(ui.Button("Back", variant="ghost",
                               on_click=ui.Call("__panel__add_account", step="password", email=email)))
    return ui.Stack(children)
