"""Main GUI frame for RRC client."""

from __future__ import annotations

import json
import logging
import threading
import time
from datetime import datetime
from pathlib import Path

import cbor2
import RNS
import wx
import wx.richtext

from .client import Client, ClientConfig, parse_hash
from .config import load_config, save_config
from .constants import (
    B_JOINED_USERS,
    B_WELCOME_GREETING,
    B_WELCOME_HUB,
    K_BODY,
    K_ID,
    K_NICK,
    K_ROOM,
    K_SRC,
)
from .dialogs import ConnectionDialog, DiscoveredHubsDialog, PreferencesDialog
from .theme import get_theme_colors
from .ui_constants import (
    BUTTON_WIDTH,
    CONNECTION_TIMEOUT,
    DEFAULT_BORDER,
    INPUT_HISTORY_SIZE,
    MAX_MESSAGE_LENGTH,
    MAX_MESSAGES_PER_ROOM,
    PENDING_MESSAGE_TIMEOUT,
    RATE_LIMIT_MESSAGES_PER_MINUTE,
    RATE_LIMIT_WARNING_THRESHOLD,
    ROOM_LIST_WIDTH,
    USER_LIST_WIDTH,
)
from .utils import load_or_create_identity, normalize_room_name, sanitize_display_name

logger = logging.getLogger(__name__)

STALE_HUB_THRESHOLD_SECONDS = 3600
MAX_ANNOUNCE_DATA_SIZE = 10240
MAX_TIMESTAMP_SKEW_SECONDS = 300

_load_config = load_config
_save_config = save_config
_get_theme_colors = get_theme_colors
_load_or_create_identity = load_or_create_identity
_normalize_room_name = normalize_room_name


class HubAnnounceHandler:
    """Handler for RRC hub announcements on the Reticulum network."""

    def __init__(self, main_frame):
        """Initialize the announce handler.

        Args:
            main_frame: Reference to the MainFrame instance
        """
        self.main_frame = main_frame
        self.aspect_filter = "rrc.hub"

    def received_announce(
        self,
        destination_hash: bytes,
        announced_identity: RNS.Identity,  # noqa: ARG002
        app_data: bytes,
    ) -> None:
        """Handle received announces from the network.

        Args:
            destination_hash: Hash of the announcing destination
            announced_identity: Identity that made the announcement (unused)
            app_data: Application data from the announcement
        """
        try:
            hash_hex = destination_hash.hex()
            hub_name = None

            if app_data:
                if len(app_data) > MAX_ANNOUNCE_DATA_SIZE:
                    logger.warning(
                        f"Ignoring announce with oversized app_data: {len(app_data)} bytes"
                    )
                    return

                try:
                    decoded = cbor2.loads(app_data)
                    if isinstance(decoded, dict):
                        if decoded.get("proto") == "rrc" and "hub" in decoded:
                            hub_name = (
                                decoded["hub"]
                                if isinstance(decoded["hub"], str)
                                else None
                            )
                        else:
                            hub_name = (
                                decoded.get("name")
                                if isinstance(decoded.get("name"), str)
                                else (
                                    decoded.get("hub")
                                    if isinstance(decoded.get("hub"), str)
                                    else None
                                )
                            )
                    elif isinstance(decoded, str):
                        hub_name = decoded if len(decoded) <= 200 else None
                except Exception:
                    try:
                        hub_name = app_data.decode("utf-8")
                    except Exception:
                        pass

            if not hub_name:
                hub_name = f"Hub {hash_hex[:8]}"

            sanitized_hub_name = sanitize_display_name(hub_name, max_length=200)
            if not sanitized_hub_name:
                sanitized_hub_name = f"Hub {hash_hex[:8]}"

            logger.info(
                f"Discovered RRC hub: {sanitized_hub_name} ({hash_hex[:16]}...)"
            )

            self.main_frame.discovered_hubs[hash_hex] = {
                "hash": hash_hex,
                "name": sanitized_hub_name,
                "last_seen": time.time(),
            }

            wx.CallAfter(self.main_frame._save_discovered_hubs)
        except Exception as e:
            logger.exception(f"Error processing announcement: {e}")


