"""Connection manager for handling hub connections."""

from __future__ import annotations

import logging
import threading
from typing import TYPE_CHECKING

import RNS
import wx

from .client import Client, ClientConfig, parse_hash
from .ui_constants import CONNECTION_TIMEOUT
from .utils import load_or_create_identity

if TYPE_CHECKING:
    from typing import Callable

logger = logging.getLogger(__name__)


class ConnectionManager:
    """Manages connection to the hub and client lifecycle."""

    def __init__(self) -> None:
        """Initialize connection manager."""
        self.client: Client | None = None
        self.is_connecting: bool = False
        self.current_configdir: str | None = None
        self.on_connection_success: Callable[[], None] | None = None
        self.on_connection_failed: Callable[[str], None] | None = None
        self.on_disconnected: Callable[[], None] | None = None
        self._pending_callbacks: dict[str, Callable] = {}

    def initialize_reticulum(
        self, configdir: str | None = None
    ) -> tuple[bool, str | None]:
        """Initialize Reticulum at startup.

        Args:
            configdir: Optional config directory path

        Returns:
            Tuple of (success, error_message)
        """
        try:
            if RNS.Reticulum.get_instance() is None:
                RNS.Reticulum(configdir=configdir)
                self.current_configdir = configdir
            return True, None
        except Exception as e:
            logger.exception("Failed to initialize Reticulum: %s", e)
            return False, str(e)

    def connect(
        self,
        identity_path: str,
        dest_name: str,
        hub_hash: str,
        nickname: str | None = None,
        hello_body: dict | None = None,
        auto_join_room: str | None = None,
        configdir: str | None = None,
    ) -> None:
        """Connect to a hub (runs in background thread).

        Args:
            identity_path: Path to identity file
            dest_name: Destination name
            hub_hash: Hub hash string
            nickname: Optional nickname
            hello_body: Optional HELLO body dict
            auto_join_room: Optional room to auto-join
            configdir: Optional config directory
        """
        if self.client or self.is_connecting:
            logger.warning("Already connected or connecting")
            return

        if configdir != self.current_configdir:
            if self.on_connection_failed:
                wx.CallAfter(
                    self.on_connection_failed,
                    f"Reticulum is already initialized with a different config directory.\n"
                    f"Current: {self.current_configdir or '(default)'}\n"
                    f"Requested: {configdir or '(default)'}\n\n"
                    f"Please restart the application to use a different config directory.",
                )
            return

        self.is_connecting = True

        thread = threading.Thread(
            target=self._connect_thread,
            args=(
                identity_path,
                dest_name,
                hub_hash,
                nickname,
                hello_body or {},
                auto_join_room,
            ),
            daemon=True,
        )
        thread.start()

    def _connect_thread(
        self,
        identity_path: str,
        dest_name: str,
        hub_hash_str: str,
        nickname: str | None,
        hello_body: dict,
        auto_join_room: str | None,
    ) -> None:
        """Background thread for connection (internal)."""
        try:
            logger.debug("_connect_thread started")

            if RNS.Reticulum.get_instance() is None:
                logger.error("Reticulum not initialized")
                wx.CallAfter(
                    self.on_connection_failed,
                    "Reticulum not initialized. Please try again.",
                )
                self.is_connecting = False
                return

            logger.debug("Loading identity from: %s", identity_path)
            identity = load_or_create_identity(identity_path)
            logger.debug("Identity loaded: %s...", identity.hash.hex()[:16])

            logger.debug("Creating client with dest_name=%s", dest_name)
            config = ClientConfig(dest_name=dest_name)
            client = Client(
                identity,
                config,
                hello_body=hello_body,
                nickname=nickname if nickname else None,
            )

            if self._pending_callbacks:
                for callback_name, callback_func in self._pending_callbacks.items():
                    setattr(client, callback_name, callback_func)
                self._pending_callbacks.clear()

            logger.debug("Parsing hub hash: %s", hub_hash_str)
            hub_hash = parse_hash(hub_hash_str)
            logger.debug("Parsed hub hash: %s", hub_hash.hex())
            logger.debug("Calling client.connect() with timeout=%s", CONNECTION_TIMEOUT)
            client.connect(
                hub_hash, wait_for_welcome=True, timeout_s=CONNECTION_TIMEOUT
            )

            logger.debug("client.connect() returned successfully")

            def _commit_connection() -> None:
                try:
                    self.client = client
                    self.is_connecting = False

                    if self.on_connection_success:
                        self.on_connection_success()
                    else:
                        logger.warning("on_connection_success callback is None")

                    if auto_join_room:
                        try:
                            client.join(auto_join_room)
                        except Exception as e:
                            logger.warning(
                                "Failed to auto-join room '%s': %s", auto_join_room, e
                            )
                except Exception as e:
                    logger.exception("Error in _commit_connection: %s", e)
                    self.is_connecting = False
                    if self.on_connection_failed:
                        self.on_connection_failed(
                            f"Connection state update failed: {e}"
                        )

            wx.CallAfter(_commit_connection)

        except OSError as e:
            self.is_connecting = False
            wx.CallAfter(self.on_connection_failed, f"Network error: {e}")
        except ValueError as e:
            self.is_connecting = False
            wx.CallAfter(
                self.on_connection_failed, f"Invalid connection parameter: {e}"
            )
        except TimeoutError as e:
            self.is_connecting = False
            wx.CallAfter(self.on_connection_failed, f"Connection timeout: {e}")
        except (RuntimeError, IOError) as e:
            self.is_connecting = False
            wx.CallAfter(self.on_connection_failed, f"Connection error: {e}")
        except Exception as e:
            logger.exception("Unexpected error during connection: %s", e)
            self.is_connecting = False
            wx.CallAfter(self.on_connection_failed, f"Unexpected error: {e}")

    def disconnect(self) -> None:
        """Disconnect from the hub."""
        if self.client:
            try:
                self.client.close()
            except Exception as e:
                logger.warning("Error during client disconnect: %s", e)

            self.client = None
            self.is_connecting = False

    def is_connected(self) -> bool:
        """Check if connected to a hub.

        Returns:
            True if connected
        """
        return self.client is not None

    def get_client(self) -> Client | None:
        """Get the current client instance.

        Returns:
            Client or None
        """
        return self.client

    def set_client_callbacks(
        self,
        on_message: Callable | None = None,
        on_notice: Callable | None = None,
        on_error: Callable | None = None,
        on_welcome: Callable | None = None,
        on_pong: Callable | None = None,
        on_joined: Callable | None = None,
        on_parted: Callable | None = None,
        on_close: Callable | None = None,
        on_resource_warning: Callable | None = None,
    ) -> None:
        """Set callbacks for client events.

        Args:
            on_message: Message received callback
            on_notice: Notice received callback
            on_error: Error received callback
            on_welcome: Welcome received callback
            on_pong: Pong received callback
            on_joined: Joined room callback
            on_parted: Parted room callback
            on_close: Connection closed callback
            on_resource_warning: Resource warning callback
        """
        callbacks = {
            "on_message": on_message,
            "on_notice": on_notice,
            "on_error": on_error,
            "on_welcome": on_welcome,
            "on_pong": on_pong,
            "on_joined": on_joined,
            "on_parted": on_parted,
            "on_close": on_close,
            "on_resource_warning": on_resource_warning,
        }

        if self.client:
            for callback_name, callback_func in callbacks.items():
                if callback_func:
                    setattr(self.client, callback_name, callback_func)
        else:
            for callback_name, callback_func in callbacks.items():
                if callback_func:
                    self._pending_callbacks[callback_name] = callback_func
