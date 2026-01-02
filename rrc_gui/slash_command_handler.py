"""Slash command handler for client-side and server-side commands."""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

import wx

from .constants import T_PING
from .envelope import make_envelope
from .error_handler import ErrorSeverity
from .ui_constants import MAX_MESSAGE_LENGTH
from .utils import normalize_room_name, get_timestamp

if TYPE_CHECKING:
    from .client import Client, MessageTooLargeError
    from .error_handler import ErrorHandler
    from .message_handler import MessageHandler
    from .room_manager import RoomManager

logger = logging.getLogger(__name__)


class SlashCommandHandler:
    """Handles slash command parsing and execution."""

    def __init__(
        self,
        get_client_func,
        message_handler: MessageHandler,
        room_manager: RoomManager,
        error_handler: ErrorHandler,
        hub_room: str,
    ):
        """Initialize slash command handler.

        Args:
            get_client_func: Function that returns current Client instance
            message_handler: Message handler instance
            room_manager: Room manager instance
            error_handler: Error handler instance
            hub_room: Name of the hub room
        """
        self.get_client = get_client_func
        self.message_handler = message_handler
        self.room_manager = room_manager
        self.error_handler = error_handler
        self.HUB_ROOM = hub_room
        self.ping_sent_time: float | None = None

    def handle_command(self, text: str) -> bool:
        """Handle a slash command.

        Args:
            text: The command text starting with /

        Returns:
            True if command was handled, False if not a command
        """
        if not text.startswith('/'):
            return False

        client = self.get_client()
        if not client:
            return True

        parts = text.split(None, 1)
        command = parts[0].lower()
        args = parts[1] if len(parts) > 1 else ""

        if command == '/ping':
            self._handle_ping()
            return True

        elif command == '/join':
            self._handle_join(args)
            return True

        elif command == '/part':
            self._handle_part(args)
            return True

        self._handle_server_command(text)
        return True

    def _handle_ping(self) -> None:
        """Send a PING to the server and track the time."""
        client = self.get_client()
        if not client:
            return

        try:
            self.ping_sent_time = time.time()
            env = make_envelope(T_PING, src=client.identity.hash)
            client._send(env)

            timestamp = get_timestamp()
            self.message_handler.append_styled_message(
                f"[{timestamp}] PING sent...\n",
                color=self.message_handler.COLOR_SYSTEM,
                italic=True,
                room=self.HUB_ROOM,
            )
        except Exception as e:
            logger.exception("Failed to send PING: %s", e)
            timestamp = get_timestamp()
            self.message_handler.append_styled_message(
                f"[{timestamp}] ERROR: Failed to send PING: {e}\n",
                color=self.message_handler.COLOR_ERROR,
                bold=True,
                room=self.HUB_ROOM,
            )

    def handle_pong(self) -> None:
        """Handle PONG response from server."""
        if self.ping_sent_time is not None:
            latency = (time.time() - self.ping_sent_time) * 1000
            self.ping_sent_time = None

            timestamp = get_timestamp()
            self.message_handler.append_styled_message(
                f"[{timestamp}] PONG received (latency: {latency:.1f} ms)\n",
                color=self.message_handler.COLOR_SYSTEM,
                italic=True,
                room=self.HUB_ROOM,
            )

    def _handle_join(self, args: str) -> None:
        """Handle /join command.

        Args:
            args: Room name argument
        """
        client = self.get_client()
        if not client:
            return

        if not args:
            wx.MessageBox(
                "Usage: /join <room-name>",
                "Missing Room Name",
                wx.OK | wx.ICON_WARNING,
            )
            return

        raw_room = args.strip()
        room = normalize_room_name(raw_room)

        if room is None:
            self.error_handler.show_invalid_room_name_error()
            return

        if self.room_manager.is_room_joined(room):
            self.error_handler.show_error(
                f"Already in room '{room}'.",
                "Already Joined",
                ErrorSeverity.INFO
            )
        else:
            client.join(room)

    def _handle_part(self, args: str) -> None:
        """Handle /part command.

        Args:
            args: Optional room name argument
        """
        client = self.get_client()
        if not client:
            return

        room = None
        if args:
            room = normalize_room_name(args.strip())
            if room is None:
                self.error_handler.show_invalid_room_name_error()
                return
        elif self.room_manager.active_room != self.HUB_ROOM:
            room = self.room_manager.active_room
        else:
            self.error_handler.show_error(
                "Usage: /part [room-name]\n\n"
                "Specify a room name, or use this command while in a room.",
                "Missing Room Name",
                ErrorSeverity.WARNING
            )
            return

        if room and room != self.HUB_ROOM:
            if not self.room_manager.is_room_joined(room):
                wx.MessageBox(
                    f"Not in room '{room}'.",
                    "Not In Room",
                    wx.OK | wx.ICON_INFORMATION,
                )
            else:
                client.part(room)

    def _handle_server_command(self, text: str) -> None:
        """Send a slash command to the server for processing.

        Args:
            text: The complete command text
        """
        client = self.get_client()
        if not client:
            return

        try:
            if len(text) > MAX_MESSAGE_LENGTH:
                self.error_handler.show_message_too_long_error(
                    len(text), MAX_MESSAGE_LENGTH
                )
                return

            from .client import MessageTooLargeError

            parts = text.split(None, 2)
            command = parts[0].lower() if parts else ""
            
            room_commands = {
                '/register', '/unregister', '/topic', '/mode', '/kick',
                '/op', '/deop', '/voice', '/devoice', '/ban', '/invite'
            }
            
            room_field = ""
            if command in room_commands and len(parts) >= 2:
                room_arg = parts[1]
                normalized = normalize_room_name(room_arg)
                if normalized:
                    room_field = normalized
            
            client.msg(room_field, text)
            timestamp = get_timestamp()
            self.message_handler.append_styled_message(
                f"[{timestamp}] -> {text}\n",
                color=self.message_handler.COLOR_SYSTEM,
                italic=True,
                room=self.HUB_ROOM,
            )
        except MessageTooLargeError:
            pass
        except Exception as e:
            logger.exception("Failed to send server command: %s", e)
            timestamp = get_timestamp()
            self.message_handler.append_styled_message(
                f"[{timestamp}] ERROR: Failed to send command: {e}\n",
                color=self.message_handler.COLOR_ERROR,
                bold=True,
                room=self.HUB_ROOM,
            )
