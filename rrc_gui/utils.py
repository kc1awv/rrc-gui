"""Utility functions for RRC GUI."""

from __future__ import annotations

import os
from pathlib import Path

import RNS


def expand_path(p: str) -> str:
    """Expand ~ and environment variables in path."""
    return os.path.expanduser(os.path.expandvars(p))


def load_or_create_identity(path: str) -> RNS.Identity:
    """Load identity from file or create a new one."""
    identity_path = Path(expand_path(path))
    identity_path.parent.mkdir(parents=True, exist_ok=True)
    if identity_path.exists():
        ident = RNS.Identity.from_file(str(identity_path))
        if ident is None:
            raise RuntimeError(f"Failed to load identity from {identity_path}")
        return ident
    ident = RNS.Identity()
    ident.to_file(str(identity_path))
    try:
        os.chmod(identity_path, 0o600)
    except Exception:
        pass
    return ident


def normalize_room_name(room: str) -> str:
    """Normalize room name to lowercase and strip whitespace."""
    r = room.strip().lower()
    if " " in r:
        return ""
    return r


def sanitize_display_name(name: str, max_length: int = 64) -> str | None:
    """Sanitize display names like hub names and nicknames.

    Removes control characters and limits length. More permissive than
    sanitize_text_input as these are display-only and don't allow newlines.

    Args:
        name: Name to sanitize
        max_length: Maximum allowed length

    Returns:
        Sanitized name, or None if invalid
    """
    if not isinstance(name, str):
        return None

    sanitized = name.strip()
    if not sanitized:
        return None

    if len(sanitized) > max_length:
        sanitized = sanitized[:max_length]

    cleaned = ""
    for char in sanitized:
        code = ord(char)
        if code < 32 or code == 0x7F or code == 0xFFFE or code == 0xFFFF:
            continue
        cleaned += char

    if not cleaned:
        return None

    return cleaned