class MainFrame(wx.Frame):
    """Main chat window."""

    def __init__(self):
        super().__init__(None, title="RRC Client", size=(900, 600))

        theme_colors = get_theme_colors()
        self.COLOR_OWN_MESSAGE = theme_colors["own_message"]
        self.COLOR_NOTICE = theme_colors["notice"]
        self.COLOR_ERROR = theme_colors["error"]
        self.COLOR_SYSTEM = theme_colors["system"]
        self.client: Client | None = None
        self.active_room: str | None = None
        self.nickname_map: dict[str, str] = {}
        self.own_identity_hash: str | None = None
        self.current_configdir: str | None = None
        self.is_connecting: bool = False
        self.pending_messages: dict[bytes, tuple[str, str, float, int | None]] = {}
        self.room_messages: dict[
            str, list[tuple[str, wx.Colour | None, bool, bool]]
        ] = {}
        self.HUB_ROOM = "[Hub]"
        self.room_messages[self.HUB_ROOM] = []
        self.room_users: dict[str, set[str]] = {}
        self.unread_counts: dict[str, int] = {}
        self.message_send_times: list[float] = []
        self.input_history: list[str] = []
        self.input_history_index: int = -1
        self.input_buffer: str = ""

        self.last_ping_time: float | None = None
        self.latency_ms: int | None = None

        self.room_operation_times: dict[str, list[float]] = {}
        self.room_op_rate_limit = 10
        self.room_op_rate_window = 5.0

        self.discovered_hubs: dict[str, dict] = {}
        self.announce_handler: HubAnnounceHandler | None = None
        self.hub_cache_path = Path.home() / ".rrc-gui" / "discovered_hubs.json"

        self._initialize_reticulum()

        config = _load_config()
        if "window_x" in config and "window_y" in config:
            self.SetPosition((config["window_x"], config["window_y"]))
        if "window_width" in config and "window_height" in config:
            self.SetSize((config["window_width"], config["window_height"]))

        self._create_menu_bar()

        panel = wx.Panel(self)
        main_sizer = wx.BoxSizer(wx.HORIZONTAL)

        left_box = wx.BoxSizer(wx.VERTICAL)

        room_label = wx.StaticText(panel, label="Rooms:")
        left_box.Add(room_label, flag=wx.ALL, border=DEFAULT_BORDER)
        self.room_list = wx.ListBox(panel, size=(ROOM_LIST_WIDTH, -1))
        self.room_list.Bind(wx.EVT_LISTBOX, self.on_room_select)
        self.room_list.Append(self.HUB_ROOM)
        self.room_list.SetSelection(0)
        self.active_room = self.HUB_ROOM
        left_box.Add(
            self.room_list, proportion=1, flag=wx.EXPAND | wx.ALL, border=DEFAULT_BORDER
        )

        room_btn_box = wx.BoxSizer(wx.HORIZONTAL)
        self.join_btn = wx.Button(panel, label="Join", size=(BUTTON_WIDTH, -1))
        self.part_btn = wx.Button(panel, label="Part", size=(BUTTON_WIDTH, -1))
        self.join_btn.Bind(wx.EVT_BUTTON, self.on_join_room)
        self.part_btn.Bind(wx.EVT_BUTTON, self.on_part_room)
        room_btn_box.Add(self.join_btn, flag=wx.RIGHT, border=DEFAULT_BORDER)
        room_btn_box.Add(self.part_btn)
        left_box.Add(room_btn_box, flag=wx.ALL | wx.ALIGN_CENTER, border=DEFAULT_BORDER)

        main_sizer.Add(left_box, flag=wx.EXPAND)

        right_box = wx.BoxSizer(wx.VERTICAL)

        self.active_room_label = wx.StaticText(panel, label="Active room: [Hub]")
        right_box.Add(self.active_room_label, flag=wx.ALL, border=DEFAULT_BORDER)

        self.message_display = wx.richtext.RichTextCtrl(
            panel, style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_WORDWRAP
        )
        right_box.Add(
            self.message_display,
            proportion=1,
            flag=wx.EXPAND | wx.ALL,
            border=DEFAULT_BORDER,
        )

        input_box = wx.BoxSizer(wx.HORIZONTAL)
        self.message_input = wx.TextCtrl(panel, style=wx.TE_PROCESS_ENTER)
        self.message_input.Bind(wx.EVT_TEXT_ENTER, self.on_send_message)
        self.message_input.Bind(wx.EVT_KEY_DOWN, self.on_input_key_down)
        input_box.Add(self.message_input, proportion=1, flag=wx.EXPAND)
        self.send_btn = wx.Button(panel, label="Send")
        self.send_btn.Bind(wx.EVT_BUTTON, self.on_send_message)
        input_box.Add(self.send_btn, flag=wx.LEFT, border=DEFAULT_BORDER)
        right_box.Add(input_box, flag=wx.EXPAND | wx.ALL, border=DEFAULT_BORDER)

        main_sizer.Add(right_box, proportion=1, flag=wx.EXPAND)

        self.users_outer_box = wx.BoxSizer(wx.VERTICAL)
        self.users_panel = wx.Panel(panel)
        users_box = wx.BoxSizer(wx.VERTICAL)
        users_label = wx.StaticText(self.users_panel, label="Users:")
        users_box.Add(users_label, flag=wx.ALL, border=DEFAULT_BORDER)
        self.users_list = wx.ListBox(self.users_panel, size=(USER_LIST_WIDTH, -1))
        users_box.Add(
            self.users_list,
            proportion=1,
            flag=wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM,
            border=DEFAULT_BORDER,
        )
        self.users_panel.SetSizer(users_box)
        self.users_outer_box.Add(self.users_panel, proportion=1, flag=wx.EXPAND)

        self.users_panel.Hide()
        self.users_panel_in_sizer = False

        panel.SetSizer(main_sizer)

        self.CreateStatusBar()
        self.SetStatusText("Not connected")

        self._set_controls_enabled(False)

        self.Bind(wx.EVT_CLOSE, self.on_close)

        self.Bind(wx.EVT_CHAR_HOOK, self.on_key_press)

        self.pending_check_timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self._check_pending_timeouts, self.pending_check_timer)
        self.pending_check_timer.Start(5000)

        self.status_update_timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self._update_status_display, self.status_update_timer)
        self.status_update_timer.Start(1000)

    def _initialize_reticulum(self):
        """Initialize Reticulum at startup."""
        try:
            config = _load_config()
            configdir = config.get("configdir") or None

            if RNS.Reticulum.get_instance() is None:
                RNS.Reticulum(configdir=configdir)
                self.current_configdir = configdir

            self._load_discovered_hubs()

            self.announce_handler = HubAnnounceHandler(self)
            RNS.Transport.register_announce_handler(self.announce_handler)
            logger.info("Hub discovery announce handler registered")

            self._cleanup_stale_hubs()
        except Exception as e:
            wx.MessageBox(
                f"Failed to initialize Reticulum: {e}\n\n"
                f"You will not be able to connect to hubs until you restart.",
                "Reticulum Warning",
                wx.OK | wx.ICON_WARNING,
            )

    def _load_discovered_hubs(self):
        """Load discovered hubs from cache file."""
        try:
            if self.hub_cache_path.exists():
                file_size = self.hub_cache_path.stat().st_size
                if file_size > 1024 * 1024:
                    logger.warning("Hub cache file too large, resetting")
                    self.discovered_hubs = {}
                    return

                with open(self.hub_cache_path, encoding="utf-8") as f:
                    data = json.load(f)

                if not isinstance(data, dict):
                    logger.warning("Hub cache has invalid format, resetting")
                    self.discovered_hubs = {}
                    return

                validated_hubs = {}
                for hash_hex, hub in data.items():
                    if not isinstance(hub, dict):
                        continue
                    if not all(key in hub for key in ["hash", "name", "last_seen"]):
                        continue
                    if not isinstance(hub.get("last_seen"), (int, float)):
                        continue

                    current_time = time.time()
                    last_seen = hub["last_seen"]
                    if (
                        last_seen < 0
                        or last_seen > current_time + MAX_TIMESTAMP_SKEW_SECONDS
                    ):
                        continue

                    validated_hubs[hash_hex] = hub

                self.discovered_hubs = validated_hubs
                logger.info(
                    f"Loaded {len(self.discovered_hubs)} discovered hub(s) from cache"
                )
        except json.JSONDecodeError:
            logger.error("Hub cache file is corrupted")
            self.discovered_hubs = {}
        except Exception as e:
            logger.error(f"Failed to load discovered hubs: {e}")
            self.discovered_hubs = {}

    def _save_discovered_hubs(self):
        """Save discovered hubs to cache file."""
        try:
            self.hub_cache_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.hub_cache_path, "w", encoding="utf-8") as f:
                json.dump(self.discovered_hubs, f, indent=2)
            logger.debug(
                f"Saved {len(self.discovered_hubs)} discovered hub(s) to cache"
            )
        except Exception as e:
            logger.error(f"Failed to save discovered hubs: {e}")

    def _cleanup_stale_hubs(self):
        """Remove hubs that haven't been seen in over 1 hour."""
        current_time = time.time()
        stale_hubs = [
            hash_hex
            for hash_hex, hub in self.discovered_hubs.items()
            if current_time - hub.get("last_seen", 0) > STALE_HUB_THRESHOLD_SECONDS
        ]
        for hash_hex in stale_hubs:
            del self.discovered_hubs[hash_hex]
            logger.info(f"Removed stale hub: {hash_hex[:16]}...")

        if stale_hubs:
            self._save_discovered_hubs()

    def _create_menu_bar(self):
        menu_bar = wx.MenuBar()

        file_menu = wx.Menu()
        self.connect_menu_item = file_menu.Append(
            wx.ID_ANY, "&Connect\tCtrl-N", "Connect to hub"
        )
        self.disconnect_menu_item = file_menu.Append(
            wx.ID_ANY, "&Disconnect\tCtrl-D", "Disconnect from hub"
        )
        file_menu.AppendSeparator()
        discovered_hubs_item = file_menu.Append(
            wx.ID_ANY, "Discovered &Hubs...", "View and connect to discovered hubs"
        )
        file_menu.AppendSeparator()
        prefs_item = file_menu.Append(
            wx.ID_PREFERENCES, "&Preferences...", "Configure colors and fonts"
        )
        file_menu.AppendSeparator()
        quit_item = file_menu.Append(wx.ID_EXIT, "&Quit\tCtrl-Q", "Quit application")

        self.Bind(wx.EVT_MENU, self.on_connect_menu, self.connect_menu_item)
        self.Bind(wx.EVT_MENU, self.on_disconnect_menu, self.disconnect_menu_item)
        self.Bind(wx.EVT_MENU, self.on_discovered_hubs, discovered_hubs_item)
        self.Bind(wx.EVT_MENU, self.on_preferences, prefs_item)
        self.Bind(wx.EVT_MENU, self.on_quit, quit_item)

        self.disconnect_menu_item.Enable(False)

        menu_bar.Append(file_menu, "&File")
        self.SetMenuBar(menu_bar)

    def _on_connection_success(self):
        """Handle successful connection."""
        self.is_connecting = False
        self._update_status_display()
        self._set_controls_enabled(True)
        self.connect_menu_item.Enable(False)
        self.disconnect_menu_item.Enable(True)

    def _on_connection_failed(self, error_msg: str):
        """Handle connection failure."""
        self.is_connecting = False
        self.client = None
        self._update_status_display()
        self.connect_menu_item.Enable(True)
        self.disconnect_menu_item.Enable(False)
        wx.MessageBox(error_msg, "Connection Error", wx.OK | wx.ICON_ERROR)

    def _update_status_display(self, event=None):
        """Update status bar with connection state and pending message count."""
        if self.is_connecting:
            icon = "🟡"
            status = "Connecting..."
        elif self.client:
            icon = "🟢"
            status = "Connected"
        else:
            icon = "🔴"
            status = "Not connected"

        pending_count = len(self.pending_messages)
        if pending_count > 0:
            status += f" | Sending: {pending_count}"

        if self.latency_ms is not None and self.client:
            status += f" | {self.latency_ms}ms"

        self.SetStatusText(f"{icon} {status}")

    def on_input_key_down(self, event):
        """Handle input history navigation with up/down arrows."""
        keycode = event.GetKeyCode()

        if keycode == wx.WXK_UP:
            if self.input_history:
                if self.input_history_index == -1:
                    self.input_buffer = self.message_input.GetValue()
                    self.input_history_index = len(self.input_history) - 1
                elif self.input_history_index > 0:
                    self.input_history_index -= 1

                if 0 <= self.input_history_index < len(self.input_history):
                    self.message_input.SetValue(
                        self.input_history[self.input_history_index]
                    )
                    self.message_input.SetInsertionPointEnd()
            return

        elif keycode == wx.WXK_DOWN:
            if self.input_history_index != -1:
                if self.input_history_index < len(self.input_history) - 1:
                    self.input_history_index += 1
                    self.message_input.SetValue(
                        self.input_history[self.input_history_index]
                    )
                    self.message_input.SetInsertionPointEnd()
                else:
                    self.input_history_index = -1
                    self.message_input.SetValue(self.input_buffer)
                    self.message_input.SetInsertionPointEnd()
            return

        event.Skip()

    def on_key_press(self, event):
        """Handle keyboard shortcuts."""
        keycode = event.GetKeyCode()

        if event.AltDown() and ord("1") <= keycode <= ord("9"):
            room_index = keycode - ord("1")
            if room_index < self.room_list.GetCount():
                self.room_list.SetSelection(room_index)
                room = self.room_list.GetString(room_index)
                self._set_active_room(room)
            return

        if event.AltDown():
            if keycode == wx.WXK_UP:
                current = self.room_list.GetSelection()
                if current > 0:
                    self.room_list.SetSelection(current - 1)
                    room = self.room_list.GetString(current - 1)
                    self._set_active_room(room)
                return
            elif keycode == wx.WXK_DOWN:
                current = self.room_list.GetSelection()
                if current < self.room_list.GetCount() - 1:
                    self.room_list.SetSelection(current + 1)
                    room = self.room_list.GetString(current + 1)
                    self._set_active_room(room)
                return

        event.Skip()

    def _check_pending_timeouts(self, event):
        """Check for pending messages that have timed out and mark them as failed."""
        if not self.pending_messages:
            return

        current_time = time.time()
        timed_out = []

        for mid, (room, text, sent_time, index) in list(self.pending_messages.items()):
            if current_time - sent_time <= PENDING_MESSAGE_TIMEOUT:
                continue
            timed_out.append(mid)

            if room not in self.room_messages:
                continue

            messages = self.room_messages[room]
            message_index: int | None = None
            if isinstance(index, int) and 0 <= index < len(messages):
                msg_text, msg_color, _msg_bold, msg_italic = messages[index]
                if msg_italic and msg_color == self.COLOR_SYSTEM and text in msg_text:
                    message_index = index
            if message_index is None:
                for i in range(len(messages) - 1, -1, -1):
                    msg_text, msg_color, _msg_bold, msg_italic = messages[i]
                    if (
                        msg_italic
                        and msg_color == self.COLOR_SYSTEM
                        and text in msg_text
                    ):
                        message_index = i
                        break

            if message_index is None:
                continue

            timestamp = datetime.now().strftime("%H:%M:%S")
            user = (
                self._format_user(bytes.fromhex(self.own_identity_hash))
                if self.own_identity_hash
                else "you"
            )
            messages[message_index] = (
                f"[{timestamp}] [{room}] {user}: {text} [FAILED - not delivered]\n",
                self.COLOR_ERROR,
                False,
                True,
            )
            if room == self.active_room:
                self._reload_room_messages()

        for mid in timed_out:
            self.pending_messages.pop(mid, None)

    def _update_theme_colors(self):
        """Update color constants based on current theme."""
        theme_colors = _get_theme_colors()
        self.COLOR_OWN_MESSAGE = theme_colors["own_message"]
        self.COLOR_NOTICE = theme_colors["notice"]
        self.COLOR_ERROR = theme_colors["error"]
        self.COLOR_SYSTEM = theme_colors["system"]

    def _set_controls_enabled(self, enabled: bool):
        """Enable/disable controls based on connection state."""
        self.room_list.Enable(enabled)
        self.join_btn.Enable(enabled)
        self.part_btn.Enable(enabled)
        self.message_input.Enable(enabled)
        self.send_btn.Enable(enabled)

    def _format_user(self, src: bytes | bytearray | str) -> str:
        """Format a user identity for display, using nickname if available."""
        if not isinstance(src, (bytes, bytearray)):
            return str(src)

        src_hex_full = src.hex()
        src_hex_short = src_hex_full[:12]

        if self.own_identity_hash and src_hex_full == self.own_identity_hash:
            own_nick = self.nickname_map.get(src_hex_full, "")
            if own_nick:
                return f"{own_nick} (you)"
            return f"{src_hex_short}… (you)"

        nick: str | None = self.nickname_map.get(src_hex_full)
        if nick:
            return f"{nick} <{src_hex_short}…>"

        return f"{src_hex_short}…"

    def _append_styled_message(
        self,
        text: str,
        color: wx.Colour | None = None,
        bold: bool = False,
        italic: bool = False,
        room: str | None = None,
    ) -> int:
        """Append text to message display with styling and store in room history."""
        target_room = room or self.active_room or self.HUB_ROOM

        if target_room not in self.room_messages:
            self.room_messages[target_room] = []

        self.room_messages[target_room].append((text, color, bold, italic))
        appended_index = len(self.room_messages[target_room]) - 1

        if target_room != self.active_room and target_room != self.HUB_ROOM:
            self.unread_counts[target_room] = self.unread_counts.get(target_room, 0) + 1
            wx.CallAfter(self._update_room_list_display)

        if len(self.room_messages[target_room]) > MAX_MESSAGES_PER_ROOM:
            dropped = len(self.room_messages[target_room]) - MAX_MESSAGES_PER_ROOM
            self.room_messages[target_room] = self.room_messages[target_room][
                -MAX_MESSAGES_PER_ROOM:
            ]
            appended_index = max(0, appended_index - dropped)

            if self.pending_messages and dropped > 0:
                for mid, (
                    pending_room,
                    pending_text,
                    pending_sent,
                    pending_index,
                ) in list(self.pending_messages.items()):
                    if pending_room != target_room:
                        continue
                    if pending_index is None:
                        continue
                    new_index = pending_index - dropped
                    self.pending_messages[mid] = (
                        pending_room,
                        pending_text,
                        pending_sent,
                        new_index if new_index >= 0 else None,
                    )

        if target_room != self.active_room:
            return appended_index

        if not self.IsShown() or self.message_display.GetSize().GetWidth() <= 0:
            return appended_index

        self.message_display.MoveEnd()

        attr = wx.richtext.RichTextAttr()
        if color:
            attr.SetTextColour(color)
        if bold:
            attr.SetFontWeight(wx.FONTWEIGHT_BOLD)
        if italic:
            attr.SetFontStyle(wx.FONTSTYLE_ITALIC)

        if color:
            self.message_display.BeginTextColour(color)
        if bold:
            self.message_display.BeginBold()
        if italic:
            self.message_display.BeginItalic()

        self.message_display.WriteText(text)

        if italic:
            self.message_display.EndItalic()
        if bold:
            self.message_display.EndBold()
        if color:
            self.message_display.EndTextColour()

        self.message_display.MoveEnd()
        self.message_display.ShowPosition(self.message_display.GetLastPosition())

        return appended_index

    def on_discovered_hubs(self, event):
        """Show discovered hubs dialog."""
        if not self.discovered_hubs:
            wx.MessageBox(
                "No hubs have been discovered yet.\n\n"
                "Hubs will appear here automatically as they announce themselves on the network.",
                "No Hubs Found",
                wx.OK | wx.ICON_INFORMATION,
            )
            return

        dlg = DiscoveredHubsDialog(self, self.discovered_hubs)
        result = dlg.ShowModal()

        if result == wx.ID_OK:
            selected_hash = dlg.get_selected_hub_hash()
            if selected_hash:
                self._connect_to_hub_hash(selected_hash)

        dlg.Destroy()

    def _connect_to_hub_hash(self, hub_hash: str):
        """Open connection dialog with pre-filled hub hash."""
        config = _load_config()
        config["hub_hash"] = hub_hash
        _save_config(config)

        dlg = ConnectionDialog(self)
        if dlg.ShowModal() == wx.ID_OK:
            values = dlg.get_values()
            dlg.Destroy()

            _save_config(values)

            self.is_connecting = True
            self._update_status_display()
            self.connect_menu_item.Enable(False)

            if RNS.Reticulum.get_instance() is None:
                wx.MessageBox(
                    "Reticulum is not initialized.\n\n"
                    "Please restart the application.",
                    "Reticulum Error",
                    wx.OK | wx.ICON_ERROR,
                )
                self.is_connecting = False
                self.connect_menu_item.Enable(True)
                self.SetStatusText("Not connected")
                return

            configdir = values.get("configdir") or None
            if configdir != self.current_configdir:
                wx.MessageBox(
                    f"Reticulum is already initialized with a different config directory.\n"
                    f"Current: {self.current_configdir or '(default)'}\n"
                    f"Requested: {configdir or '(default)'}\n\n"
                    f"Please restart the application to use a different config directory.",
                    "Config Directory Mismatch",
                    wx.OK | wx.ICON_WARNING,
                )
                self.is_connecting = False
                self.connect_menu_item.Enable(True)
                return

            thread = threading.Thread(
                target=self._connect_thread, args=(values,), daemon=True
            )
            thread.start()
        else:
            dlg.Destroy()

    def on_connect_menu(self, event):
        """Show connection dialog and connect to hub."""
        if self.client or self.is_connecting:
            return

        dlg = ConnectionDialog(self)
        result = dlg.ShowModal()
        if result == wx.ID_OK:
            if not dlg.Validate():
                dlg.Destroy()
                return

            values = dlg.get_values()
            dlg.Destroy()

            _save_config(values)

            self.is_connecting = True
            self._update_status_display()
            self.connect_menu_item.Enable(False)

            if RNS.Reticulum.get_instance() is None:
                wx.MessageBox(
                    "Reticulum is not initialized.\n\n"
                    "Please restart the application.",
                    "Reticulum Error",
                    wx.OK | wx.ICON_ERROR,
                )
                self.is_connecting = False
                self.connect_menu_item.Enable(True)
                self.SetStatusText("Not connected")
                return

            configdir = values.get("configdir") or None
            if configdir != self.current_configdir:
                wx.MessageBox(
                    f"Reticulum is already initialized with a different config directory.\n"
                    f"Current: {self.current_configdir or '(default)'}\n"
                    f"Requested: {configdir or '(default)'}\n\n"
                    f"Please restart the application to use a different config directory.",
                    "Config Directory Mismatch",
                    wx.OK | wx.ICON_WARNING,
                )
                self.is_connecting = False
                self.connect_menu_item.Enable(True)
                return

            thread = threading.Thread(
                target=self._connect_thread, args=(values,), daemon=True
            )
            thread.start()
        else:
            dlg.Destroy()

    def _connect_thread(self, values: dict):
        """Connect to the hub (runs in background thread)."""
        try:
            print(f"[DEBUG] _connect_thread started with values: {values.keys()}")
            wx.CallAfter(self.SetStatusText, "Connecting...")

            if RNS.Reticulum.get_instance() is None:
                print("[DEBUG] ERROR: Reticulum not initialized")
                wx.CallAfter(
                    self._on_connection_failed,
                    "Reticulum not initialized. Please try again.",
                )
                return

            print(f"[DEBUG] Loading identity from: {values['identity_path']}")
            identity = _load_or_create_identity(values["identity_path"])
            print(f"[DEBUG] Identity loaded: {identity.hash.hex()[:16]}...")

            own_identity_hash = identity.hash.hex()
            nickname = values.get("nickname", "")
            if nickname:
                print(f"[DEBUG] Set nickname: {nickname}")

            print(f"[DEBUG] Creating client with dest_name={values['dest_name']}")
            config = ClientConfig(dest_name=values["dest_name"])
            client = Client(identity, config, nickname=nickname if nickname else None)

            client.on_message = lambda env: wx.CallAfter(self._on_message, env)
            client.on_notice = lambda env: wx.CallAfter(self._on_notice, env)
            client.on_error = lambda env: wx.CallAfter(self._on_error, env)
            client.on_welcome = lambda env: wx.CallAfter(self._on_welcome, env)
            client.on_joined = lambda room, env: wx.CallAfter(
                self._on_joined, room, env
            )
            client.on_parted = lambda room, env: wx.CallAfter(
                self._on_parted, room, env
            )
            client.on_close = lambda: wx.CallAfter(self._on_close)
            client.on_resource_warning = lambda msg: wx.CallAfter(
                self._on_resource_warning, msg
            )
            client.on_pong = lambda env: wx.CallAfter(self._on_pong, env)

            print(f"[DEBUG] Parsing hub hash: {values['hub_hash']}")
            hub_hash = parse_hash(values["hub_hash"])
            print(f"[DEBUG] Parsed hub hash: {hub_hash.hex()}")
            print(f"[DEBUG] Calling client.connect() with timeout={CONNECTION_TIMEOUT}")
            client.connect(
                hub_hash, wait_for_welcome=True, timeout_s=CONNECTION_TIMEOUT
            )

            print("[DEBUG] client.connect() returned successfully")

            auto_join_room = values.get("auto_join_room", "")

            def _commit_connection() -> None:
                self.client = client
                self.own_identity_hash = own_identity_hash
                if nickname:
                    self.nickname_map[own_identity_hash] = nickname

                self._on_connection_success()

                if auto_join_room:
                    room = _normalize_room_name(auto_join_room)
                    if room:
                        try:
                            client.join(room)
                        except Exception:
                            pass

            wx.CallAfter(_commit_connection)

        except OSError as e:
            wx.CallAfter(self._on_connection_failed, f"Network error: {e}")
        except ValueError as e:
            wx.CallAfter(
                self._on_connection_failed, f"Invalid connection parameter: {e}"
            )
        except Exception as e:
            wx.CallAfter(self._on_connection_failed, f"Failed to connect: {e}")

    def on_disconnect_menu(self, event):
        """Disconnect from hub."""
        if self.client:
            try:
                self.client.close()
            except Exception:
                pass

            self.client = None
            self.is_connecting = False
            self.pending_messages.clear()
            self.nickname_map.clear()
            self.own_identity_hash = None
            self.room_list.Clear()
            self.room_list.Append(self.HUB_ROOM)
            self.room_list.SetSelection(0)
            hub_msgs = self.room_messages.get(self.HUB_ROOM, [])
            self.room_messages.clear()
            self.room_messages[self.HUB_ROOM] = hub_msgs
            self.room_users.clear()
            self._set_active_room(self.HUB_ROOM)
            self._set_controls_enabled(False)
            self._update_status_display()
            self.connect_menu_item.Enable(True)
            self.disconnect_menu_item.Enable(False)

    def on_preferences(self, event):
        """Show preferences dialog."""
        dlg = PreferencesDialog(self)
        if dlg.ShowModal() == wx.ID_OK:
            theme_colors = _get_theme_colors()
            self.COLOR_OWN_MESSAGE = theme_colors["own_message"]
            self.COLOR_NOTICE = theme_colors["notice"]
            self.COLOR_ERROR = theme_colors["error"]
            self.COLOR_SYSTEM = theme_colors["system"]

            if self.active_room:
                self._reload_room_messages()
        dlg.Destroy()

    def on_quit(self, event):
        """Quit the application."""
        self.Close()

    def on_close(self, event):
        """Handle window close."""
        if hasattr(self, "pending_check_timer"):
            if self.pending_check_timer and self.pending_check_timer.IsRunning():
                self.pending_check_timer.Stop()
        if hasattr(self, "status_update_timer"):
            if self.status_update_timer and self.status_update_timer.IsRunning():
                self.status_update_timer.Stop()

        config = _load_config()
        pos = self.GetPosition()
        size = self.GetSize()
        config["window_x"] = pos.x
        config["window_y"] = pos.y
        config["window_width"] = size.width
        config["window_height"] = size.height
        _save_config(config)

        if self.client:
            self.client.close()
        self.Destroy()

    def on_room_select(self, event):
        """Handle room selection from list."""
        sel = self.room_list.GetSelection()
        if sel != wx.NOT_FOUND:
            room = self.room_list.GetString(sel)
            self._set_active_room(room)

    def _set_active_room(self, room: str):
        """Set the active room for sending messages and update display."""
        self.active_room = room
        self.active_room_label.SetLabel(f"Active room: {room}")

        if room in self.unread_counts:
            self.unread_counts[room] = 0
            self._update_room_list_display()

        idx = self.room_list.FindString(room)
        if idx != wx.NOT_FOUND:
            self.room_list.SetSelection(idx)

        panel = self.users_panel.GetParent()
        main_sizer = panel.GetSizer()

        if room == self.HUB_ROOM:
            if self.users_panel_in_sizer:
                main_sizer.Detach(self.users_outer_box)
                self.users_panel.Hide()
                self.users_panel_in_sizer = False
        else:
            if not self.users_panel_in_sizer:
                main_sizer.Add(self.users_outer_box, flag=wx.EXPAND)
                self.users_panel.Show()
                self.users_panel_in_sizer = True

        panel.Layout()

        self._reload_room_messages()

    def _reload_room_messages(self):
        """Reload the message display with current room's history."""
        if not self.IsShown() or self.message_display.GetSize().GetWidth() <= 0:
            return

        self.message_display.Clear()

        room = self.active_room or self.HUB_ROOM
        messages = self.room_messages.get(room, [])

        for text, color, bold, italic in messages:
            self.message_display.MoveEnd()

            if color:
                self.message_display.BeginTextColour(color)
            if bold:
                self.message_display.BeginBold()
            if italic:
                self.message_display.BeginItalic()

            self.message_display.WriteText(text)

            if italic:
                self.message_display.EndItalic()
            if bold:
                self.message_display.EndBold()
            if color:
                self.message_display.EndTextColour()

        self.message_display.MoveEnd()
        self.message_display.ShowPosition(self.message_display.GetLastPosition())

        self._update_user_list()

    def _update_room_list_display(self):
        """Update room list with unread message indicators."""
        current_sel = self.room_list.GetSelection()
        current_room = (
            self.room_list.GetString(current_sel)
            if current_sel != wx.NOT_FOUND
            else None
        )

        rooms = [self.room_list.GetString(i) for i in range(self.room_list.GetCount())]
        self.room_list.Clear()

        for room in rooms:
            clean_room = room.split(" (")[0] if " (" in room else room

            unread = self.unread_counts.get(clean_room, 0)
            if unread > 0 and clean_room != self.active_room:
                display = f"{clean_room} ({unread})"
            else:
                display = clean_room

            self.room_list.Append(display)

        if current_room:
            for i in range(self.room_list.GetCount()):
                if self.room_list.GetString(i).startswith(current_room.split(" (")[0]):
                    self.room_list.SetSelection(i)
                    break

    def _update_user_list(self):
        """Update the user list for the active room."""
        self.users_list.Clear()

        room = self.active_room
        if not room or room == self.HUB_ROOM:
            return

        users = self.room_users.get(room, set())
        if not users:
            return

        user_entries = []
        for user_hash in users:
            nick = self.nickname_map.get(user_hash)
            if nick:
                display = f"{nick} <{user_hash[:12]}…>"
            else:
                display = f"{user_hash[:12]}…"

            if user_hash == self.own_identity_hash:
                display += " (you)"

            user_entries.append((display, user_hash))

        user_entries.sort(key=lambda x: x[0].lower())

        for display, _ in user_entries:
            self.users_list.Append(display)

    def on_join_room(self, event):
        """Join a new room."""
        if not self.client:
            return

        dlg = wx.TextEntryDialog(self, "Enter room name:", "Join Room")
        if dlg.ShowModal() == wx.ID_OK:
            raw_room = dlg.GetValue()

            if " " in raw_room:
                wx.MessageBox(
                    "Room names cannot contain spaces.\n\n"
                    "Use hyphens (-) or underscores (_) instead.\n"
                    "Example: 'test-2' or 'test_2'",
                    "Invalid Room Name",
                    wx.OK | wx.ICON_WARNING,
                )
                dlg.Destroy()
                return

            room = _normalize_room_name(raw_room)
            if room:
                if self.room_list.FindString(room) != wx.NOT_FOUND:
                    wx.MessageBox(
                        f"Already in room '{room}'.",
                        "Already Joined",
                        wx.OK | wx.ICON_INFORMATION,
                    )
                else:
                    self.client.join(room)
        dlg.Destroy()

    def on_part_room(self, event):
        """Leave the active room."""
        if not self.client or not self.active_room:
            return

        if self.active_room == self.HUB_ROOM:
            return

        room_to_part = self.active_room

        result = wx.MessageBox(
            f"Leave room '{room_to_part}'?\n\nMessage history will be preserved.",
            "Confirm Part",
            wx.YES_NO | wx.NO_DEFAULT | wx.ICON_QUESTION,
        )

        if result == wx.YES:
            self.client.part(room_to_part)

    def on_send_message(self, event):
        """Send a message to the active room."""
        if not self.client or not self.active_room:
            return

        text = self.message_input.GetValue().strip()
        if not text:
            return

        if text.startswith("/"):
            self._handle_command(text)
            self.message_input.Clear()
            return

        if self.active_room == self.HUB_ROOM:
            wx.MessageBox(
                "Cannot send messages to [Hub]. Join a room first or use /join <room>.",
                "Hub Messages",
                wx.OK | wx.ICON_INFORMATION,
            )
            return

        current_time = time.time()
        self.message_send_times = [
            t for t in self.message_send_times if current_time - t < 60
        ]

        if len(self.message_send_times) >= RATE_LIMIT_MESSAGES_PER_MINUTE:
            wx.MessageBox(
                f"Rate limit: maximum {RATE_LIMIT_MESSAGES_PER_MINUTE} messages per minute.\n\nPlease wait a moment before sending.",
                "Sending Too Fast",
                wx.OK | wx.ICON_WARNING,
            )
            return
        elif len(self.message_send_times) >= int(
            RATE_LIMIT_MESSAGES_PER_MINUTE * RATE_LIMIT_WARNING_THRESHOLD
        ):
            self.SetStatusText(
                f"WARNING: Approaching rate limit ({len(self.message_send_times)}/{RATE_LIMIT_MESSAGES_PER_MINUTE} msgs/min)"
            )

        if len(text) > MAX_MESSAGE_LENGTH:
            wx.MessageBox(
                f"Message too long ({len(text)} characters).\n\nMaximum length is {MAX_MESSAGE_LENGTH} characters.",
                "Message Too Long",
                wx.OK | wx.ICON_WARNING,
            )
            return

        try:
            mid = self.client.msg(self.active_room, text)
        except Exception as e:
            if "MessageTooLargeError" not in str(type(e).__name__):
                wx.MessageBox(
                    f"Failed to send message: {e}",
                    "Send Error",
                    wx.OK | wx.ICON_ERROR,
                )
            return

        if self.own_identity_hash:
            timestamp = datetime.now().strftime("%H:%M:%S")
            send_time = time.time()
            user = self._format_user(bytes.fromhex(self.own_identity_hash))

            placeholder_index = self._append_styled_message(
                f"[{timestamp}] [{self.active_room}] {user}: {text}\n",
                color=self.COLOR_SYSTEM,
                italic=True,
                room=self.active_room,
            )
            self.pending_messages[mid] = (
                self.active_room,
                text,
                send_time,
                placeholder_index,
            )

        if text not in self.input_history or self.input_history[-1] != text:
            self.input_history.append(text)
            if len(self.input_history) > INPUT_HISTORY_SIZE:
                self.input_history.pop(0)

        self.input_history_index = -1
        self.input_buffer = ""

        self.message_send_times.append(time.time())

        self.message_input.Clear()

    def _check_room_operation_rate_limit(self, operation_key: str) -> bool:
        """Check if room operation is within rate limit.

        Args:
            operation_key: Unique key for this operation (e.g., 'join:room_name')

        Returns:
            True if operation is allowed, False if rate limited
        """
        now = time.time()
        if operation_key not in self.room_operation_times:
            self.room_operation_times[operation_key] = []

        self.room_operation_times[operation_key] = [
            t
            for t in self.room_operation_times[operation_key]
            if now - t < self.room_op_rate_window
        ]

        if len(self.room_operation_times[operation_key]) >= self.room_op_rate_limit:
            return False

        self.room_operation_times[operation_key].append(now)
        return True

    def _handle_command(self, text: str):
        """Handle slash commands.

        Args:
            text: Command text starting with /
        """
        parts = text.split(maxsplit=1)
        cmd = parts[0].lower()
        timestamp = datetime.now().strftime("%H:%M:%S")

        if cmd == "/join":
            if len(parts) < 2:
                self._append_styled_message(
                    f"[{timestamp}] Usage: /join <room>\n",
                    color=self.COLOR_ERROR,
                    room=self.active_room,
                )
                return

            room_name = parts[1].strip()
            if " " in room_name:
                wx.MessageBox(
                    "Room names cannot contain spaces.\n\n"
                    "Use hyphens (-) or underscores (_) instead.\n"
                    "Example: 'test-2' or 'test_2'",
                    "Invalid Room Name",
                    wx.OK | wx.ICON_WARNING,
                )
                return

            room = _normalize_room_name(room_name)
            if room:
                if self.room_list.FindString(room) != wx.NOT_FOUND:
                    self._append_styled_message(
                        f"[{timestamp}] Already in room '{room}'\n",
                        color=self.COLOR_NOTICE,
                        room=self.active_room,
                    )
                else:
                    if not self._check_room_operation_rate_limit(f"join:{room}"):
                        self._append_styled_message(
                            f"[{timestamp}] Too many join requests. Please wait a moment.\n",
                            color=self.COLOR_ERROR,
                            room=self.active_room,
                        )
                        return

                    if not self.client:
                        return

                    try:
                        self.client.join(room)
                    except Exception as e:
                        self._append_styled_message(
                            f"[{timestamp}] Failed to join room: {e}\n",
                            color=self.COLOR_ERROR,
                            room=self.active_room,
                        )

        elif cmd == "/part":
            if len(parts) > 1:
                part_room: str | None = _normalize_room_name(parts[1].strip())
            else:
                part_room = (
                    self.active_room if self.active_room != self.HUB_ROOM else None
                )

            if not part_room:
                self._append_styled_message(
                    f"[{timestamp}] Usage: /part [room] - specify a room or use from a room window\n",
                    color=self.COLOR_ERROR,
                    room=self.active_room,
                )
                return

            if self.room_list.FindString(part_room) == wx.NOT_FOUND:
                self._append_styled_message(
                    f"[{timestamp}] Not in room '{part_room}'\n",
                    color=self.COLOR_NOTICE,
                    room=self.active_room,
                )
                return

            if not self._check_room_operation_rate_limit(f"part:{part_room}"):
                self._append_styled_message(
                    f"[{timestamp}] Too many part requests. Please wait a moment.\n",
                    color=self.COLOR_ERROR,
                    room=self.active_room,
                )
                return

            if not self.client:
                return

            try:
                self.client.part(part_room)
            except Exception as e:
                self._append_styled_message(
                    f"[{timestamp}] Failed to part room: {e}\n",
                    color=self.COLOR_ERROR,
                    room=self.active_room,
                )

        elif cmd == "/nick":
            if not self.client:
                return

            if len(parts) < 2:
                current_nick = (
                    self.client.nickname if self.client.nickname else "(not set)"
                )
                self._append_styled_message(
                    f"[{timestamp}] Current nickname: {current_nick}\n"
                    f"[{timestamp}] Usage: /nick <nickname> to change it\n",
                    color=self.COLOR_SYSTEM,
                    italic=True,
                    room=self.active_room,
                )
                return

            new_nick = parts[1].strip()
            if len(new_nick) > 32:
                self._append_styled_message(
                    f"[{timestamp}] Nickname too long (max 32 characters)\n",
                    color=self.COLOR_ERROR,
                    room=self.active_room,
                )
                return

            if not new_nick:
                self._append_styled_message(
                    f"[{timestamp}] Nickname cannot be empty\n",
                    color=self.COLOR_ERROR,
                    room=self.active_room,
                )
                return

            old_nick = self.client.nickname
            self.client.nickname = new_nick

            if self.own_identity_hash:
                self.nickname_map[self.own_identity_hash] = new_nick
                for room in self.room_users.keys():
                    if self.active_room == room:
                        wx.CallAfter(self._update_user_list)

            config = _load_config()
            config["nickname"] = new_nick
            _save_config(config)

            if old_nick:
                self._append_styled_message(
                    f"[{timestamp}] Nickname changed from '{old_nick}' to '{new_nick}'\n",
                    color=self.COLOR_SYSTEM,
                    italic=True,
                    room=self.active_room,
                )
            else:
                self._append_styled_message(
                    f"[{timestamp}] Nickname set to '{new_nick}'\n",
                    color=self.COLOR_SYSTEM,
                    italic=True,
                    room=self.active_room,
                )

        elif cmd == "/ping":
            if not self.client:
                return

            try:
                self.last_ping_time = time.time()
                self.client.ping()
                self._append_styled_message(
                    f"[{timestamp}] PING sent to hub\n",
                    color=self.COLOR_SYSTEM,
                    italic=True,
                    room=self.active_room,
                )
            except Exception as e:
                self.last_ping_time = None
                self._append_styled_message(
                    f"[{timestamp}] Failed to send PING: {e}\n",
                    color=self.COLOR_ERROR,
                    room=self.active_room,
                )

        elif cmd in ("/help", "/?"):
            help_text = (
                f"[{timestamp}] Available commands:\n"
                "  /join <room>  - Join a room\n"
                "  /part [room]  - Leave current room or specified room\n"
                "  /nick <name>  - Change your nickname\n"
                "  /ping         - Send a PING to the hub\n"
                "  /help or /?   - Show this help message\n"
            )
            self._append_styled_message(
                help_text,
                color=self.COLOR_SYSTEM,
                italic=True,
                room=self.active_room,
            )

        else:
            if not self.client or not self.active_room:
                return

            try:
                self.client.msg(self.active_room, text)
                self._append_styled_message(
                    f"[{timestamp}] > {text}\n",
                    color=self.COLOR_SYSTEM,
                    italic=True,
                    room=self.active_room,
                )
            except Exception as e:
                self._append_styled_message(
                    f"[{timestamp}] Failed to send command: {e}\n",
                    color=self.COLOR_ERROR,
                    room=self.active_room,
                )

    def _on_message(self, env: dict):
        """Handle incoming message."""
        room = env.get(K_ROOM, "?")
        src = env.get(K_SRC, b"")
        body = env.get(K_BODY, "")

        nick = env.get(K_NICK)
        if isinstance(src, (bytes, bytearray)) and isinstance(nick, str) and nick:
            src_hex = src.hex()
            self.nickname_map[src_hex] = nick
            if room == self.active_room and room in self.room_users:
                self.room_users[room].add(src_hex)
                self._update_user_list()

        user = self._format_user(src)
        timestamp = datetime.now().strftime("%H:%M:%S")

        is_own = (
            isinstance(src, (bytes, bytearray))
            and self.own_identity_hash
            and src.hex() == self.own_identity_hash
        )

        mid = env.get(K_ID)

        target_room = room if room and room != "?" else self.HUB_ROOM

        if is_own:
            pending = None
            if isinstance(mid, (bytes, bytearray)):
                pending = self.pending_messages.pop(bytes(mid), None)

            if pending and target_room in self.room_messages:
                pending_room, pending_text, _pending_sent, pending_index = pending
                messages = self.room_messages[target_room]

                message_index: int | None = None
                if isinstance(pending_index, int) and 0 <= pending_index < len(
                    messages
                ):
                    msg_text, msg_color, _msg_bold, msg_italic = messages[pending_index]
                    if (
                        msg_italic
                        and msg_color == self.COLOR_SYSTEM
                        and pending_text in msg_text
                    ):
                        message_index = pending_index

                if message_index is None:
                    for i in range(len(messages) - 1, -1, -1):
                        msg_text, msg_color, _msg_bold, msg_italic = messages[i]
                        if (
                            msg_italic
                            and msg_color == self.COLOR_SYSTEM
                            and pending_text in msg_text
                        ):
                            message_index = i
                            break

                if message_index is not None:
                    messages[message_index] = (
                        f"[{timestamp}] [{room}] {user}: {body}\n",
                        self.COLOR_OWN_MESSAGE,
                        False,
                        False,
                    )
                    if target_room == self.active_room:
                        self._reload_room_messages()
                    return

            self._append_styled_message(
                f"[{timestamp}] [{room}] {user}: {body}\n",
                color=self.COLOR_OWN_MESSAGE,
                room=target_room,
            )
        else:
            self._append_styled_message(
                f"[{timestamp}] [{room}] {user}: {body}\n", room=target_room
            )

    def _on_notice(self, env: dict):
        """Handle incoming notice."""
        room = env.get(K_ROOM, "?")
        src = env.get(K_SRC, b"")
        body = env.get(K_BODY, "")

        nick = env.get(K_NICK)
        if isinstance(src, (bytes, bytearray)) and isinstance(nick, str) and nick:
            src_hex = src.hex()
            self.nickname_map[src_hex] = nick
            if room == self.active_room and room in self.room_users:
                self.room_users[room].add(src_hex)
                self._update_user_list()

        user = self._format_user(src)
        timestamp = datetime.now().strftime("%H:%M:%S")

        target_room = room if room and room != "?" else self.HUB_ROOM

        self._append_styled_message(
            f"[{timestamp}] [{room}] NOTICE {user}: {body}\n",
            color=self.COLOR_NOTICE,
            room=target_room,
        )

    def _on_error(self, env: dict):
        """Handle incoming error."""
        room = env.get(K_ROOM, "?")
        body = env.get(K_BODY, "")
        timestamp = datetime.now().strftime("%H:%M:%S")

        if body == "HELLO already sent":
            print("[DEBUG] Ignoring expected HELLO retry error")
            return

        target_room = room if room and room != "?" else self.HUB_ROOM

        self._append_styled_message(
            f"[{timestamp}] ERROR [{room}]: {body}\n",
            color=self.COLOR_ERROR,
            bold=True,
            room=target_room,
        )

    def _on_resource_warning(self, message: str):
        """Handle resource warning (message too large)."""
        wx.MessageBox(
            message,
            "Message Too Large",
            wx.OK | wx.ICON_WARNING,
        )

    def _on_pong(self, env: dict):
        """Handle PONG response from hub."""
        if self.last_ping_time:
            latency = int((time.time() - self.last_ping_time) * 1000)
            self.latency_ms = latency
            self.last_ping_time = None
            self._update_status_display()

            timestamp = datetime.now().strftime("%H:%M:%S")
            self._append_styled_message(
                f"[{timestamp}] PONG received - latency: {latency}ms\n",
                color=self.COLOR_SYSTEM,
                italic=True,
                room=self.active_room,
            )

    def _on_welcome(self, env: dict):
        """Handle WELCOME message."""
        timestamp = datetime.now().strftime("%H:%M:%S")
        hub_name = None
        greeting = None
        body = env.get(K_BODY)
        if isinstance(body, dict):
            hub = body.get(B_WELCOME_HUB)
            if isinstance(hub, str) and hub.strip():
                hub_name = hub.strip()
            g = body.get(B_WELCOME_GREETING)
            if isinstance(g, str) and g.strip():
                greeting = g

        hub_txt = f" ({hub_name})" if hub_name else ""
        self._append_styled_message(
            f"[{timestamp}] *** WELCOME - Connected to hub{hub_txt} ***\n",
            color=self.COLOR_SYSTEM,
            italic=True,
            room=self.HUB_ROOM,
        )

        if greeting:
            self._append_styled_message(
                f"[{timestamp}] *** {greeting}\n",
                color=self.COLOR_SYSTEM,
                italic=True,
                room=self.HUB_ROOM,
            )

    def _on_joined(self, room: str, env: dict):
        """Handle JOINED confirmation.

        This handles two scenarios:
        1. Self-join: Multiple hashes or empty list (we just joined)
        2. Member-join: Single hash (another user joined a room we're in)
        """
        timestamp = datetime.now().strftime("%H:%M:%S")

        body = env.get(K_BODY)
        logger.debug(f"JOINED room={room}, body type={type(body)}, body={body}")

        user_list = None
        if isinstance(body, dict):
            user_list = body.get(B_JOINED_USERS)
            logger.debug(f"Body is dict, user_list={user_list}")
        elif isinstance(body, list):
            user_list = body
            logger.debug(f"Body is list directly, user_list={user_list}")

        if not isinstance(user_list, list):
            user_list = []

        is_self_join = len(user_list) != 1

        if is_self_join:
            if self.room_list.FindString(room) == wx.NOT_FOUND:
                self.room_list.Append(room)

            if room not in self.room_messages:
                self.room_messages[room] = []

            members = set()
            for member_hash in user_list:
                if isinstance(member_hash, (bytes, bytearray)):
                    members.add(member_hash.hex())
                    logger.debug(f"Added user: {member_hash.hex()[:16]}...")
            self.room_users[room] = members

            if self.own_identity_hash:
                self.room_users[room].add(self.own_identity_hash)

            member_count = len(self.room_users.get(room, set()))
            self._append_styled_message(
                f"[{timestamp}] *** JOINED {room} ({member_count} user{'s' if member_count != 1 else ''}) ***\n",
                color=self.COLOR_SYSTEM,
                italic=True,
                room=room,
            )

            if self.active_room == self.HUB_ROOM:
                self._set_active_room(room)
            elif self.active_room == room:
                self._update_user_list()
        else:
            user_hash = user_list[0]
            if isinstance(user_hash, (bytes, bytearray)):
                user_hex = user_hash.hex()
                user_formatted = self._format_user(user_hash)

                if room not in self.room_users:
                    self.room_users[room] = set()
                self.room_users[room].add(user_hex)

                self._append_styled_message(
                    f"[{timestamp}] *** {user_formatted} joined {room} ***\n",
                    color=self.COLOR_SYSTEM,
                    italic=True,
                    room=room,
                )

                if self.active_room == room:
                    self._update_user_list()

    def _on_parted(self, room: str, env: dict):
        """Handle PARTED confirmation.

        This handles two scenarios:
        1. Self-part: Multiple hashes or empty list (we left the room)
        2. Member-part: Single hash (another user left a room we're in)
        """
        timestamp = datetime.now().strftime("%H:%M:%S")

        body = env.get(K_BODY)
        logger.debug(f"PARTED room={room}, body type={type(body)}, body={body}")

        user_list = None
        if isinstance(body, dict):
            user_list = body.get(B_JOINED_USERS)
            logger.debug(f"Body is dict, user_list={user_list}")
        elif isinstance(body, list):
            user_list = body
            logger.debug(f"Body is list directly, user_list={user_list}")

        if not isinstance(user_list, list):
            user_list = []

        is_self_part = len(user_list) != 1

        if is_self_part:
            idx = self.room_list.FindString(room)
            if idx != wx.NOT_FOUND:
                self.room_list.Delete(idx)

            self._append_styled_message(
                f"[{timestamp}] *** PARTED {room} ***\n",
                color=self.COLOR_SYSTEM,
                italic=True,
                room=room,
            )

            if self.active_room == room:
                self._set_active_room(self.HUB_ROOM)

            if room in self.room_users:
                del self.room_users[room]
        else:
            user_hash = user_list[0]
            if isinstance(user_hash, (bytes, bytearray)):
                user_hex = user_hash.hex()
                user_formatted = self._format_user(user_hash)

                if room in self.room_users:
                    self.room_users[room].discard(user_hex)

                self._append_styled_message(
                    f"[{timestamp}] *** {user_formatted} left {room} ***\n",
                    color=self.COLOR_SYSTEM,
                    italic=True,
                    room=room,
                )

                if self.active_room == room:
                    self._update_user_list()

    def _on_close(self):
        """Handle connection close (called from callback thread)."""
        wx.CallAfter(self._handle_disconnect)

    def _handle_disconnect(self):
        """Handle disconnect in main thread."""
        self.client = None
        self.is_connecting = False

        timestamp = datetime.now().strftime("%H:%M:%S")
        self._append_styled_message(
            f"[{timestamp}] *** DISCONNECTED ***\n",
            color=self.COLOR_SYSTEM,
            italic=True,
            room=self.HUB_ROOM,
        )

        while self.room_list.GetCount() > 1:
            self.room_list.Delete(1)

        for room in list(self.room_users.keys()):
            del self.room_users[room]

        self.pending_messages.clear()
        self._set_active_room(self.HUB_ROOM)
        self._set_controls_enabled(False)
        self.connect_menu_item.Enable(True)
        self.disconnect_menu_item.Enable(False)
        self._update_status_display()
