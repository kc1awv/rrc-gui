"""Dialog classes for RRC GUI."""

from __future__ import annotations

import time

import wx
import wx.lib.scrolledpanel as scrolled

from .config import get_config_schema, load_config, save_config
from .ui_constants import (
    INPUT_HISTORY_SIZE,
    RATE_LIMIT_MESSAGES_PER_MINUTE,
    RATE_LIMIT_WARNING_THRESHOLD,
)


class ConnectionDialog(wx.Dialog):
    """Dialog for collecting connection parameters."""

    def __init__(self, parent):
        super().__init__(parent, title="Connect to RRC Hub", size=(450, 260))

        saved_config = load_config()

        self._identity_path = saved_config.get("identity_path", "~/.rrc-gui/identity")
        self._dest_name = saved_config.get("dest_name", "rrc.hub")
        self._configdir = saved_config.get("configdir", "")

        panel = wx.Panel(self)
        vbox = wx.BoxSizer(wx.VERTICAL)

        hbox1 = wx.BoxSizer(wx.HORIZONTAL)
        label1 = wx.StaticText(panel, label="Hub Hash:")
        hbox1.Add(label1, flag=wx.RIGHT | wx.ALIGN_CENTER_VERTICAL, border=8)
        self.hub_text = wx.TextCtrl(panel, value=saved_config.get("hub_hash", ""))
        hbox1.Add(self.hub_text, proportion=1)
        vbox.Add(hbox1, flag=wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, border=10)

        hbox2 = wx.BoxSizer(wx.HORIZONTAL)
        label2 = wx.StaticText(panel, label="Nickname:")
        hbox2.Add(label2, flag=wx.RIGHT | wx.ALIGN_CENTER_VERTICAL, border=8)
        self.nick_text = wx.TextCtrl(panel, value=saved_config.get("nickname", ""))
        hbox2.Add(self.nick_text, proportion=1)
        vbox.Add(hbox2, flag=wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, border=10)

        hbox3 = wx.BoxSizer(wx.HORIZONTAL)
        label3 = wx.StaticText(panel, label="Auto-join Room:")
        hbox3.Add(label3, flag=wx.RIGHT | wx.ALIGN_CENTER_VERTICAL, border=8)
        self.room_text = wx.TextCtrl(
            panel, value=saved_config.get("auto_join_room", "")
        )
        hbox3.Add(self.room_text, proportion=1)
        vbox.Add(hbox3, flag=wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, border=10)

        button_box = wx.BoxSizer(wx.HORIZONTAL)
        ok_btn = wx.Button(panel, wx.ID_OK, "Connect")
        cancel_btn = wx.Button(panel, wx.ID_CANCEL, "Cancel")
        button_box.Add(ok_btn)
        button_box.Add(cancel_btn, flag=wx.LEFT, border=5)
        vbox.Add(button_box, flag=wx.ALIGN_CENTER | wx.TOP | wx.BOTTOM, border=10)

        panel.SetSizer(vbox)

    def get_values(self):
        """Return the connection parameters as a dict."""
        return {
            "hub_hash": self.hub_text.GetValue().strip(),
            "nickname": self.nick_text.GetValue().strip(),
            "auto_join_room": self.room_text.GetValue().strip(),
            "identity_path": self._identity_path,
            "dest_name": self._dest_name or "rrc.hub",
            "configdir": self._configdir,
        }

    def Validate(self):
        """Validate dialog inputs before accepting."""
        hub_hash = self.hub_text.GetValue().strip()
        if not hub_hash:
            wx.MessageBox(
                "Hub hash is required.", "Validation Error", wx.OK | wx.ICON_ERROR
            )
            return False

        hex_only = (
            hub_hash.replace(":", "").replace(" ", "").replace("<", "").replace(">", "")
        )
        if not all(c in "0123456789abcdefABCDEF" for c in hex_only):
            wx.MessageBox(
                "Hub hash must be a valid hexadecimal string.",
                "Validation Error",
                wx.OK | wx.ICON_ERROR,
            )
            return False

        if len(hex_only) != 32:
            wx.MessageBox(
                f"Hub hash should be 32 hexadecimal characters (got {len(hex_only)}).\n"
                "A valid hash looks like: dbb6dc282cb3fca0f91ad812f204c031",
                "Validation Error",
                wx.OK | wx.ICON_WARNING,
            )

        return True


