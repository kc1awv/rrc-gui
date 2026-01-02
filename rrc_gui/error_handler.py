"""Centralized error handling and user feedback for RRC GUI."""

from __future__ import annotations

import logging
from enum import Enum

import wx

logger = logging.getLogger(__name__)


class ErrorSeverity(Enum):
    """Error severity levels."""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class ErrorHandler:
    """Centralized error handling and user feedback."""

    def __init__(self, parent: wx.Window) -> None:
        """Initialize error handler.

        Args:
            parent: Parent window for dialogs.
        """
        self.parent = parent

    def show_error(
        self,
        message: str,
        title: str | None = None,
        severity: ErrorSeverity = ErrorSeverity.ERROR,
        log: bool = True,
    ) -> None:
        """Show an error dialog to the user.

        Args:
            message: Error message to display.
            title: Dialog title (auto-generated if None).
            severity: Severity level.
            log: Whether to log the error.
        """
        if log:
            if severity == ErrorSeverity.INFO:
                logger.info(message)
            elif severity == ErrorSeverity.WARNING:
                logger.warning(message)
            elif severity == ErrorSeverity.ERROR:
                logger.error(message)
            elif severity == ErrorSeverity.CRITICAL:
                logger.critical(message)

        if severity == ErrorSeverity.INFO:
            icon = wx.ICON_INFORMATION
            default_title = "Information"
        elif severity == ErrorSeverity.WARNING:
            icon = wx.ICON_WARNING
            default_title = "Warning"
        elif severity == ErrorSeverity.ERROR:
            icon = wx.ICON_ERROR
            default_title = "Error"
        elif severity == ErrorSeverity.CRITICAL:
            icon = wx.ICON_ERROR
            default_title = "Critical Error"
        else:
            icon = wx.ICON_INFORMATION
            default_title = "Message"

        final_title = title if title else default_title

        wx.MessageBox(message, final_title, wx.OK | icon, self.parent)

    def show_validation_error(self, field: str, issue: str) -> None:
        """Show a validation error for a specific field.

        Args:
            field: Field name that failed validation.
            issue: Description of the validation issue.
        """
        message = f"{field}: {issue}"
        self.show_error(message, "Validation Error", ErrorSeverity.WARNING)

    def show_network_error(self, operation: str, error: Exception) -> None:
        """Show a network operation error.

        Args:
            operation: Operation that failed (e.g., "connect", "send message").
            error: Exception that occurred.
        """
        message = f"Network error during {operation}:\n\n{error}"
        self.show_error(message, "Network Error", ErrorSeverity.ERROR)

    def show_rate_limit_warning(self, current: int, limit: int) -> None:
        """Show rate limit warning.

        Args:
            current: Current message count.
            limit: Rate limit.
        """
        message = (
            f"Rate limit: maximum {limit} messages per minute.\n\n"
            f"You have sent {current} messages in the last minute.\n"
            "Please wait a moment before sending."
        )
        self.show_error(message, "Sending Too Fast", ErrorSeverity.WARNING)

    def show_message_too_long_error(self, length: int, max_length: int) -> None:
        """Show message length error.

        Args:
            length: Actual message length.
            max_length: Maximum allowed length.
        """
        message = (
            f"Message too long ({length} characters).\n\n"
            f"Maximum length is {max_length} characters."
        )
        self.show_error(message, "Message Too Long", ErrorSeverity.WARNING)

    def show_invalid_room_name_error(self) -> None:
        """Show invalid room name error."""
        message = (
            "Invalid room name.\n\n"
            "Room names must:\n"
            "• Be 1-64 characters long\n"
            "• Not contain spaces\n"
            "• Contain only letters, numbers, hyphens, underscores, dots, or # symbols\n\n"
            "Examples: 'general', 'test-room', 'room_1', 'dev.chat', '#kc1awv'"
        )
        self.show_error(message, "Invalid Room Name", ErrorSeverity.WARNING)

    def confirm_action(self, message: str, title: str = "Confirm") -> bool:
        """Show a confirmation dialog.

        Args:
            message: Confirmation message.
            title: Dialog title.

        Returns:
            True if user confirmed, False otherwise.
        """
        result = wx.MessageBox(
            message, title, wx.YES_NO | wx.NO_DEFAULT | wx.ICON_QUESTION, self.parent
        )
        return result == wx.YES
