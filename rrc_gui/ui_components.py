"""UI components for the main chat window."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import wx
import wx.richtext

from .ui_constants import (
    BUTTON_WIDTH,
    DEFAULT_BORDER,
    ROOM_LIST_WIDTH,
    USER_LIST_WIDTH,
)

if TYPE_CHECKING:
    from typing import Callable

logger = logging.getLogger(__name__)


class UIComponents:
    """Manages UI component creation and layout."""

    def __init__(self, parent: wx.Frame) -> None:
        """Initialize UI components.

        Args:
            parent: Parent frame
        """
        self.parent = parent
        self.panel: wx.Panel | None = None
        self.left_splitter: wx.SplitterWindow | None = None
        self.right_splitter: wx.SplitterWindow | None = None
        self.room_list: wx.ListBox | None = None
        self.users_list: wx.ListBox | None = None
        self.message_display: wx.richtext.RichTextCtrl | None = None
        self.message_input: wx.TextCtrl | None = None
        self.send_btn: wx.Button | None = None
        self.join_btn: wx.Button | None = None
        self.part_btn: wx.Button | None = None
        self.active_room_label: wx.StaticText | None = None
        self.users_panel: wx.Panel | None = None
        self.users_panel_in_sizer: bool = False
        self.saved_left_sash: int = ROOM_LIST_WIDTH
        self.saved_right_sash: int | None = None

    def create_ui(
        self,
        hub_room: str,
        saved_left_sash: int | None = None,
        saved_right_sash: int | None = None,
    ) -> None:
        """Create all UI components.

        Args:
            hub_room: Name of the hub room
            saved_left_sash: Saved left splitter position
            saved_right_sash: Saved right splitter position
        """
        if saved_left_sash is not None:
            self.saved_left_sash = saved_left_sash
        if saved_right_sash is not None:
            self.saved_right_sash = saved_right_sash

        self.panel = wx.Panel(self.parent)
        main_sizer = wx.BoxSizer(wx.HORIZONTAL)

        self.left_splitter = wx.SplitterWindow(self.panel, style=wx.SP_LIVE_UPDATE)
        self.left_splitter.SetMinimumPaneSize(100)

        left_panel = wx.Panel(self.left_splitter)
        left_box = wx.BoxSizer(wx.VERTICAL)

        room_label = wx.StaticText(left_panel, label="Rooms:")
        left_box.Add(room_label, flag=wx.ALL, border=DEFAULT_BORDER)
        self.room_list = wx.ListBox(left_panel)
        self.room_list.Append(hub_room)
        self.room_list.SetSelection(0)
        left_box.Add(
            self.room_list, proportion=1, flag=wx.EXPAND | wx.ALL, border=DEFAULT_BORDER
        )

        room_btn_box = wx.BoxSizer(wx.HORIZONTAL)
        self.join_btn = wx.Button(left_panel, label="Join", size=(BUTTON_WIDTH, -1))
        self.part_btn = wx.Button(left_panel, label="Part", size=(BUTTON_WIDTH, -1))
        room_btn_box.Add(self.join_btn, flag=wx.RIGHT, border=DEFAULT_BORDER)
        room_btn_box.Add(self.part_btn)
        left_box.Add(room_btn_box, flag=wx.ALL | wx.ALIGN_CENTER, border=DEFAULT_BORDER)
        left_panel.SetSizer(left_box)

        self.right_splitter = wx.SplitterWindow(
            self.left_splitter, style=wx.SP_LIVE_UPDATE
        )
        self.right_splitter.SetMinimumPaneSize(100)

        middle_panel = wx.Panel(self.right_splitter)
        right_box = wx.BoxSizer(wx.VERTICAL)

        self.active_room_label = wx.StaticText(
            middle_panel, label=f"Active room: {hub_room}"
        )
        right_box.Add(self.active_room_label, flag=wx.ALL, border=DEFAULT_BORDER)

        self.message_display = wx.richtext.RichTextCtrl(
            middle_panel, style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_WORDWRAP
        )
        right_box.Add(
            self.message_display,
            proportion=1,
            flag=wx.EXPAND | wx.ALL,
            border=DEFAULT_BORDER,
        )

        input_box = wx.BoxSizer(wx.HORIZONTAL)
        self.message_input = wx.TextCtrl(middle_panel, style=wx.TE_PROCESS_ENTER)
        input_box.Add(self.message_input, proportion=1, flag=wx.EXPAND)
        self.send_btn = wx.Button(middle_panel, label="Send")
        input_box.Add(self.send_btn, flag=wx.LEFT, border=DEFAULT_BORDER)
        right_box.Add(input_box, flag=wx.EXPAND | wx.ALL, border=DEFAULT_BORDER)
        middle_panel.SetSizer(right_box)

        self.users_panel = wx.Panel(self.right_splitter)
        users_box = wx.BoxSizer(wx.VERTICAL)
        users_label = wx.StaticText(self.users_panel, label="Users:")
        users_box.Add(users_label, flag=wx.ALL, border=DEFAULT_BORDER)
        self.users_list = wx.ListBox(self.users_panel)
        users_box.Add(
            self.users_list,
            proportion=1,
            flag=wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM,
            border=DEFAULT_BORDER,
        )
        self.users_panel.SetSizer(users_box)

        self.left_splitter.SplitVertically(
            left_panel, self.right_splitter, self.saved_left_sash
        )
        self.right_splitter.Initialize(middle_panel)
        self.users_panel_in_sizer = False

        self.users_panel.Hide()

        main_sizer.Add(self.left_splitter, proportion=1, flag=wx.EXPAND)
        self.panel.SetSizer(main_sizer)

    def set_active_room_label(self, room: str) -> None:
        """Update the active room label.

        Args:
            room: Room name
        """
        if self.active_room_label:
            self.active_room_label.SetLabel(f"Active room: {room}")

    def show_user_list(self) -> None:
        """Show the user list panel (split right splitter)."""
        if self.users_panel_in_sizer or not self.right_splitter:
            return

        self.users_panel.Show()

        middle_panel = self.right_splitter.GetWindow1()
        self.right_splitter.SplitVertically(middle_panel, self.users_panel)

        if self.saved_right_sash is not None:
            self.right_splitter.SetSashPosition(self.saved_right_sash)
        else:
            total_width = self.right_splitter.GetSize().GetWidth()
            self.right_splitter.SetSashPosition(total_width - USER_LIST_WIDTH)

        self.users_panel_in_sizer = True

    def hide_user_list(self, force: bool = False) -> None:
        """Hide the user list panel (unsplit right splitter).

        Args:
            force: Force hide even if already marked as hidden
        """
        if not self.right_splitter:
            return

        if not self.users_panel_in_sizer and not force:
            return

        if self.users_panel:
            self.users_panel.Hide()

        if self.right_splitter.IsSplit():
            self.right_splitter.Unsplit(self.users_panel)
        self.users_panel_in_sizer = False

    def set_controls_enabled(self, enabled: bool) -> None:
        """Enable/disable controls based on connection state.

        Args:
            enabled: Whether to enable controls
        """
        if self.room_list:
            self.room_list.Enable(enabled)
        if self.join_btn:
            self.join_btn.Enable(enabled)
        if self.part_btn:
            self.part_btn.Enable(enabled)
        if self.message_input:
            self.message_input.Enable(enabled)
        if self.send_btn:
            self.send_btn.Enable(enabled)

    def get_left_sash_position(self) -> int:
        """Get the current left splitter position.

        Returns:
            Sash position
        """
        if self.left_splitter:
            return self.left_splitter.GetSashPosition()
        return self.saved_left_sash

    def get_right_sash_position(self) -> int | None:
        """Get the current right splitter position.

        Returns:
            Sash position or None
        """
        if self.right_splitter and self.users_panel_in_sizer:
            return self.right_splitter.GetSashPosition()
        return None

    def bind_events(
        self,
        on_room_select: Callable | None = None,
        on_join_room: Callable | None = None,
        on_part_room: Callable | None = None,
        on_send_message: Callable | None = None,
        on_input_key_down: Callable | None = None,
        on_user_double_click: Callable | None = None,
    ) -> None:
        """Bind event handlers to UI components.

        Args:
            on_room_select: Room selection callback
            on_join_room: Join button callback
            on_part_room: Part button callback
            on_send_message: Send message callback
            on_input_key_down: Input key down callback
            on_user_double_click: User double-click callback
        """
        if self.room_list and on_room_select:
            self.room_list.Bind(wx.EVT_LISTBOX, on_room_select)

        if self.join_btn and on_join_room:
            self.join_btn.Bind(wx.EVT_BUTTON, on_join_room)

        if self.part_btn and on_part_room:
            self.part_btn.Bind(wx.EVT_BUTTON, on_part_room)

        if self.send_btn and on_send_message:
            self.send_btn.Bind(wx.EVT_BUTTON, on_send_message)

        if self.message_input:
            if on_send_message:
                self.message_input.Bind(wx.EVT_TEXT_ENTER, on_send_message)
            if on_input_key_down:
                self.message_input.Bind(wx.EVT_KEY_DOWN, on_input_key_down)

        if self.users_list and on_user_double_click:
            self.users_list.Bind(wx.EVT_LISTBOX_DCLICK, on_user_double_click)

    def clear_message_input(self) -> None:
        """Clear the message input field."""
        if self.message_input:
            self.message_input.Clear()

    def get_message_input_value(self) -> str:
        """Get the current message input value.

        Returns:
            Input text
        """
        if self.message_input:
            return self.message_input.GetValue()
        return ""

    def set_message_input_value(self, value: str) -> None:
        """Set the message input value.

        Args:
            value: Text to set
        """
        if self.message_input:
            self.message_input.SetValue(value)
            self.message_input.SetInsertionPointEnd()
