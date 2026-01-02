"""Entry point for RRC GUI client."""

import logging
import os
import sys

import wx


class FilteredLog(wx.LogStderr):
    """Custom log handler that filters out specific wxGTK warnings."""

    def DoLogTextAtLevel(self, level, msg):
        """Filter out harmless wxGTK menubar focus warnings."""
        if (
            "menubar" in msg.lower()
            and "lost focus even though it didn't have it" in msg.lower()
        ):
            return  # Suppress this specific warning
        super().DoLogTextAtLevel(level, msg)


from .gui import MainFrame


def main():
    """Entry point for the GUI application."""
    log_level_name = os.environ.get("RRC_LOG_LEVEL", "INFO").upper()
    log_level = getattr(logging, log_level_name, logging.INFO)

    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        stream=sys.stderr,
    )

    wx.Log.SetActiveTarget(FilteredLog())

    app = wx.App()
    frame = MainFrame()
    frame.Show()
    app.MainLoop()


if __name__ == "__main__":
    main()