class PreferencesDialog(wx.Dialog):
    """Preferences dialog for colors and fonts."""

    def __init__(self, parent):
        super().__init__(parent, title="Preferences", size=(400, 300))

        panel = wx.Panel(self)
        vbox = wx.BoxSizer(wx.VERTICAL)

        color_box = wx.StaticBoxSizer(wx.VERTICAL, panel, "Message Colors")

        note = wx.StaticText(
            panel,
            label="Note: Color preferences are saved but currently\nuse system theme detection.",
        )
        color_box.Add(note, flag=wx.ALL, border=10)

        vbox.Add(color_box, flag=wx.ALL | wx.EXPAND, border=10)

        rate_box = wx.StaticBoxSizer(wx.VERTICAL, panel, "Rate Limiting")
        rate_text = wx.StaticText(
            panel,
            label=f"Client-side limit: {RATE_LIMIT_MESSAGES_PER_MINUTE} messages/minute\n"
            f"Warning at: {int(RATE_LIMIT_MESSAGES_PER_MINUTE * RATE_LIMIT_WARNING_THRESHOLD)} messages/minute",
        )
        rate_box.Add(rate_text, flag=wx.ALL, border=10)
        vbox.Add(rate_box, flag=wx.ALL | wx.EXPAND, border=10)

        history_box = wx.StaticBoxSizer(wx.VERTICAL, panel, "Input History")
        history_text = wx.StaticText(
            panel,
            label=f"History size: {INPUT_HISTORY_SIZE} messages\n"
            "Navigate with Up/Down arrow keys in message input",
        )
        history_box.Add(history_text, flag=wx.ALL, border=10)
        vbox.Add(history_box, flag=wx.ALL | wx.EXPAND, border=10)

        button_box = wx.BoxSizer(wx.HORIZONTAL)
        ok_btn = wx.Button(panel, wx.ID_OK, "OK")
        ok_btn.SetDefault()
        button_box.Add(ok_btn)
        vbox.Add(button_box, flag=wx.ALIGN_CENTER | wx.ALL, border=10)

        panel.SetSizer(vbox)

    def Validate(self):
        """Validate dialog inputs."""
        return True


