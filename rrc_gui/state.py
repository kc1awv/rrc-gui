"""State persistence APIs for RRC GUI."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


class StateManager:
    """Manages application state persistence."""

    def __init__(self, app_dir: Path | None = None):
        """Initialize state manager.

        Args:
            app_dir: Application directory for state files.
                     Defaults to ~/.rrc-gui
        """
        self.app_dir = app_dir or Path.home() / ".rrc-gui"
        self.app_dir.mkdir(parents=True, exist_ok=True)

    def get_state_file(self, name: str) -> Path:
        """Get path to a state file.

        Args:
            name: Name of the state file (without .json extension)

        Returns:
            Path to the state file
        """
        return self.app_dir / f"{name}.json"

    def load_state(self, name: str, default: Any = None) -> Any:
        """Load state from a file.

        Args:
            name: Name of the state file (without .json extension)
            default: Default value to return if file doesn't exist or is invalid

        Returns:
            Loaded state or default value
        """
        state_file = self.get_state_file(name)
        if not state_file.exists():
            return default

        try:
            with open(state_file, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return default

    def save_state(self, name: str, data: Any) -> bool:
        """Save state to a file.

        Args:
            name: Name of the state file (without .json extension)
            data: Data to save (must be JSON-serializable)

        Returns:
            True if successful, False otherwise
        """
        state_file = self.get_state_file(name)
        try:
            with open(state_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            os.chmod(state_file, 0o600)
            return True
        except Exception:
            return False

    def delete_state(self, name: str) -> bool:
        """Delete a state file.

        Args:
            name: Name of the state file (without .json extension)

        Returns:
            True if file was deleted, False otherwise
        """
        state_file = self.get_state_file(name)
        try:
            if state_file.exists():
                state_file.unlink()
                return True
            return False
        except Exception:
            return False

    def list_states(self) -> list[str]:
        """List all available state files.

        Returns:
            List of state file names (without .json extension)
        """
        try:
            return [f.stem for f in self.app_dir.glob("*.json") if f.is_file()]
        except Exception:
            return []

    def get_window_state(self) -> dict[str, Any]:
        """Get saved window state.

        Returns:
            Dictionary with window position, size, and other UI state
        """
        result = self.load_state(
            "window_state",
            {
                "size": [900, 600],
                "position": None,
                "maximized": False,
            },
        )
        return (
            result
            if isinstance(result, dict)
            else {
                "size": [900, 600],
                "position": None,
                "maximized": False,
            }
        )

    def save_window_state(
        self,
        size: tuple[int, int] | None = None,
        position: tuple[int, int] | None = None,
        maximized: bool = False,
    ) -> bool:
        """Save window state.

        Args:
            size: Window size (width, height)
            position: Window position (x, y)
            maximized: Whether window is maximized

        Returns:
            True if successful, False otherwise
        """
        current = self.get_window_state()

        if size is not None:
            current["size"] = list(size)
        if position is not None:
            current["position"] = list(position)
        current["maximized"] = maximized

        return self.save_state("window_state", current)

    def get_input_history(self, room: str) -> list[str]:
        """Get input history for a room.

        Args:
            room: Room name

        Returns:
            List of previous inputs
        """
        all_history = self.load_state("input_history", {})
        if isinstance(all_history, dict):
            result = all_history.get(room, [])
            return result if isinstance(result, list) else []
        return []

    def save_input_history(self, room: str, history: list[str]) -> bool:
        """Save input history for a room.

        Args:
            room: Room name
            history: List of inputs to save

        Returns:
            True if successful, False otherwise
        """
        all_history = self.load_state("input_history", {})
        all_history[room] = history
        return self.save_state("input_history", all_history)

    def clear_input_history(self, room: str | None = None) -> bool:
        """Clear input history.

        Args:
            room: Room name to clear, or None to clear all

        Returns:
            True if successful, False otherwise
        """
        if room is None:
            return self.delete_state("input_history")

        all_history = self.load_state("input_history", {})
        if room in all_history:
            del all_history[room]
            return self.save_state("input_history", all_history)
        return False
