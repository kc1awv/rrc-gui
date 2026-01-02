"""Room manager for managing chat rooms and users."""

from __future__ import annotations

import logging
import threading
import time
from typing import TYPE_CHECKING

import wx

from .ui_constants import MAX_PARTED_ROOMS_HISTORY

if TYPE_CHECKING:
    from typing import Callable

logger = logging.getLogger(__name__)


class RoomManager:
    """Manages room state, user lists, and room transitions."""

    @staticmethod
    def strip_unread_count(room_display: str) -> str:
        """Strip unread count suffix from room display name.

        Args:
            room_display: Room name possibly with " (N)" unread count suffix

        Returns:
            Clean room name without unread count
        """
        return room_display.split(" (")[0] if " (" in room_display else room_display

    def __init__(
        self, room_list: wx.ListBox, users_list: wx.ListBox, hub_room: str
    ) -> None:
        """Initialize room manager.

        Args:
            room_list: ListBox widget for displaying rooms
            users_list: ListBox widget for displaying users
            hub_room: Name of the hub room (special room)
        """
        self.room_list = room_list
        self.users_list = users_list
        self.HUB_ROOM = hub_room
        self._lock = threading.Lock()
        self.active_room: str | None = None
        self.room_users: dict[str, set[str]] = {}
        self.nickname_map: dict[str, str] = {}
        self.own_identity_hash: str | None = None
        self.parted_rooms: dict[str, float] = {}
        self.unread_counts: dict[str, int] = {}
        self._room_list_update_timer: wx.Timer | None = None
        self._room_list_update_pending: bool = False
        self.on_room_changed: Callable[[str], None] | None = None

    def set_own_identity(self, identity_hash: str) -> None:
        """Set the user's own identity hash."""
        self.own_identity_hash = identity_hash

    def set_nickname(self, user_hash: str, nickname: str) -> None:
        """Set a nickname for a user.

        Args:
            user_hash: Hash of the user
            nickname: Nickname to set
        """
        with self._lock:
            self.nickname_map[user_hash] = nickname

    def get_nickname(self, user_hash: str) -> str | None:
        """Get a nickname for a user.

        Args:
            user_hash: Hash of the user

        Returns:
            Nickname string if found, None if user has no nickname set
        """
        with self._lock:
            return self.nickname_map.get(user_hash)

    def format_user(self, src: bytes | bytearray | str) -> str:
        """Format a user identity for display, using nickname if available.

        Args:
            src: User identity (bytes/bytearray hash or string)

        Returns:
            Formatted user string
        """
        if not isinstance(src, (bytes, bytearray)):
            return str(src)

        src_hex_full = src.hex()
        src_hex_short = src_hex_full[:12]

        if self.own_identity_hash and src_hex_full == self.own_identity_hash:
            nick = self.nickname_map.get(src_hex_full, "")
            if nick:
                return f"{nick} (you)"
            return f"{src_hex_short}… (you)"

        nick = self.nickname_map.get(src_hex_full)
        if nick:
            return f"{nick} <{src_hex_short}…>"

        return f"{src_hex_short}…"

    def set_active_room(self, room: str) -> None:
        """Set the active room.

        Args:
            room: Room name to activate
        """
        self.active_room = room
        with self._lock:
            if room in self.unread_counts:
                self.unread_counts[room] = 0

        idx = self.room_list.FindString(room)
        if idx != wx.NOT_FOUND:
            self.room_list.SetSelection(idx)

        self.update_user_list()

        if self.on_room_changed:
            self.on_room_changed(room)

    def add_room(
        self, room: str, members: list[bytes | bytearray] | None = None
    ) -> None:
        """Add a room to the room list.

        Args:
            room: Room name
            members: Optional list of member hashes
        """
        if self.room_list.FindString(room) == wx.NOT_FOUND:
            self.room_list.Append(room)

        if members:
            user_set = set()
            for member_hash in members:
                if isinstance(member_hash, (bytes, bytearray)):
                    user_set.add(member_hash.hex())
            with self._lock:
                self.room_users[room] = user_set
        else:
            with self._lock:
                if room not in self.room_users:
                    self.room_users[room] = set()

        if self.own_identity_hash:
            with self._lock:
                self.room_users[room].add(self.own_identity_hash)

    def remove_room(self, room: str) -> None:
        """Remove a room from the room list.

        Args:
            room: Room name
        """
        idx = self.room_list.FindString(room)
        if idx != wx.NOT_FOUND:
            self.room_list.Delete(idx)

        with self._lock:
            if room in self.room_users:
                del self.room_users[room]

            self.parted_rooms[room] = time.time()

            if len(self.parted_rooms) > MAX_PARTED_ROOMS_HISTORY:
                sorted_rooms = sorted(self.parted_rooms.items(), key=lambda x: x[1])
                rooms_to_remove = sorted_rooms[:-MAX_PARTED_ROOMS_HISTORY]

                for old_room, _ in rooms_to_remove:
                    del self.parted_rooms[old_room]
                    if old_room in self.unread_counts:
                        del self.unread_counts[old_room]
                    logger.debug("Cleaned up history for old parted room: %s", old_room)

    def add_user_to_room(self, room: str, user_hash: str) -> None:
        """Add a user to a room.

        Args:
            room: Room name
            user_hash: User hash
        """
        with self._lock:
            if room not in self.room_users:
                self.room_users[room] = set()
            self.room_users[room].add(user_hash)

        if room == self.active_room:
            self.update_user_list()

    def get_room_user_count(self, room: str) -> int:
        """Get the number of users in a room.

        Args:
            room: Room name

        Returns:
            Number of users
        """
        with self._lock:
            return len(self.room_users.get(room, set()))

    def update_user_list(self) -> None:
        """Update the user list for the active room."""
        self.users_list.Clear()

        room = self.active_room
        if not room or room == self.HUB_ROOM:
            return

        with self._lock:
            users = self.room_users.get(room, set()).copy()

        if not users:
            return

        user_entries = []
        for user_hash in users:
            with self._lock:
                nick = self.nickname_map.get(user_hash)
                is_own = user_hash == self.own_identity_hash

            if nick:
                display = f"{nick} <{user_hash[:12]}…>"
            else:
                display = f"{user_hash[:12]}…"

            if is_own:
                display += " (you)"

            user_entries.append((display, user_hash))

        user_entries.sort(key=lambda x: x[0].lower())

        for display, _ in user_entries:
            self.users_list.Append(display)

    def update_room_list_display(self) -> None:
        """Update room list with unread message indicators.

        Uses debouncing to batch rapid successive updates.
        """
        if self._room_list_update_timer and self._room_list_update_timer.IsRunning():
            self._room_list_update_pending = True
            return

        self._do_room_list_update()

        if not self._room_list_update_timer:
            self._room_list_update_timer = wx.Timer()
            self._room_list_update_timer.Bind(wx.EVT_TIMER, self._on_debounce_timer)

        self._room_list_update_pending = False
        self._room_list_update_timer.Start(100, oneShot=True)

    def _on_debounce_timer(self, event: wx.TimerEvent) -> None:
        """Handle debounce timer expiration."""
        if self._room_list_update_pending:
            self._do_room_list_update()
            self._room_list_update_pending = False

    def _do_room_list_update(self) -> None:
        """Actually perform the room list display update."""
        rooms = [self.room_list.GetString(i) for i in range(self.room_list.GetCount())]
        self.room_list.Clear()

        for room in rooms:
            clean_room = self.strip_unread_count(room)

            with self._lock:
                unread = self.unread_counts.get(clean_room, 0)
            if unread > 0 and clean_room != self.active_room:
                display = f"{clean_room} ({unread})"
            else:
                display = clean_room

            self.room_list.Append(display)

        for i in range(self.room_list.GetCount()):
            room_text = self.room_list.GetString(i)
            clean_room = room_text.split(" (")[0] if " (" in room_text else room_text
            if clean_room == self.active_room:
                self.room_list.SetSelection(i)
                break

    def is_room_joined(self, room: str) -> bool:
        """Check if a room is currently joined.

        Args:
            room: Room name

        Returns:
            True if joined
        """
        return self.room_list.FindString(room) != wx.NOT_FOUND

    def reset(self, keep_hub_room: bool = True) -> None:
        """Reset room manager to initial state.

        Args:
            keep_hub_room: Whether to keep the hub room
        """
        if self._room_list_update_timer and self._room_list_update_timer.IsRunning():
            self._room_list_update_timer.Stop()
        self._room_list_update_pending = False

        self.room_list.Clear()
        if keep_hub_room:
            self.room_list.Append(self.HUB_ROOM)
            self.room_list.SetSelection(0)
            self.active_room = self.HUB_ROOM

        with self._lock:
            self.room_users.clear()
            self.nickname_map.clear()
            self.parted_rooms.clear()
            self.own_identity_hash = None

        self.users_list.Clear()

    def get_user_info(self, user_hash: str) -> dict[str, str | bool]:
        """Get information about a user.

        Args:
            user_hash: User hash (can be short or full)

        Returns:
            Dictionary with user info
        """
        full_hash = None
        if self.active_room in self.room_users:
            with self._lock:
                for hash_str in self.room_users[self.active_room]:
                    if hash_str.startswith(user_hash):
                        full_hash = hash_str
                        break

        if not full_hash:
            return {}

        with self._lock:
            nickname = self.nickname_map.get(full_hash, "(unknown)")
            is_you = full_hash == self.own_identity_hash

        return {
            "full_hash": full_hash,
            "nickname": nickname,
            "is_you": is_you,
        }
