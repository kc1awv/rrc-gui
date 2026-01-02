"""Utility functions for RRC GUI."""

from __future__ import annotations

import logging
import os
from datetime import datetime
from pathlib import Path

import RNS

logger = logging.getLogger(__name__)


def get_timestamp() -> str:
    """Get current timestamp formatted for display.

    Returns:
        Formatted timestamp string (HH:MM:SS)
    """
    return datetime.now().strftime("%H:%M:%S")


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
    except OSError as e:
        logger.warning(
            "Failed to set permissions on identity file %s: %s - file may be insecure",
            identity_path,
            e,
        )
    return ident


def normalize_room_name(room: str) -> str | None:
    """Normalize room name to lowercase and strip whitespace.

    Args:
        room: The room name to normalize.

    Returns:
        Normalized room name, or None if invalid (contains spaces or is empty).

    Validation rules:
    - 1-64 characters
    - No spaces
    - Alphanumeric, hyphens, underscores, dots, # allowed
    - Cannot be only special characters
    - Cannot start/end with dots (prevents '..' and similar)
    - Cannot have consecutive special characters (prevents '--', '__', etc.)
    """
    if not isinstance(room, str):
        return None

    r = room.strip().lower()

    if not r or " " in r:
        return None

    if len(r) < 1 or len(r) > 64:
        return None

    if not all(c.isalnum() or c in "-_.#" for c in r):
        return None

    if not any(c.isalnum() for c in r):
        return None

    if r.startswith(".") or r.endswith("."):
        return None

    special_chars = "-_.#"
    for i in range(len(r) - 1):
        if r[i] in special_chars and r[i + 1] in special_chars:
            return None

    return r


def sanitize_text_input(text: str, max_length: int = 1024) -> str | None:
    """Sanitize and validate user text input.

    Args:
        text: The text to sanitize.
        max_length: Maximum allowed length.

    Returns:
        Sanitized text, or None if invalid.
    """
    if not isinstance(text, str):
        return None

    text = text.strip()

    if not text:
        return None

    if len(text) > max_length:
        return None

    cleaned = "".join(c for c in text if ord(c) >= 32 or c in "\n\t")

    if not cleaned:
        return None

    return cleaned
