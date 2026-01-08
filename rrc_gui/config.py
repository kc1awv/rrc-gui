"""Configuration file management for RRC GUI."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path


def _expand_path(p: str) -> str:
    """Expand ~ and environment variables in path."""
    return os.path.expanduser(os.path.expandvars(p))


def get_config_path() -> Path:
    """Get path to GUI config file."""
    return Path(_expand_path("~/.rrc-gui/config"))


def load_config() -> dict[str, str]:
    """Load saved connection settings."""
    config_path = get_config_path()
    if config_path.exists():
        try:
            with open(config_path, encoding="utf-8") as f:
                data: dict[str, str] = json.load(f)
                return data
        except Exception:
            pass
    return {}


def save_config(config: dict) -> None:
    """Save connection settings."""
    config_path = get_config_path()
    config_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2)
        os.chmod(config_path, 0o600)
    except Exception as e:
        print(
            f"Warning: Failed to save config to {config_path}: {e}",
            file=sys.stderr,
        )