class ConfigurationDialog(wx.Dialog):
    """Configuration dialog with tabbed interface for all settings."""

    def __init__(self, parent):
        super().__init__(parent, title="Configuration", size=(700, 600))

        self.config = load_config()
        self.original_config = self.config.copy()
        self.schema = get_config_schema()
        self.widgets = {}
        self.needs_restart = False

        panel = wx.Panel(self)
        vbox = wx.BoxSizer(wx.VERTICAL)

        notebook = wx.Notebook(panel)

        categories: dict[str, list[str]] = {}
        for key, meta in self.schema.items():
            category = meta.get("category", "Other")
            if category not in categories:
                categories[category] = []
            categories[category].append(key)

        for category in sorted(categories.keys()):
            page = self._create_category_page(notebook, category, categories[category])
            notebook.AddPage(page, category)

        vbox.Add(notebook, proportion=1, flag=wx.EXPAND | wx.ALL, border=10)

        button_box = wx.BoxSizer(wx.HORIZONTAL)
        save_btn = wx.Button(panel, wx.ID_OK, "Save")
        cancel_btn = wx.Button(panel, wx.ID_CANCEL, "Cancel")
        reset_btn = wx.Button(panel, label="Reset to Defaults")

        button_box.Add(save_btn)
        button_box.Add(cancel_btn, flag=wx.LEFT, border=5)
        button_box.AddStretchSpacer()
        button_box.Add(reset_btn)

        vbox.Add(button_box, flag=wx.ALIGN_CENTER | wx.ALL, border=10)

        panel.SetSizer(vbox)

        save_btn.Bind(wx.EVT_BUTTON, self.on_save)
        reset_btn.Bind(wx.EVT_BUTTON, self.on_reset)

    def _create_category_page(self, parent, category: str, keys: list[str]):
        """Create a scrolled panel for a category of settings."""
        panel = scrolled.ScrolledPanel(parent)
        panel.SetupScrolling()

        vbox = wx.BoxSizer(wx.VERTICAL)

        for key in sorted(keys):
            meta = self.schema[key]
            widget = self._create_widget(panel, key, meta)
            if widget:
                self.widgets[key] = widget

                hbox = wx.BoxSizer(wx.HORIZONTAL)
                label = wx.StaticText(panel, label=meta.get("label", key) + ":")
                label.SetMinSize((200, -1))
                hbox.Add(label, flag=wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, border=10)
                hbox.Add(widget, proportion=1, flag=wx.EXPAND)

                vbox.Add(hbox, flag=wx.EXPAND | wx.ALL, border=5)

                if "description" in meta:
                    desc = wx.StaticText(
                        panel,
                        label=meta["description"],
                        style=wx.ST_NO_AUTORESIZE,
                    )
                    desc.SetForegroundColour(
                        wx.SystemSettings.GetColour(wx.SYS_COLOUR_GRAYTEXT)
                    )
                    font = desc.GetFont()
                    font.SetPointSize(font.GetPointSize() - 1)
                    desc.SetFont(font)
                    desc.Wrap(500)
                    vbox.Add(desc, flag=wx.LEFT | wx.BOTTOM, border=5)

        panel.SetSizer(vbox)
        return panel

    def _create_widget(self, parent, key: str, meta: dict):
        """Create appropriate widget for a config value."""
        widget_type = meta.get("type", "string")
        value = self.config.get(key)

        if widget_type == "boolean":
            widget = wx.CheckBox(parent)
            widget.SetValue(bool(value))
            return widget

        elif widget_type == "integer":
            widget = wx.SpinCtrl(
                parent,
                min=meta.get("min", 0),
                max=meta.get("max", 10000),
                initial=int(value) if value is not None else 0,
            )
            return widget

        elif widget_type == "float":
            widget = wx.SpinCtrlDouble(
                parent,
                min=meta.get("min", 0.0),
                max=meta.get("max", 100.0),
                initial=float(value) if value is not None else 0.0,
                inc=0.1,
            )
            return widget

        elif widget_type == "choice":
            choices = meta.get("choices", [])
            widget = wx.Choice(parent, choices=choices)
            if value in choices:
                widget.SetSelection(choices.index(value))
            elif choices:
                widget.SetSelection(0)
            return widget

        elif widget_type in ("string", "path"):
            widget = wx.TextCtrl(parent, value=str(value) if value is not None else "")
            return widget

        else:
            widget = wx.TextCtrl(parent, value=str(value) if value is not None else "")
            return widget

    def on_save(self, event):
        """Save configuration."""
        for key, widget in self.widgets.items():
            meta = self.schema[key]
            widget_type = meta.get("type", "string")

            if widget_type == "boolean":
                self.config[key] = widget.GetValue()
            elif widget_type == "integer":
                self.config[key] = widget.GetValue()
            elif widget_type == "float":
                self.config[key] = widget.GetValue()
            elif widget_type == "choice":
                choices = meta.get("choices", [])
                selection = widget.GetSelection()
                if selection >= 0 and selection < len(choices):
                    self.config[key] = choices[selection]
            else:
                self.config[key] = widget.GetValue()

        self.needs_restart = False
        for key, value in self.config.items():
            meta = self.schema.get(key, {})
            if meta.get("requires_restart", False):
                if self.original_config.get(key) != value:
                    self.needs_restart = True
                    break

        save_config(self.config)
        self.EndModal(wx.ID_OK)

    def on_reset(self, event):
        """Reset all settings to defaults."""
        result = wx.MessageBox(
            "Are you sure you want to reset all settings to their default values?",
            "Reset Configuration",
            wx.YES_NO | wx.ICON_QUESTION,
        )

        if result == wx.YES:
            from .config import get_default_config

            self.config = get_default_config()

            for key, widget in self.widgets.items():
                meta = self.schema[key]
                widget_type = meta.get("type", "string")
                value = self.config.get(key)

                if widget_type == "boolean":
                    widget.SetValue(bool(value))
                elif widget_type == "integer":
                    widget.SetValue(int(value) if value is not None else 0)
                elif widget_type == "float":
                    widget.SetValue(float(value) if value is not None else 0.0)
                elif widget_type == "choice":
                    choices = meta.get("choices", [])
                    if value in choices:
                        widget.SetSelection(choices.index(value))
                else:
                    widget.SetValue(str(value) if value is not None else "")

    def get_config(self):
        """Get the configuration."""
        return self.config

    def requires_restart(self):
        """Check if changes require a restart."""
        return self.needs_restart


