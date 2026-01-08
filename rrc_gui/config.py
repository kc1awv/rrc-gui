"""Configuration file management for RRC GUI."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any


def _expand_path(p: str) -> str:
    """Expand ~ and environment variables in path."""
    return os.path.expanduser(os.path.expandvars(p))


def get_config_path() -> Path:
    """Get path to GUI config file."""
    return Path(_expand_path("~/.rrc-gui/config.json"))


def get_default_config() -> dict[str, Any]:
    """Get default configuration values.

    Returns:
        Dictionary with default configuration
    """
    return {
        # Connection settings
        "hub_hash": "",
        "nickname": "",
        "auto_join_room": "",
        "identity_path": "~/.rrc-gui/identity",
        "dest_name": "rrc.hub",
        "configdir": "",
        # UI settings
        "window_width": 900,
        "window_height": 600,
        "theme": "system",
        "font_size": 10,
        # Logging settings
        "log_level": "INFO",
        "log_to_file": True,
        "log_to_console": False,
        "max_log_size_mb": 10,
        "log_backup_count": 5,
        # Rate limiting
        "rate_limit_enabled": True,
        "max_messages_per_minute": 30,
        "rate_warning_threshold": 0.8,
        # Input history
        "input_history_size": 50,
        "save_input_history": True,
        # Message display
        "max_messages_per_room": 500,
        "show_timestamps": True,
        "timestamp_format": "%H:%M:%S",
        # Notifications
        "enable_notifications": False,
        "notify_on_mention": True,
        "notify_on_all_messages": False,
        # Advanced
        "auto_reconnect": True,
        "reconnect_delay_seconds": 5,
        "connection_timeout_seconds": 30,
        "enable_hub_discovery": True,
        "hub_discovery_cleanup_hours": 24,
    }


def load_config() -> dict[str, Any]:
    """Load saved configuration.

    Returns:
        Configuration dictionary with defaults filled in
    """
    config_path = get_config_path()
    saved_config = {}

    if config_path.exists():
        try:
            with open(config_path, encoding="utf-8") as f:
                saved_config = json.load(f)
        except Exception:
            pass

    # Merge with defaults
    default_config = get_default_config()
    default_config.update(saved_config)
    return default_config


def save_config(config: dict[str, Any]) -> None:
    """Save configuration.

    Args:
        config: Configuration dictionary to save
    """
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


def get_config_schema() -> dict[str, dict[str, Any]]:
    """Get configuration schema with metadata.

    Returns:
        Dictionary mapping config keys to their metadata
    """
    return {
        "hub_hash": {
            "type": "string",
            "label": "Hub Hash",
            "description": "Destination hash of the RRC hub",
            "category": "Connection",
        },
        "nickname": {
            "type": "string",
            "label": "Nickname",
            "description": "Your display name in chat",
            "category": "Connection",
        },
        "auto_join_room": {
            "type": "string",
            "label": "Auto-join Room",
            "description": "Room to join automatically on connect",
            "category": "Connection",
        },
        "identity_path": {
            "type": "path",
            "label": "Identity Path",
            "description": "Path to Reticulum identity file",
            "category": "Connection",
        },
        "dest_name": {
            "type": "string",
            "label": "Destination Name",
            "description": "RNS destination aspect name",
            "category": "Connection",
        },
        "configdir": {
            "type": "path",
            "label": "Reticulum Config Directory",
            "description": "Custom Reticulum config directory (optional)",
            "category": "Connection",
        },
        "window_width": {
            "type": "integer",
            "label": "Window Width",
            "description": "Default window width in pixels",
            "category": "UI",
            "min": 400,
            "max": 4000,
        },
        "window_height": {
            "type": "integer",
            "label": "Window Height",
            "description": "Default window height in pixels",
            "category": "UI",
            "min": 300,
            "max": 3000,
        },
        "theme": {
            "type": "choice",
            "label": "Theme",
            "description": "Color theme for the application",
            "category": "UI",
            "choices": ["system", "light", "dark"],
        },
        "font_size": {
            "type": "integer",
            "label": "Font Size",
            "description": "Base font size in points",
            "category": "UI",
            "min": 6,
            "max": 24,
        },
        "log_level": {
            "type": "choice",
            "label": "Log Level",
            "description": "Logging verbosity level",
            "category": "Logging",
            "choices": ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
            "requires_restart": True,
        },
        "log_to_file": {
            "type": "boolean",
            "label": "Log to File",
            "description": "Enable logging to file",
            "category": "Logging",
            "requires_restart": True,
        },
        "log_to_console": {
            "type": "boolean",
            "label": "Log to Console",
            "description": "Enable logging to console/terminal",
            "category": "Logging",
            "requires_restart": True,
        },
        "max_log_size_mb": {
            "type": "integer",
            "label": "Max Log Size (MB)",
            "description": "Maximum log file size before rotation",
            "category": "Logging",
            "min": 1,
            "max": 100,
            "requires_restart": True,
        },
        "log_backup_count": {
            "type": "integer",
            "label": "Log Backup Count",
            "description": "Number of rotated log files to keep",
            "category": "Logging",
            "min": 0,
            "max": 20,
            "requires_restart": True,
        },
        "rate_limit_enabled": {
            "type": "boolean",
            "label": "Enable Rate Limiting",
            "description": "Enable client-side message rate limiting",
            "category": "Rate Limiting",
        },
        "max_messages_per_minute": {
            "type": "integer",
            "label": "Max Messages/Minute",
            "description": "Maximum messages allowed per minute",
            "category": "Rate Limiting",
            "min": 1,
            "max": 100,
        },
        "rate_warning_threshold": {
            "type": "float",
            "label": "Warning Threshold",
            "description": "Fraction of limit to trigger warning (0.0-1.0)",
            "category": "Rate Limiting",
            "min": 0.0,
            "max": 1.0,
        },
        "input_history_size": {
            "type": "integer",
            "label": "Input History Size",
            "description": "Number of messages to keep in input history",
            "category": "Input History",
            "min": 0,
            "max": 200,
        },
        "save_input_history": {
            "type": "boolean",
            "label": "Save Input History",
            "description": "Persist input history between sessions",
            "category": "Input History",
        },
        "max_messages_per_room": {
            "type": "integer",
            "label": "Max Messages Per Room",
            "description": "Maximum messages to display per room",
            "category": "Message Display",
            "min": 50,
            "max": 2000,
        },
        "show_timestamps": {
            "type": "boolean",
            "label": "Show Timestamps",
            "description": "Display timestamps on messages",
            "category": "Message Display",
        },
        "timestamp_format": {
            "type": "string",
            "label": "Timestamp Format",
            "description": "strftime format for timestamps",
            "category": "Message Display",
        },
        "enable_notifications": {
            "type": "boolean",
            "label": "Enable Notifications",
            "description": "Enable desktop notifications (requires setup)",
            "category": "Notifications",
        },
        "notify_on_mention": {
            "type": "boolean",
            "label": "Notify on Mention",
            "description": "Show notification when mentioned",
            "category": "Notifications",
        },
        "notify_on_all_messages": {
            "type": "boolean",
            "label": "Notify on All Messages",
            "description": "Show notification for all messages",
            "category": "Notifications",
        },
        "auto_reconnect": {
            "type": "boolean",
            "label": "Auto Reconnect",
            "description": "Automatically reconnect on disconnect",
            "category": "Advanced",
        },
        "reconnect_delay_seconds": {
            "type": "integer",
            "label": "Reconnect Delay (seconds)",
            "description": "Delay before attempting reconnect",
            "category": "Advanced",
            "min": 1,
            "max": 300,
        },
        "connection_timeout_seconds": {
            "type": "integer",
            "label": "Connection Timeout (seconds)",
            "description": "Timeout for connection attempts",
            "category": "Advanced",
            "min": 5,
            "max": 120,
        },
        "enable_hub_discovery": {
            "type": "boolean",
            "label": "Enable Hub Discovery",
            "description": "Listen for hub announcements on network",
            "category": "Advanced",
        },
        "hub_discovery_cleanup_hours": {
            "type": "integer",
            "label": "Hub Discovery Cleanup (hours)",
            "description": "Remove discovered hubs not seen for this many hours",
            "category": "Advanced",
            "min": 1,
            "max": 168,
        },
    }
