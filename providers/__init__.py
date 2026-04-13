"""Mail extension providers — factory and exports."""
from __future__ import annotations
from .google    import GoogleMailProvider
from .microsoft import MicrosoftMailProvider
from .imap      import ImapMailProvider

_INSTANCES: dict = {}

def get_provider(acc: dict):
    """Return the correct provider instance for the given account dict."""
    p = acc.get("provider", "oauth")
    if p == "oauth":
        return _INSTANCES.setdefault("google",    GoogleMailProvider())
    elif p == "microsoft":
        return _INSTANCES.setdefault("microsoft", MicrosoftMailProvider())
    elif p in ("imap", "yahoo"):
        return _INSTANCES.setdefault("imap",      ImapMailProvider())
    raise ValueError(f"Unknown provider type: '{p}'")

__all__ = ["get_provider", "GoogleMailProvider", "MicrosoftMailProvider", "ImapMailProvider"]