class DiscoveredHubsDialog(wx.Dialog):
    """Dialog for displaying and selecting discovered hubs."""

    def __init__(self, parent, discovered_hubs: dict):
        super().__init__(parent, title="Discovered Hubs", size=(600, 400))

        self.discovered_hubs = discovered_hubs
        self.selected_hub_hash = None

        panel = wx.Panel(self)
        vbox = wx.BoxSizer(wx.VERTICAL)

        info_text = wx.StaticText(panel, label="Select a hub to connect:")
        vbox.Add(info_text, flag=wx.ALL, border=10)

        self.hub_list = wx.ListCtrl(panel, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
        self.hub_list.InsertColumn(0, "Hub Name", width=200)
        self.hub_list.InsertColumn(1, "Hash", width=280)
        self.hub_list.InsertColumn(2, "Last Seen", width=100)

        self._populate_hub_list()

        vbox.Add(self.hub_list, proportion=1, flag=wx.EXPAND | wx.ALL, border=10)

        button_box = wx.BoxSizer(wx.HORIZONTAL)
        connect_btn = wx.Button(panel, wx.ID_OK, "Connect to Selected")
        cancel_btn = wx.Button(panel, wx.ID_CANCEL, "Cancel")
        button_box.Add(connect_btn)
        button_box.Add(cancel_btn, flag=wx.LEFT, border=5)
        vbox.Add(button_box, flag=wx.ALIGN_CENTER | wx.ALL, border=10)

        panel.SetSizer(vbox)

        self.hub_list.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self.on_hub_activated)
        connect_btn.Bind(wx.EVT_BUTTON, self.on_connect_clicked)

    def _populate_hub_list(self):
        """Populate the hub list with discovered hubs."""
        sorted_hubs = sorted(
            self.discovered_hubs.items(),
            key=lambda x: x[1].get("last_seen", 0),
            reverse=True,
        )

        for idx, (hash_hex, hub_info) in enumerate(sorted_hubs):
            name = hub_info.get("name", "Unknown")
            last_seen = hub_info.get("last_seen", 0)

            if last_seen > 0:
                elapsed = int(time.time() - last_seen)
                if elapsed < 60:
                    time_str = "Just now"
                elif elapsed < 3600:
                    time_str = f"{elapsed // 60}m ago"
                else:
                    time_str = f"{elapsed // 3600}h ago"
            else:
                time_str = "Unknown"

            index = self.hub_list.InsertItem(idx, name)
            self.hub_list.SetItem(index, 1, hash_hex)
            self.hub_list.SetItem(index, 2, time_str)

            self.hub_list.SetItemData(index, idx)

        if self.hub_list.GetItemCount() > 0:
            self.hub_list.Select(0)

    def on_hub_activated(self, event):
        """Handle double-click on hub item."""
        self.on_connect_clicked(event)

    def on_connect_clicked(self, event):
        """Handle connect button click."""
        selected = self.hub_list.GetFirstSelected()
        if selected == -1:
            wx.MessageBox(
                "Please select a hub to connect.",
                "No Selection",
                wx.OK | wx.ICON_WARNING,
            )
            return

        self.selected_hub_hash = self.hub_list.GetItemText(selected, 1)
        self.EndModal(wx.ID_OK)

    def get_selected_hub_hash(self):
        """Return the selected hub hash."""
        return self.selected_hub_hash


class RestartDialog(wx.Dialog):
    """Dialog prompting user to restart the application."""

    def __init__(self, parent):
        super().__init__(
            parent, title="Restart Required", size=(450, 200), style=wx.DEFAULT_DIALOG_STYLE
        )

        panel = wx.Panel(self)
        vbox = wx.BoxSizer(wx.VERTICAL)

        hbox_msg = wx.BoxSizer(wx.HORIZONTAL)
        
        icon = wx.ArtProvider.GetBitmap(wx.ART_INFORMATION, wx.ART_MESSAGE_BOX, (48, 48))
        icon_bitmap = wx.StaticBitmap(panel, bitmap=icon)
        hbox_msg.Add(icon_bitmap, flag=wx.ALL, border=10)

        msg_vbox = wx.BoxSizer(wx.VERTICAL)
        title_text = wx.StaticText(panel, label="Configuration Saved")
        font = title_text.GetFont()
        font.SetWeight(wx.FONTWEIGHT_BOLD)
        title_text.SetFont(font)
        msg_vbox.Add(title_text, flag=wx.BOTTOM, border=5)

        info_text = wx.StaticText(
            panel,
            label="Some settings require restarting the application to take effect.\n\n"
            "Would you like to restart now?",
        )
        msg_vbox.Add(info_text)

        hbox_msg.Add(msg_vbox, flag=wx.ALL, border=10)
        vbox.Add(hbox_msg, flag=wx.EXPAND)

        button_box = wx.BoxSizer(wx.HORIZONTAL)
        restart_btn = wx.Button(panel, wx.ID_YES, "Restart Now")
        later_btn = wx.Button(panel, wx.ID_NO, "Restart Later")
        
        restart_btn.SetDefault()
        button_box.Add(restart_btn)
        button_box.Add(later_btn, flag=wx.LEFT, border=5)
        vbox.Add(button_box, flag=wx.ALIGN_CENTER | wx.ALL, border=10)

        panel.SetSizer(vbox)
        self.Centre()

        restart_btn.Bind(wx.EVT_BUTTON, self.on_restart)
        later_btn.Bind(wx.EVT_BUTTON, self.on_later)

    def on_restart(self, event):
        """Handle Restart Now button."""
        self.EndModal(wx.ID_YES)

    def on_later(self, event):
        """Handle Restart Later button."""
        self.EndModal(wx.ID_NO)
