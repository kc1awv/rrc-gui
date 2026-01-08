"""Entry point for RRC GUI client."""

import wx

from .config import load_config
from .gui import MainFrame
from .logging_manager import LogManager


def main():
    """Entry point for the GUI application."""
    config = load_config()
    log_manager = LogManager()
    log_manager.setup_logging(
        level=config.get("log_level", "INFO"),
        log_to_file=config.get("log_to_file", True),
        log_to_console=config.get("log_to_console", False),
        max_bytes=config.get("max_log_size_mb", 10) * 1024 * 1024,
        backup_count=config.get("log_backup_count", 5),
    )

    app = wx.App()
    frame = MainFrame()
    frame.Show()
    app.MainLoop()


if __name__ == "__main__":
    main()
