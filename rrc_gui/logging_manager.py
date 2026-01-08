"""Advanced logging configuration for RRC GUI."""

from __future__ import annotations

import logging
import logging.handlers
import sys
from collections.abc import Callable
from pathlib import Path


class LogManager:
    """Manages application logging configuration."""

    def __init__(self, app_dir: Path | None = None):
        """Initialize log manager.

        Args:
            app_dir: Application directory for log files.
                     Defaults to ~/.rrc-gui
        """
        self.app_dir = app_dir or Path.home() / ".rrc-gui"
        self.app_dir.mkdir(parents=True, exist_ok=True)
        self.log_dir = self.app_dir / "logs"
        self.log_dir.mkdir(parents=True, exist_ok=True)

    def setup_logging(
        self,
        level: str = "INFO",
        log_to_file: bool = True,
        log_to_console: bool = True,
        max_bytes: int = 10 * 1024 * 1024,
        backup_count: int = 5,
        format_string: str | None = None,
    ) -> None:
        """Configure application logging.

        Args:
            level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
            log_to_file: Whether to log to file
            log_to_console: Whether to log to console
            max_bytes: Maximum size of log file before rotation
            backup_count: Number of backup log files to keep
            format_string: Custom format string for log messages
        """
        numeric_level = getattr(logging, level.upper(), logging.INFO)

        root_logger = logging.getLogger()
        root_logger.setLevel(numeric_level)

        root_logger.handlers.clear()

        if format_string is None:
            format_string = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"

        formatter = logging.Formatter(format_string)

        if log_to_console:
            console_handler = logging.StreamHandler(sys.stdout)
            console_handler.setLevel(numeric_level)
            console_handler.setFormatter(formatter)
            root_logger.addHandler(console_handler)

        if log_to_file:
            log_file = self.log_dir / "rrc-gui.log"
            file_handler = logging.handlers.RotatingFileHandler(
                log_file,
                maxBytes=max_bytes,
                backupCount=backup_count,
                encoding="utf-8",
            )
            file_handler.setLevel(numeric_level)
            file_handler.setFormatter(formatter)
            root_logger.addHandler(file_handler)

        logging.getLogger("RNS").setLevel(logging.WARNING)

    def get_log_file_path(self) -> Path:
        """Get path to the main log file.

        Returns:
            Path to the log file
        """
        return self.log_dir / "rrc-gui.log"

    def get_all_log_files(self) -> list[Path]:
        """Get all log files including rotated ones.

        Returns:
            List of log file paths, newest first
        """
        try:
            log_files = sorted(
                self.log_dir.glob("rrc-gui.log*"),
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )
            return log_files
        except Exception:
            return []

    def clear_logs(self, keep_current: bool = True) -> int:
        """Clear log files.

        Args:
            keep_current: If True, keep the current log file

        Returns:
            Number of files deleted
        """
        deleted = 0
        try:
            for log_file in self.log_dir.glob("rrc-gui.log*"):
                if keep_current and log_file.name == "rrc-gui.log":
                    log_file.write_text("")
                else:
                    log_file.unlink()
                    deleted += 1
        except Exception:
            pass
        return deleted

    def get_log_level_name(self) -> str:
        """Get current log level name.

        Returns:
            Log level name (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        """
        root_logger = logging.getLogger()
        return logging.getLevelName(root_logger.level)

    def set_log_level(self, level: str) -> None:
        """Set log level for all handlers.

        Args:
            level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        """
        numeric_level = getattr(logging, level.upper(), logging.INFO)
        root_logger = logging.getLogger()
        root_logger.setLevel(numeric_level)

        for handler in root_logger.handlers:
            handler.setLevel(numeric_level)

    def tail_log(self, lines: int = 100) -> list[str]:
        """Get the last N lines from the current log file.

        Args:
            lines: Number of lines to retrieve

        Returns:
            List of log lines
        """
        log_file = self.get_log_file_path()
        if not log_file.exists():
            return []

        try:
            with open(log_file, encoding="utf-8") as f:
                return f.readlines()[-lines:]
        except Exception:
            return []

    def create_debug_log_context(self) -> DebugLogContext:
        """Create a context manager for temporary debug logging.

        Returns:
            Context manager that temporarily enables debug logging
        """
        return DebugLogContext(self)


class DebugLogContext:
    """Context manager for temporary debug logging."""

    def __init__(self, log_manager: LogManager):
        """Initialize debug log context.

        Args:
            log_manager: LogManager instance
        """
        self.log_manager = log_manager
        self.original_level: str | None = None

    def __enter__(self):
        """Enable debug logging."""
        self.original_level = self.log_manager.get_log_level_name()
        self.log_manager.set_log_level("DEBUG")
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Restore original log level."""
        if self.original_level:
            self.log_manager.set_log_level(self.original_level)


class LogViewHandler(logging.Handler):
    """Custom logging handler for displaying logs in a wx widget."""

    def __init__(self, callback: Callable[[str, str], None]):
        """Initialize log view handler.

        Args:
            callback: Function to call with formatted log records (msg, level)
        """
        super().__init__()
        self.callback = callback

    def emit(self, record: logging.LogRecord) -> None:
        """Emit a log record.

        Args:
            record: Log record to emit
        """
        try:
            msg = self.format(record)
            self.callback(msg, record.levelname)
        except Exception:
            self.handleError(record)
