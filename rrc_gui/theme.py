"""Theme and color management for RRC GUI."""

from __future__ import annotations

import wx


def is_dark_mode() -> bool:
    """Detect if the system is using a dark theme."""
    bg_color = wx.SystemSettings.GetColour(wx.SYS_COLOUR_WINDOW)
    luminance = (
        0.299 * bg_color.Red() + 0.587 * bg_color.Green() + 0.114 * bg_color.Blue()
    )
    return luminance < 128


def get_theme_colors() -> dict:
    """Get color scheme based on current theme."""
    if is_dark_mode():
        return {
            "own_message": wx.Colour(100, 149, 237),
            "notice": wx.Colour(144, 238, 144),
            "error": wx.Colour(255, 99, 71),
            "system": wx.Colour(169, 169, 169),
        }
    else:
        return {
            "own_message": wx.Colour(0, 0, 180),
            "notice": wx.Colour(0, 128, 0),
            "error": wx.RED,
            "system": wx.Colour(128, 128, 128),
        }
