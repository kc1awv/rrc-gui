"""Message handler for managing chat messages and display."""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime
from typing import TYPE_CHECKING

import wx
import wx.richtext

from .ui_constants import MAX_MESSAGES_PER_ROOM, MAX_USER_LAST_MESSAGE_CACHE

if TYPE_CHECKING:
    from typing import Callable

logger = logging.getLogger(__name__)


class MessageHandler:
    """Handles message storage, formatting, and display."""

    def __init__(
        self,
        message_display: wx.richtext.RichTextCtrl,
        color_own_message: wx.Colour,
        color_notice: wx.Colour,
        color_error: wx.Colour,
        color_system: wx.Colour,
    ):
        """Initialize message handler.

        Args:
            message_display: The RichTextCtrl for displaying messages
            color_own_message: Color for user's own messages
            color_notice: Color for notice messages
            color_error: Color for error messages
            color_system: Color for system messages
        """
        self.message_display = message_display
        self.COLOR_OWN_MESSAGE = color_own_message
        self.COLOR_NOTICE = color_notice
        self.COLOR_ERROR = color_error
        self.COLOR_SYSTEM = color_system
        self._lock = threading.Lock()
        self.room_messages: dict[
            str, list[tuple[str, wx.Colour | None, bool, bool]]
        ] = {}
        self.pending_messages: dict[bytes, tuple[str, str, float, int | None]] = {}
        self.user_last_message: dict[str, tuple[str, float]] = {}
        self.active_room: str | None = None
        self.unread_counts: dict[str, int] = {}
        self.on_unread_changed: Callable[[], None] | None = None

    def set_active_room(self, room: str) -> None:
        """Set the active room and clear unread count."""
        with self._lock:
            self.active_room = room
            if room in self.unread_counts:
                self.unread_counts[room] = 0

        if self.on_unread_changed:
            self.on_unread_changed()

    def append_styled_message(
        self,
        text: str,
        color: wx.Colour | None = None,
        bold: bool = False,
        italic: bool = False,
        room: str | None = None,
    ) -> int:
        """Append text to message display with styling and store in room history.

        Args:
            text: Message text to append
            color: Optional color for the message
            bold: Whether to bold the message
            italic: Whether to italicize the message
            room: Room to append to (defaults to active room)

        Returns:
            Index of the appended message in the room's message list
        """
        with self._lock:
            target_room = room or self.active_room
        if not target_room:
            return -1

        if target_room not in self.room_messages:
            self.room_messages[target_room] = []

        self.room_messages[target_room].append((text, color, bold, italic))
        appended_index = len(self.room_messages[target_room]) - 1

        if target_room != self.active_room:
            self.unread_counts[target_room] = self.unread_counts.get(target_room, 0) + 1
            if self.on_unread_changed:
                self.on_unread_changed()

        if len(self.room_messages[target_room]) > MAX_MESSAGES_PER_ROOM:
            dropped = len(self.room_messages[target_room]) - MAX_MESSAGES_PER_ROOM
            self.room_messages[target_room] = self.room_messages[target_room][
                -MAX_MESSAGES_PER_ROOM:
            ]
            appended_index = max(0, appended_index - dropped)

            with self._lock:
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

        should_display = target_room == self.active_room

        if should_display:
            self._render_message(text, color, bold, italic)

        return appended_index

    def _render_message(
        self,
        text: str,
        color: wx.Colour | None = None,
        bold: bool = False,
        italic: bool = False,
    ) -> None:
        """Render a single message to the display."""
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

    def reload_room_messages(self, room: str) -> None:
        """Reload the message display with the specified room's history."""
        self.message_display.Clear()

        messages = self.room_messages.get(room, [])

        for text, color, bold, italic in messages:
            self._render_message(text, color, bold, italic)

    def add_pending_message(
        self,
        message_id: bytes,
        room: str,
        text: str,
        message_index: int,
    ) -> None:
        """Track a pending message."""
        with self._lock:
            self.pending_messages[message_id] = (room, text, time.time(), message_index)

    def update_pending_message_to_sent(
        self,
        message_id: bytes,
        final_text: str,
        final_color: wx.Colour | None = None,
    ) -> bool:
        """Update a pending message to show it was successfully sent.

        Args:
            message_id: ID of the message
            final_text: Final text to display
            final_color: Color for the final message

        Returns:
            True if the message was found and updated
        """
        with self._lock:
            pending = self.pending_messages.pop(message_id, None)
            if not pending:
                return False

            room, pending_text, _sent_time, pending_index = pending

            if room not in self.room_messages:
                return False

            messages = self.room_messages[room]

            message_index: int | None = None
            if isinstance(pending_index, int) and 0 <= pending_index < len(messages):
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
                messages[message_index] = (final_text, final_color, False, False)
                if room == self.active_room:
                    self.reload_room_messages(room)
                return True

            return False

    def mark_pending_message_as_failed(
        self,
        message_id: bytes,
        error_text: str,
    ) -> bool:
        """Mark a pending message as failed.

        Args:
            message_id: ID of the message
            error_text: Error text to append to the message

        Returns:
            True if the message was found and updated
        """
        with self._lock:
            pending = self.pending_messages.pop(message_id, None)
            if not pending:
                return False

            room, pending_text, _sent_time, pending_index = pending

            if room not in self.room_messages:
                return False

            messages = self.room_messages[room]

            message_index: int | None = None
            if isinstance(pending_index, int) and 0 <= pending_index < len(messages):
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
                original_text = messages[message_index][0]
                messages[message_index] = (
                    f"{original_text.rstrip()}\n{error_text}\n",
                    self.COLOR_ERROR,
                    False,
                    True,
                )
                if room == self.active_room:
                    self.reload_room_messages(room)
                return True

            return False

    def check_pending_timeouts(self, timeout_seconds: float) -> list[bytes]:
        """Check for pending messages that have timed out.

        Args:
            timeout_seconds: Timeout in seconds

        Returns:
            List of message IDs that timed out
        """
        with self._lock:
            if not self.pending_messages:
                return []

            current_time = time.time()
            timed_out = []

            for mid, (room, text, sent_time, index) in list(
                self.pending_messages.items()
            ):
                if current_time - sent_time <= timeout_seconds:
                    continue

                timed_out.append(mid)

                if room not in self.room_messages:
                    continue

                messages = self.room_messages[room]
                message_index: int | None = None
                if isinstance(index, int) and 0 <= index < len(messages):
                    msg_text, msg_color, _msg_bold, msg_italic = messages[index]
                    if (
                        msg_italic
                        and msg_color == self.COLOR_SYSTEM
                        and text in msg_text
                    ):
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
                original_text = messages[message_index][0]
                messages[message_index] = (
                    f"{original_text.rstrip()} [FAILED - not delivered]\n",
                    self.COLOR_ERROR,
                    False,
                    True,
                )
                if room == self.active_room:
                    self.reload_room_messages(room)

            for mid in timed_out:
                self.pending_messages.pop(mid, None)

            return timed_out

    def track_user_message(self, user_hash: str, message: str) -> None:
        """Track the last message from a user.

        Args:
            user_hash: Hash of the user
            message: Message text
        """
        if not user_hash or not message:
            return

        with self._lock:
            self.user_last_message[user_hash] = (message, time.time())

            if len(self.user_last_message) > MAX_USER_LAST_MESSAGE_CACHE:
                sorted_by_time = sorted(
                    self.user_last_message.items(), key=lambda x: x[1][1]
                )
                num_to_remove = len(self.user_last_message) // 10
                for old_hash, _ in sorted_by_time[:num_to_remove]:
                    del self.user_last_message[old_hash]

    def get_user_last_message(self, user_hash: str) -> tuple[str, float] | None:
        """Get the last message from a user.

        Args:
            user_hash: Hash of the user

        Returns:
            Tuple of (message, timestamp) or None if user has no tracked messages
        """
        if not user_hash:
            return None

        with self._lock:
            return self.user_last_message.get(user_hash)

    def get_pending_count(self) -> int:
        """Get the number of pending messages."""
        with self._lock:
            return len(self.pending_messages)

    def clear_room_messages(self, room: str) -> None:
        """Clear messages for a specific room.

        Args:
            room: Room name
        """
        with self._lock:
            if room in self.room_messages:
                del self.room_messages[room]
            if room in self.unread_counts:
                del self.unread_counts[room]

    def update_colors(
        self,
        color_own_message: wx.Colour,
        color_notice: wx.Colour,
        color_error: wx.Colour,
        color_system: wx.Colour,
    ) -> None:
        """Update message colors (e.g., after theme change)."""
        self.COLOR_OWN_MESSAGE = color_own_message
        self.COLOR_NOTICE = color_notice
        self.COLOR_ERROR = color_error
        self.COLOR_SYSTEM = color_system
