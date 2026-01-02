"""Main GUI frame for RRC client."""

from __future__ import annotations

import logging
import time
from datetime import datetime

import wx

from .client import MessageTooLargeError
from .config import load_config, save_config
from .connection_manager import ConnectionManager
from .constants import (
    B_WELCOME_HUB,
    B_WELCOME_VER,
    K_BODY,
    K_ID,
    K_NICK,
    K_ROOM,
    K_SRC,
)
from .dialogs import ConnectionDialog, PreferencesDialog
from .error_handler import ErrorHandler, ErrorSeverity
from .message_handler import MessageHandler
from .room_manager import RoomManager
from .slash_command_handler import SlashCommandHandler
from .theme import get_theme_colors
from .ui_components import UIComponents
from .ui_constants import (
    INPUT_HISTORY_SIZE,
    MAX_MESSAGE_LENGTH,
    PENDING_CHECK_TIMER_INTERVAL,
    PENDING_MESSAGE_TIMEOUT,
    RATE_LIMIT_MESSAGES_PER_MINUTE,
    RATE_LIMIT_WARNING_THRESHOLD,
    STATUS_UPDATE_TIMER_INTERVAL,
)
from .utils import normalize_room_name, get_timestamp

logger = logging.getLogger(__name__)


class MainFrame(wx.Frame):
    """Main chat window."""

    def __init__(self) -> None:
        super().__init__(None, title="RRC Client", size=(900, 600))

        self.HUB_ROOM = "[Hub]"
        self._create_menu_bar()
        config = load_config()
        if "window_x" in config and "window_y" in config:
            self.SetPosition((config["window_x"], config["window_y"]))
        if "window_width" in config and "window_height" in config:
            self.SetSize((config["window_width"], config["window_height"]))

        theme_colors = get_theme_colors()

        self.connection_manager = ConnectionManager()
        self.ui_components = UIComponents(self)

        success, error_msg = self.connection_manager.initialize_reticulum(
            config.get("configdir") or None
        )

        if not success:
            temp_error_handler = ErrorHandler(self)
            temp_error_handler.show_error(
                f"Failed to initialize Reticulum: {error_msg}\n\n"
                f"You will not be able to connect to hubs until you restart.",
                "Reticulum Initialization",
                ErrorSeverity.WARNING,
            )

        self.ui_components.create_ui(
            hub_room=self.HUB_ROOM,
            saved_left_sash=config.get("left_sash_position"),
            saved_right_sash=config.get("right_sash_position"),
        )

        self.message_handler = MessageHandler(
            self.ui_components.message_display,
            theme_colors["own_message"],
            theme_colors["notice"],
            theme_colors["error"],
            theme_colors["system"],
        )
        self.message_handler.room_messages[self.HUB_ROOM] = []
        self.message_handler.active_room = self.HUB_ROOM

        self.room_manager = RoomManager(
            self.ui_components.room_list,
            self.ui_components.users_list,
            self.HUB_ROOM,
        )
        self.room_manager.active_room = self.HUB_ROOM

        self.message_handler.unread_counts = self.room_manager.unread_counts

        self.message_handler.on_unread_changed = (
            self.room_manager.update_room_list_display
        )
        self.room_manager.on_room_changed = self._on_room_changed
        self.connection_manager.on_connection_success = self._on_connection_success
        self.connection_manager.on_connection_failed = self._on_connection_failed
        self.connection_manager.on_disconnected = self._handle_disconnect

        self.ui_components.bind_events(
            on_room_select=self.on_room_select,
            on_join_room=self.on_join_room,
            on_part_room=self.on_part_room,
            on_send_message=self.on_send_message,
            on_input_key_down=self.on_input_key_down,
            on_user_double_click=self.on_user_double_click,
        )

        self.input_history: list[str] = []
        self.input_history_index: int = -1
        self.input_buffer: str = ""
        self.message_send_times: list[float] = []

        self.CreateStatusBar()
        self.SetStatusText("Not connected")

        self.ui_components.set_controls_enabled(False)

        self.Bind(wx.EVT_CLOSE, self.on_close)
        self.Bind(wx.EVT_CHAR_HOOK, self.on_key_press)

        self.pending_check_timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self._check_pending_timeouts, self.pending_check_timer)
        self.pending_check_timer.Start(PENDING_CHECK_TIMER_INTERVAL)

        self.status_update_timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self._update_status_display, self.status_update_timer)
        self.status_update_timer.Start(STATUS_UPDATE_TIMER_INTERVAL)

        self.error_handler = ErrorHandler(self)

        self.slash_command_handler = SlashCommandHandler(
            get_client_func=self.connection_manager.get_client,
            message_handler=self.message_handler,
            room_manager=self.room_manager,
            error_handler=self.error_handler,
            hub_room=self.HUB_ROOM,
        )

        self.ui_components.panel.Layout()
        wx.CallAfter(self.ui_components.message_display.SetFocus)

    def _create_menu_bar(self) -> None:
        menu_bar = wx.MenuBar()

        file_menu = wx.Menu()
        self.connect_menu_item = file_menu.Append(
            wx.ID_ANY, "&Connect\tCtrl-N", "Connect to hub"
        )
        self.disconnect_menu_item = file_menu.Append(
            wx.ID_ANY, "&Disconnect\tCtrl-D", "Disconnect from hub"
        )
        file_menu.AppendSeparator()
        prefs_item = file_menu.Append(
            wx.ID_PREFERENCES, "&Preferences...", "Configure colors and fonts"
        )
        file_menu.AppendSeparator()
        quit_item = file_menu.Append(wx.ID_EXIT, "&Quit\tCtrl-Q", "Quit application")

        self.Bind(wx.EVT_MENU, self.on_connect_menu, self.connect_menu_item)
        self.Bind(wx.EVT_MENU, self.on_disconnect_menu, self.disconnect_menu_item)
        self.Bind(wx.EVT_MENU, self.on_preferences, prefs_item)
        self.Bind(wx.EVT_MENU, self.on_quit, quit_item)

        self.disconnect_menu_item.Enable(False)

        menu_bar.Append(file_menu, "&File")
        self.SetMenuBar(menu_bar)

    def _on_connection_success(self) -> None:
        """Handle successful connection."""
        client = self.connection_manager.get_client()
        if client:
            own_identity_hash = client.identity.hash.hex()
            self.room_manager.set_own_identity(own_identity_hash)

            if client.nickname:
                self.room_manager.set_nickname(own_identity_hash, client.nickname)
        else:
            logger.warning("_on_connection_success: client is None")

        self._update_status_display()
        self.ui_components.set_controls_enabled(True)
        self.connect_menu_item.Enable(False)
        self.disconnect_menu_item.Enable(True)

    def _on_connection_failed(self, error_msg: str) -> None:
        """Handle connection failure."""
        self._update_status_display()
        self.connect_menu_item.Enable(True)
        self.disconnect_menu_item.Enable(False)
        self.error_handler.show_error(
            error_msg, "Connection Error", ErrorSeverity.ERROR
        )

    def _update_status_display(self, event: wx.TimerEvent | None = None) -> None:
        """Update status bar with connection state and pending message count."""
        is_connecting = self.connection_manager.is_connecting
        is_connected = self.connection_manager.is_connected()

        if is_connecting:
            icon = "🟡"
            status = "Connecting..."
        elif is_connected:
            icon = "🟢"
            status = "Connected"
        else:
            icon = "🔴"
            status = "Not connected"

        pending_count = self.message_handler.get_pending_count()
        if pending_count > 0:
            status += f" | Sending: {pending_count}"

        self.SetStatusText(f"{icon} {status}")

    def on_input_key_down(self, event: wx.KeyEvent) -> None:
        """Handle input history navigation with up/down arrows."""
        keycode = event.GetKeyCode()

        if keycode == wx.WXK_UP:
            if self.input_history:
                if self.input_history_index == -1:
                    self.input_buffer = self.ui_components.get_message_input_value()
                    self.input_history_index = len(self.input_history) - 1
                elif self.input_history_index > 0:
                    self.input_history_index -= 1

                if 0 <= self.input_history_index < len(self.input_history):
                    self.ui_components.set_message_input_value(
                        self.input_history[self.input_history_index]
                    )
            return

        elif keycode == wx.WXK_DOWN:
            if self.input_history_index != -1:
                if self.input_history_index < len(self.input_history) - 1:
                    self.input_history_index += 1
                    self.ui_components.set_message_input_value(
                        self.input_history[self.input_history_index]
                    )
                else:
                    self.input_history_index = -1
                    self.ui_components.set_message_input_value(self.input_buffer)
            return

        event.Skip()

    def on_key_press(self, event: wx.KeyEvent) -> None:
        """Handle keyboard shortcuts."""
        keycode = event.GetKeyCode()

        if event.AltDown() and ord("1") <= keycode <= ord("9"):
            room_index = keycode - ord("1")
            if room_index < self.ui_components.room_list.GetCount():
                room = self.ui_components.room_list.GetString(room_index)
                clean_room = self.room_manager.strip_unread_count(room)
                self._set_active_room(clean_room)
            return

        if event.AltDown():
            if keycode == wx.WXK_UP:
                current = self.ui_components.room_list.GetSelection()
                if current > 0:
                    room = self.ui_components.room_list.GetString(current - 1)
                    clean_room = self.room_manager.strip_unread_count(room)
                    self._set_active_room(clean_room)
                return
            elif keycode == wx.WXK_DOWN:
                current = self.ui_components.room_list.GetSelection()
                if current < self.ui_components.room_list.GetCount() - 1:
                    room = self.ui_components.room_list.GetString(current + 1)
                    clean_room = self.room_manager.strip_unread_count(room)
                    self._set_active_room(clean_room)
                return

        event.Skip()

    def _check_pending_timeouts(self, event: wx.TimerEvent) -> None:
        """Check for pending messages that have timed out and mark them as failed."""
        self.message_handler.check_pending_timeouts(PENDING_MESSAGE_TIMEOUT)

    def on_connect_menu(self, event: wx.Event) -> None:
        """Show connection dialog and connect to hub."""
        if (
            self.connection_manager.is_connected()
            or self.connection_manager.is_connecting
        ):
            return

        wx.CallAfter(self._show_connect_dialog)

    def _show_connect_dialog(self) -> None:
        """Show the connection dialog (deferred to avoid focus warnings)."""
        dlg = ConnectionDialog(self)
        result = dlg.ShowModal()
        if result == wx.ID_OK:
            if not dlg.Validate():
                dlg.Destroy()
                return

            values = dlg.get_values()
            dlg.Destroy()

            save_config(values)

            self.connect_menu_item.Enable(False)
            self._update_status_display()

            nickname = values.get("nickname", "")
            auto_join_room = values.get("auto_join_room", "")
            if auto_join_room:
                auto_join_room = normalize_room_name(auto_join_room)

            self.connection_manager.set_client_callbacks(
                on_message=lambda env: wx.CallAfter(self._on_message, env),
                on_notice=lambda env: wx.CallAfter(self._on_notice, env),
                on_error=lambda env: wx.CallAfter(self._on_error, env),
                on_welcome=lambda env: wx.CallAfter(self._on_welcome, env),
                on_pong=lambda env: wx.CallAfter(self._on_pong, env),
                on_joined=lambda room, env: wx.CallAfter(self._on_joined, room, env),
                on_parted=lambda room, env: wx.CallAfter(self._on_parted, room, env),
                on_close=lambda: wx.CallAfter(self._on_close),
                on_resource_warning=lambda msg: wx.CallAfter(
                    self._on_resource_warning, msg
                ),
            )

            self.connection_manager.connect(
                identity_path=values["identity_path"],
                dest_name=values["dest_name"],
                hub_hash=values["hub_hash"],
                nickname=nickname if nickname else None,
                hello_body={},
                auto_join_room=auto_join_room,
                configdir=values.get("configdir") or None,
            )
        else:
            dlg.Destroy()

    def on_disconnect_menu(self, event: wx.Event) -> None:
        """Disconnect from hub."""
        if self.connection_manager.is_connected():
            result = self.error_handler.confirm_action(
                "Are you sure you want to disconnect from the hub?",
                "Confirm Disconnect",
            )
            if result:
                self.connection_manager.disconnect()
        else:
            self.connection_manager.disconnect()

    def on_preferences(self, event: wx.Event) -> None:
        """Show preferences dialog."""
        wx.CallAfter(self._show_preferences_dialog)
        wx.CallAfter(self._show_preferences_dialog)

    def _show_preferences_dialog(self) -> None:
        """Show the preferences dialog (deferred to avoid focus warnings)."""
        dlg = PreferencesDialog(self)
        if dlg.ShowModal() == wx.ID_OK:
            theme_colors = get_theme_colors()
            self.message_handler.update_colors(
                theme_colors["own_message"],
                theme_colors["notice"],
                theme_colors["error"],
                theme_colors["system"],
            )

            if self.room_manager.active_room:
                self.message_handler.reload_room_messages(self.room_manager.active_room)
        dlg.Destroy()

    def on_quit(self, event: wx.Event) -> None:
        """Quit the application."""
        self.Close()

    def on_close(self, event: wx.CloseEvent) -> None:
        """Handle window close."""
        if self.pending_check_timer and self.pending_check_timer.IsRunning():
            self.pending_check_timer.Stop()
        if self.status_update_timer and self.status_update_timer.IsRunning():
            self.status_update_timer.Stop()

        config = load_config()
        pos = self.GetPosition()
        size = self.GetSize()
        config["window_x"] = pos.x
        config["window_y"] = pos.y
        config["window_width"] = size.width
        config["window_height"] = size.height
        config["left_sash_position"] = self.ui_components.get_left_sash_position()
        right_sash = self.ui_components.get_right_sash_position()
        if right_sash is not None:
            config["right_sash_position"] = right_sash
        save_config(config)

        if self.connection_manager.is_connected():
            self.connection_manager.disconnect()
        self.Destroy()

    def on_room_select(self, event: wx.Event) -> None:
        """Handle room selection from list."""
        sel = self.ui_components.room_list.GetSelection()
        if sel != wx.NOT_FOUND:
            room = self.ui_components.room_list.GetString(sel)
            clean_room = self.room_manager.strip_unread_count(room)
            self._set_active_room(clean_room)

    def _set_active_room(self, room: str) -> None:
        """Set the active room for sending messages and update display."""
        self.ui_components.set_active_room_label(room)

        self.room_manager.set_active_room(room)
        self.message_handler.set_active_room(room)

        if room == self.HUB_ROOM:
            self.ui_components.hide_user_list()
        else:
            self.ui_components.show_user_list()

        self.message_handler.reload_room_messages(room)

    def _on_room_changed(self, room: str) -> None:
        """Callback when room changes."""
        pass

    def on_user_double_click(self, event: wx.Event) -> None:
        """Handle double-click on user in the user list."""
        sel = self.ui_components.users_list.GetSelection()
        if sel == wx.NOT_FOUND:
            return

        display_name = self.ui_components.users_list.GetString(sel)

        user_hash = None
        if "<" in display_name and "…>" in display_name:
            start = display_name.find("<") + 1
            end = display_name.find("…>")
            user_hash = display_name[start:end]
        elif "…" in display_name:
            user_hash = display_name.split("…")[0].split()[0]

        if not user_hash:
            return

        user_info = self.room_manager.get_user_info(user_hash)
        if not user_info:
            return

        full_hash = user_info["full_hash"]
        nickname = user_info["nickname"]
        is_you = user_info["is_you"]

        last_msg_info = self.message_handler.get_user_last_message(full_hash)
        if last_msg_info:
            msg_text, msg_timestamp = last_msg_info
            last_msg_text = msg_text if len(msg_text) <= 100 else msg_text[:100] + "..."
            last_msg_time = datetime.fromtimestamp(msg_timestamp).strftime(
                "%Y-%m-%d %H:%M:%S"
            )
        else:
            last_msg_text = "(no messages seen)"
            last_msg_time = None

        info_lines = [
            f"Nickname: {nickname}",
            f"Identity Hash: {full_hash}",
            "",
            "Last Message:",
            f"  {last_msg_text}",
        ]
        if last_msg_time:
            info_lines.append(f"  Time: {last_msg_time}")

        if is_you:
            info_lines.insert(2, "\n(This is you)")

        info_text = "\n".join(info_lines)

        dlg = wx.MessageDialog(
            self,
            info_text,
            f"User Information: {nickname}",
            wx.OK | wx.ICON_INFORMATION,
        )
        dlg.ShowModal()
        dlg.Destroy()

    def on_join_room(self, event: wx.Event) -> None:
        """Join a new room."""
        client = self.connection_manager.get_client()
        if not client:
            return

        dlg = wx.TextEntryDialog(self, "Enter room name:", "Join Room")
        if dlg.ShowModal() == wx.ID_OK:
            raw_room = dlg.GetValue()
            room = normalize_room_name(raw_room)

            if room is None:
                if self.error_handler:
                    self.error_handler.show_invalid_room_name_error()
                dlg.Destroy()
                return

            if self.room_manager.is_room_joined(room):
                if self.error_handler:
                    self.error_handler.show_error(
                        f"Already in room '{room}'.",
                        "Already Joined",
                        ErrorSeverity.INFO,
                    )
            else:
                client.join(room)
        dlg.Destroy()

    def on_part_room(self, event: wx.Event) -> None:
        """Leave the active room."""
        client = self.connection_manager.get_client()
        if not client or not self.room_manager.active_room:
            return

        if self.room_manager.active_room == self.HUB_ROOM:
            return

        room_to_part = self.room_manager.active_room

        if self.error_handler:
            confirmed = self.error_handler.confirm_action(
                f"Leave room '{room_to_part}'?\n\nMessage history will be preserved.",
                "Confirm Part",
            )
            if confirmed:
                client.part(room_to_part)
        else:
            result = wx.MessageBox(
                f"Leave room '{room_to_part}'?\n\nMessage history will be preserved.",
                "Confirm Part",
                wx.YES_NO | wx.NO_DEFAULT | wx.ICON_QUESTION,
            )
            if result == wx.YES:
                client.part(room_to_part)

    def on_send_message(self, event: wx.Event) -> None:
        """Send a message to the active room."""
        client = self.connection_manager.get_client()
        if not client or not self.room_manager.active_room:
            return

        text = self.ui_components.get_message_input_value().strip()
        if not text:
            return

        text = text.replace("\n", " ").replace("\r", " ").replace("\t", " ")
        text = " ".join(text.split())

        if not text:
            return

        if text.startswith("/"):
            self.slash_command_handler.handle_command(text)
            self.ui_components.clear_message_input()
            return

        if self.room_manager.active_room == self.HUB_ROOM:
            return

        current_time = time.time()
        self.message_send_times = [
            t for t in self.message_send_times if current_time - t < 60
        ]

        if len(self.message_send_times) >= RATE_LIMIT_MESSAGES_PER_MINUTE:
            self.error_handler.show_rate_limit_warning(
                len(self.message_send_times), RATE_LIMIT_MESSAGES_PER_MINUTE
            )
            return
        elif len(self.message_send_times) >= int(
            RATE_LIMIT_MESSAGES_PER_MINUTE * RATE_LIMIT_WARNING_THRESHOLD
        ):
            self.SetStatusText(
                f"WARNING: Approaching rate limit ({len(self.message_send_times)}/{RATE_LIMIT_MESSAGES_PER_MINUTE} msgs/min)"
            )

        if len(text) > MAX_MESSAGE_LENGTH:
            self.error_handler.show_message_too_long_error(
                len(text), MAX_MESSAGE_LENGTH
            )
            return

        try:
            mid = client.msg(self.room_manager.active_room, text)
        except MessageTooLargeError:
            return

        if self.room_manager.own_identity_hash:
            timestamp = get_timestamp()
            user = self.room_manager.format_user(
                bytes.fromhex(self.room_manager.own_identity_hash)
            )

            placeholder_index = self.message_handler.append_styled_message(
                f"[{timestamp}] [{self.room_manager.active_room}] {user}: {text}\n",
                color=self.message_handler.COLOR_SYSTEM,
                italic=True,
                room=self.room_manager.active_room,
            )
            self.message_handler.add_pending_message(
                mid, self.room_manager.active_room, text, placeholder_index
            )

        if text not in self.input_history or self.input_history[-1] != text:
            self.input_history.append(text)
            if len(self.input_history) > INPUT_HISTORY_SIZE:
                self.input_history.pop(0)

        self.input_history_index = -1
        self.input_buffer = ""

        self.message_send_times.append(time.time())

        self.ui_components.clear_message_input()

    def _on_message(self, env: dict) -> None:
        """Handle incoming message."""
        room = env.get(K_ROOM, "?")
        src = env.get(K_SRC, b"")
        body = env.get(K_BODY, "")

        nick = env.get(K_NICK)
        if isinstance(src, (bytes, bytearray)) and isinstance(nick, str) and nick:
            src_hex = src.hex()
            self.room_manager.set_nickname(src_hex, nick)
            if room == self.room_manager.active_room:
                self.room_manager.add_user_to_room(room, src_hex)

        if isinstance(src, (bytes, bytearray)) and isinstance(body, str):
            src_hex = src.hex()
            self.message_handler.track_user_message(src_hex, body)

        user = self.room_manager.format_user(src)
        timestamp = datetime.now().strftime("%H:%M:%S")

        is_own = (
            isinstance(src, (bytes, bytearray))
            and self.room_manager.own_identity_hash
            and src.hex() == self.room_manager.own_identity_hash
        )

        mid = env.get(K_ID)

        target_room = room if room and room != "?" else self.HUB_ROOM

        if is_own:
            if isinstance(mid, (bytes, bytearray)):
                final_text = f"[{timestamp}] [{room}] {user}: {body}\n"
                updated = self.message_handler.update_pending_message_to_sent(
                    bytes(mid), final_text, self.message_handler.COLOR_OWN_MESSAGE
                )
                if updated:
                    return

            self.message_handler.append_styled_message(
                f"[{timestamp}] [{room}] {user}: {body}\n",
                color=self.message_handler.COLOR_OWN_MESSAGE,
                room=target_room,
            )
        else:
            self.message_handler.append_styled_message(
                f"[{timestamp}] [{room}] {user}: {body}\n", room=target_room
            )

    def _on_notice(self, env: dict) -> None:
        """Handle incoming notice."""
        room = env.get(K_ROOM, "?")
        src = env.get(K_SRC, b"")
        body = env.get(K_BODY, "")

        logger.debug(
            "_on_notice called: room=%s src=%s body=%s",
            room,
            src.hex() if isinstance(src, (bytes, bytearray)) else src,
            body,
        )

        nick = env.get(K_NICK)
        if isinstance(src, (bytes, bytearray)) and isinstance(nick, str) and nick:
            src_hex = src.hex()
            self.room_manager.set_nickname(src_hex, nick)
            if room == self.room_manager.active_room:
                self.room_manager.add_user_to_room(room, src_hex)

        user = self.room_manager.format_user(src)
        timestamp = datetime.now().strftime("%H:%M:%S")

        self.message_handler.append_styled_message(
            f"[{timestamp}] NOTICE {user}: {body}\n",
            color=self.message_handler.COLOR_NOTICE,
            room=self.HUB_ROOM,
        )

    def _on_error(self, env: dict) -> None:
        """Handle incoming error."""
        room = env.get(K_ROOM, "?")
        body = env.get(K_BODY, "")
        timestamp = get_timestamp()

        if body == "HELLO already sent":
            logger.debug("Ignoring expected HELLO retry error")
            return

        target_room = room if room and room != "?" else self.HUB_ROOM

        self.message_handler.append_styled_message(
            f"[{timestamp}] ERROR [{room}]: {body}\n",
            color=self.message_handler.COLOR_ERROR,
            bold=True,
            room=target_room,
        )

    def _on_resource_warning(self, message: str) -> None:
        """Handle resource warning (message too large)."""
        self.error_handler.show_error(
            message, "Message Too Large", ErrorSeverity.WARNING
        )

    def _on_pong(self, env: dict) -> None:
        """Handle PONG response from server."""
        self.slash_command_handler.handle_pong()

    def _on_welcome(self, env: dict) -> None:
        """Handle WELCOME message."""
        timestamp = get_timestamp()
        hub_name = None
        hub_version = None

        body = env.get(K_BODY)
        if isinstance(body, dict):
            hub = body.get(B_WELCOME_HUB)
            if isinstance(hub, str) and hub.strip():
                hub_name = hub.strip()
            ver = body.get(B_WELCOME_VER)
            if isinstance(ver, str) and ver.strip():
                hub_version = ver.strip()

        hub_txt = f" ({hub_name}" if hub_name else ""
        if hub_version:
            hub_txt += f" v{hub_version}" if hub_txt else f" (v{hub_version}"
        if hub_txt:
            hub_txt += ")"
        self.message_handler.append_styled_message(
            f"[{timestamp}] *** WELCOME - Connected to hub{hub_txt} ***\n",
            color=self.message_handler.COLOR_SYSTEM,
            italic=True,
            room=self.HUB_ROOM,
        )

    def _on_joined(self, room: str, env: dict) -> None:
        """Handle JOINED confirmation."""
        timestamp = get_timestamp()

        body = env.get(K_BODY)
        members = None
        if isinstance(body, list):
            members = body

        self.room_manager.add_room(room, members)

        member_count = self.room_manager.get_room_user_count(room)
        self.message_handler.append_styled_message(
            f"[{timestamp}] *** JOINED {room} ({member_count} user{'s' if member_count != 1 else ''}) ***\n",
            color=self.message_handler.COLOR_SYSTEM,
            italic=True,
            room=room,
        )

        if self.room_manager.active_room == self.HUB_ROOM:
            self._set_active_room(room)
        elif self.room_manager.active_room == room:
            self.room_manager.update_user_list()

    def _on_parted(self, room: str, env: dict) -> None:
        """Handle PARTED confirmation."""
        timestamp = get_timestamp()

        self.room_manager.remove_room(room)

        self.message_handler.append_styled_message(
            f"[{timestamp}] *** PARTED {room} ***\n",
            color=self.message_handler.COLOR_SYSTEM,
            italic=True,
            room=room,
        )

        if self.room_manager.active_room == room:
            self._set_active_room(self.HUB_ROOM)

    def _on_close(self) -> None:
        """Handle connection close (called from callback thread)."""
        wx.CallAfter(self._handle_disconnect)

    def _handle_disconnect(self) -> None:
        """Handle disconnect in main thread."""
        timestamp = get_timestamp()
        self.message_handler.append_styled_message(
            f"[{timestamp}] *** DISCONNECTED ***\n",
            color=self.message_handler.COLOR_SYSTEM,
            italic=True,
            room=self.HUB_ROOM,
        )

        self.room_manager.reset(keep_hub_room=True)

        hub_messages = self.message_handler.room_messages.get(self.HUB_ROOM, [])
        self.message_handler.room_messages.clear()
        self.message_handler.room_messages[self.HUB_ROOM] = hub_messages

        self._set_active_room(self.HUB_ROOM)

        self.ui_components.set_controls_enabled(False)
        self.connect_menu_item.Enable(True)
        self.disconnect_menu_item.Enable(False)
        self._update_status_display()
