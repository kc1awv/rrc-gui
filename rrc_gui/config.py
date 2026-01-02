"""Configuration file management for RRC GUI."""

from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path

logger = logging.getLogger(__name__)


def _expand_path(p: str) -> str:
    """Expand ~ and environment variables in path."""
    return os.path.expanduser(os.path.expandvars(p))


def get_config_path() -> Path:
    """Get path to GUI config file.

    Can be overridden with RRC_GUI_CONFIG environment variable.
    """
    config_path = os.environ.get("RRC_GUI_CONFIG")
    if config_path:
        return Path(_expand_path(config_path))
    return Path(_expand_path("~/.rrc/gui_config.json"))


def load_config() -> dict:
    """Load saved connection settings."""
    config_path = get_config_path()
    if config_path.exists():
        try:
            with open(config_path, encoding="utf-8") as f:
                return json.load(f)
        except json.JSONDecodeError as e:
            logger.warning("Failed to parse config file %s: %s", config_path, e)
        except OSError as e:
            logger.warning("Failed to read config file %s: %s", config_path, e)
        except Exception as e:
            logger.exception("Unexpected error loading config from %s", config_path)
    return {}


def save_config(config: dict) -> None:
    """Save connection settings."""
    config_path = get_config_path()
    config_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2)
        try:
            os.chmod(config_path, 0o600)
        except OSError as e:
            logger.warning(
                "Failed to set permissions on config file %s: %s", config_path, e
            )
    except OSError as e:
        logger.error("Failed to save config to %s: %s", config_path, e)
        print(
            f"Warning: Failed to save config to {config_path}: {e}",
            file=sys.stderr,
        )
    except Exception as e:
        logger.exception("Unexpected error saving config to %s", config_path)
        print(
            f"Warning: Failed to save config to {config_path}: {e}",
            file=sys.stderr,
        )
