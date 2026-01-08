"""Theme and color management for RRC GUI."""

from __future__ import annotations

import wx


def is_dark_mode() -> bool:
    """Detect if the system is using a dark theme."""
    # Get system background color
    bg_color = wx.SystemSettings.GetColour(wx.SYS_COLOUR_WINDOW)
    # Calculate luminance (perceived brightness)
    # Formula: Y = 0.299*R + 0.587*G + 0.114*B
    luminance = (
        0.299 * bg_color.Red() + 0.587 * bg_color.Green() + 0.114 * bg_color.Blue()
    )
    # If luminance < 128, it's dark mode
    return bool(luminance < 128)


def get_theme_colors() -> dict:
    """Get color scheme based on current theme."""
    if is_dark_mode():
        # Dark mode: use lighter, more vibrant colors
        return {
            "own_message": wx.Colour(100, 149, 237),  # Cornflower blue (lighter)
            "notice": wx.Colour(144, 238, 144),  # Light green
            "error": wx.Colour(255, 99, 71),  # Tomato red (lighter)
            "system": wx.Colour(169, 169, 169),  # Light gray
        }
    else:
        # Light mode: use darker colors
        return {
            "own_message": wx.Colour(0, 0, 180),  # Dark blue
            "notice": wx.Colour(0, 128, 0),  # Dark green
            "error": wx.RED,  # Red
            "system": wx.Colour(128, 128, 128),  # Gray
        }
