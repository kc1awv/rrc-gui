"""Entry point for RRC GUI client."""

import wx

from .gui import MainFrame


def main():
    """Entry point for the GUI application."""
    app = wx.App()
    frame = MainFrame()
    frame.Show()
    app.MainLoop()


if __name__ == "__main__":
    main()
