"""Mail extension providers — factory and exports."""
from __future__ import annotations
from .google    import GoogleMailProvider
from .microsoft import MicrosoftMailProvider
from .imap      import ImapMailProvider


def get_provider(acc: dict):
    """Return a fresh provider instance for the given account dict.

    Intentionally constructs a new instance per call — providers are stateless
    objects. A module-level singleton would silently leak per-account state if
    any future refactor adds self.* attributes.
    """
    p = acc.get("provider", "oauth")
    if p == "oauth":
        return GoogleMailProvider()
    elif p == "microsoft":
        return MicrosoftMailProvider()
    elif p in ("imap", "yahoo"):
        return ImapMailProvider()
    raise ValueError(f"Unknown provider type: '{p}'")


__all__ = ["get_provider", "GoogleMailProvider", "MicrosoftMailProvider", "ImapMailProvider"]
