from __future__ import annotations

import hashlib
import logging
import os
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import RNS

logger = logging.getLogger(__name__)

from .codec import decode, encode
from .constants import (
    B_HELLO_NAME,
    B_HELLO_VER,
    B_RES_ENCODING,
    B_RES_ID,
    B_RES_KIND,
    B_RES_SHA256,
    B_RES_SIZE,
    K_BODY,
    K_ID,
    K_ROOM,
    K_T,
    RES_KIND_MOTD,
    RES_KIND_NOTICE,
    T_ERROR,
    T_HELLO,
    T_JOIN,
    T_JOINED,
    T_MSG,
    T_NOTICE,
    T_PART,
    T_PARTED,
    T_PING,
    T_PONG,
    T_RESOURCE_ENVELOPE,
    T_WELCOME,
)
from .envelope import make_envelope, validate_envelope


class MessageTooLargeError(RuntimeError):
    """Raised when message exceeds link MDU."""

    pass


@dataclass
class _ResourceExpectation:
    """Tracks an expected incoming Resource transfer."""

    id: bytes
    kind: str
    size: int
    sha256: bytes | None
    encoding: str | None
    created_at: float
    expires_at: float
    room: str | None = None


@dataclass(frozen=True)
class ClientConfig:
    dest_name: str = "rrc.hub"
    max_resource_bytes: int = 262144
    resource_expectation_ttl_s: float = 30.0
    max_pending_resource_expectations: int = 8
    hello_interval_s: float = 3.0
    hello_max_attempts: int = 3


def parse_hash(text: str) -> bytes:
    s = str(text).strip().lower()
    if s.startswith("0x"):
        s = s[2:]
    s = "".join(ch for ch in s if not ch.isspace())
    try:
        b = bytes.fromhex(s)
    except ValueError as e:
        raise ValueError(f"invalid hash {text!r}: {e}") from e
    if len(b) != 16:
        raise ValueError(f"destination hash must be 16 bytes (got {len(b)})")
    return b


class Client:
    def __init__(
        self,
        identity: RNS.Identity,
        config: ClientConfig | None = None,
        *,
        hello_body: dict[int, Any] | None = None,
        nickname: str | None = None,
    ) -> None:
        self.identity = identity
        self.config = config or ClientConfig()

        self.hello_body: dict[int, Any] = dict(hello_body or {})
        self.hello_body.setdefault(B_HELLO_NAME, "rrc-client")
        self.hello_body.setdefault(B_HELLO_VER, "0.1.0")

        self.nickname = nickname

        self.link: RNS.Link | None = None
        self.rooms: set[str] = set()

        self._lock = threading.RLock()
        self._welcomed = threading.Event()

        self._resource_expectations: dict[bytes, _ResourceExpectation] = {}
        self._active_resources: set[RNS.Resource] = set()
        self._resource_to_expectation: dict[RNS.Resource, _ResourceExpectation] = {}

        self.on_message: Callable[[dict], None] | None = None
        self.on_notice: Callable[[dict], None] | None = None
        self.on_error: Callable[[dict], None] | None = None
        self.on_welcome: Callable[[dict], None] | None = None
        self.on_joined: Callable[[str, dict], None] | None = None
        self.on_parted: Callable[[str, dict], None] | None = None
        self.on_close: Callable[[], None] | None = None
        self.on_resource_warning: Callable[[str], None] | None = None
        self.on_pong: Callable[[dict], None] | None = None

    def connect(
        self,
        hub_dest_hash: bytes,
        *,
        wait_for_welcome: bool = True,
        timeout_s: float = 20.0,
    ) -> None:
        self._welcomed.clear()

        RNS.Transport.request_path(hub_dest_hash)

        try:
            path_wait_deadline = time.monotonic() + min(5.0, float(timeout_s))
            while time.monotonic() < path_wait_deadline:
                if RNS.Transport.has_path(hub_dest_hash):
                    break
                time.sleep(0.1)
        except Exception as e:
            logger.warning("Error during path wait: %s", e)

        recall_deadline = time.monotonic() + float(timeout_s)
        hub_identity: RNS.Identity | None = None
        while time.monotonic() < recall_deadline:
            hub_identity = RNS.Identity.recall(hub_dest_hash)
            if hub_identity is not None:
                break
            time.sleep(0.1)

        if hub_identity is None:
            raise TimeoutError(
                "Could not recall hub identity from destination hash. "
                "Make sure the hub is announcing and reachable."
            )

        app_name, aspects = RNS.Destination.app_and_aspects_from_name(
            self.config.dest_name
        )

        hub_dest = RNS.Destination(
            hub_identity,
            RNS.Destination.OUT,
            RNS.Destination.SINGLE,
            app_name,
            *aspects,
        )

        if hub_dest.hash != hub_dest_hash:
            raise ValueError(
                "Hub hash does not match dest-name. "
                "Check --dest-name (must match hub) and --hub."
            )

        def _send_hello(link: RNS.Link) -> None:
            envelope = make_envelope(
                T_HELLO, src=self.identity.hash, body=self.hello_body
            )
            if self.nickname:
                from .constants import K_NICK

                envelope[K_NICK] = self.nickname
            payload = encode(envelope)
            RNS.Packet(link, payload).send()

        def _hello_loop(link: RNS.Link, deadline: float) -> None:
            hello_interval_s = self.config.hello_interval_s
            max_attempts = self.config.hello_max_attempts

            next_send = time.monotonic()
            attempts = 0

            while time.monotonic() < deadline and not self._welcomed.is_set():
                with self._lock:
                    if self.link is not link:
                        return

                now = time.monotonic()
                if attempts < max_attempts and now >= next_send:
                    try:
                        _send_hello(link)
                    except Exception as e:
                        logger.warning(
                            "Failed to send HELLO (attempt %d/%d): %s",
                            attempts + 1,
                            max_attempts,
                            e,
                        )
                    attempts += 1
                    next_send = now + hello_interval_s

                time.sleep(0.1)

        def _established(established_link: RNS.Link) -> None:
            try:
                established_link.identify(self.identity)
            except Exception as e:
                logger.warning("Failed to identify on established link: %s", e)
            deadline = time.monotonic() + float(timeout_s)
            t = threading.Thread(
                target=_hello_loop,
                args=(established_link, deadline),
                name="rrc-client-hello",
                daemon=True,
            )
            t.start()

        def _closed(_: RNS.Link) -> None:
            with self._lock:
                self.link = None
                self.rooms.clear()
                active_resources = list(self._active_resources)
                self._resource_expectations.clear()
                self._active_resources.clear()
                self._resource_to_expectation.clear()

            for resource in active_resources:
                try:
                    if hasattr(resource, "cancel") and callable(resource.cancel):
                        resource.cancel()
                except Exception as e:
                    logger.debug("Error canceling resource in _closed callback: %s", e)

            if self.on_close:
                try:
                    self.on_close()
                except Exception as e:
                    logger.exception("Error in on_close callback: %s", e)

        found_existing = False

        if hasattr(RNS.Transport, "active_links") and RNS.Transport.active_links:
            for existing_link in list(RNS.Transport.active_links):
                try:
                    dest_hash = (
                        existing_link.destination.hash
                        if existing_link.destination
                        else None
                    )
                    if dest_hash == hub_dest_hash:
                        existing_link.teardown()
                        found_existing = True
                except Exception as e:
                    logger.debug("Error checking/tearing down existing link: %s", e)

        if hasattr(RNS.Transport, "pending_links") and RNS.Transport.pending_links:
            for existing_link in list(RNS.Transport.pending_links):
                try:
                    dest_hash = (
                        existing_link.destination.hash
                        if existing_link.destination
                        else None
                    )
                    if dest_hash == hub_dest_hash:
                        existing_link.teardown()
                        found_existing = True
                except Exception as e:
                    logger.debug("Error checking/tearing down pending link: %s", e)

        if hasattr(RNS.Transport, "link_table") and RNS.Transport.link_table:
            for _link_id, link_entry in list(RNS.Transport.link_table.items()):
                try:
                    existing_link = (
                        link_entry[0]
                        if isinstance(link_entry, (tuple, list))
                        else link_entry
                    )
                    if (
                        hasattr(existing_link, "destination")
                        and existing_link.destination
                    ):
                        if existing_link.destination.hash == hub_dest_hash:
                            existing_link.teardown()
                            found_existing = True
                except Exception as e:
                    logger.debug(
                        "Error checking/tearing down link from link_table: %s", e
                    )

        if found_existing:
            time.sleep(1.0)

        link = RNS.Link(
            hub_dest, established_callback=_established, closed_callback=_closed
        )
        link.set_packet_callback(lambda data, pkt: self._on_packet(data))

        link.set_resource_strategy(RNS.Link.ACCEPT_APP)
        link.set_resource_started_callback(self._resource_advertised)
        link.set_resource_concluded_callback(self._resource_concluded)

        with self._lock:
            self.link = link

        if wait_for_welcome:
            logger.debug("Waiting for WELCOME (timeout=%ss)...", timeout_s)
            welcome_timeout = float(timeout_s)
            if not self._welcomed.wait(timeout=welcome_timeout):
                logger.error("Timed out waiting for WELCOME")
                raise TimeoutError("Timed out waiting for WELCOME")
            logger.debug("WELCOME received")

    def close(self) -> None:
        with self._lock:
            link = self.link
            self.link = None
            self.rooms.clear()
            self._resource_expectations.clear()

            active_resources = list(self._active_resources)
            self._active_resources.clear()
            self._resource_to_expectation.clear()

        for resource in active_resources:
            try:
                if hasattr(resource, "cancel") and callable(resource.cancel):
                    resource.cancel()
                if hasattr(resource, "data") and resource.data:
                    try:
                        resource.data.close()
                    except Exception as e:
                        logger.debug(
                            "Error closing resource data during cleanup: %s", e
                        )
            except Exception as e:
                logger.debug("Error canceling resource during cleanup: %s", e)

        if link is not None:
            try:
                link.teardown()
            except Exception as e:
                logger.debug("Error tearing down link during close: %s", e)

    def join(self, room: str, *, key: str | None = None) -> None:
        r = room.strip().lower()
        body: Any = key if (isinstance(key, str) and key) else None
        self._send(make_envelope(T_JOIN, src=self.identity.hash, room=r, body=body))

    def part(self, room: str) -> None:
        r = room.strip().lower()
        self._send(make_envelope(T_PART, src=self.identity.hash, room=r))
        with self._lock:
            self.rooms.discard(r)

    def msg(self, room: str, text: str) -> bytes:
        r = room.strip().lower()
        env = make_envelope(T_MSG, src=self.identity.hash, room=r, body=text)
        self._send(env)
        mid = env.get(K_ID)
        if isinstance(mid, bytearray):
            return bytes(mid)
        if isinstance(mid, bytes):
            return mid
        raise TypeError("message id (K_ID) must be bytes")

    def notice(self, room: str, text: str) -> None:
        r = room.strip().lower()
        self._send(make_envelope(T_NOTICE, src=self.identity.hash, room=r, body=text))

    def _packet_would_fit(self, link: RNS.Link, payload: bytes) -> bool:
        """Check if packet would fit within link MDU."""
        try:
            pkt = RNS.Packet(link, payload)
            pkt.pack()
            return True
        except Exception as e:
            logger.debug("Packet would not fit in MDU: %s", e)
            return False

    def _cleanup_expired_expectations(self) -> None:
        """Remove expired resource expectations."""
        now = time.monotonic()
        with self._lock:
            expired = [
                rid
                for rid, exp in self._resource_expectations.items()
                if now >= exp.expires_at
            ]
            for rid in expired:
                del self._resource_expectations[rid]

    def _find_resource_expectation(self, size: int) -> _ResourceExpectation | None:
        """Find matching resource expectation by size."""
        self._cleanup_expired_expectations()

        with self._lock:
            for rid, exp in list(self._resource_expectations.items()):
                if exp.size == size:
                    return self._resource_expectations.pop(rid, None)
        return None

    def _resource_advertised(self, resource: RNS.Resource) -> bool:
        """
        Callback when a Resource is advertised by the hub.
        Returns True to accept, False to reject.
        """
        size = resource.total_size if hasattr(resource, "total_size") else resource.size

        if size > self.config.max_resource_bytes:
            return False

        exp = self._find_resource_expectation(size)
        if not exp:
            return False

        with self._lock:
            self._active_resources.add(resource)
            self._resource_to_expectation[resource] = exp
        return True

    def _resource_concluded(self, resource: RNS.Resource) -> None:
        """Callback when a Resource transfer completes."""
        with self._lock:
            self._active_resources.discard(resource)
            matched_exp = self._resource_to_expectation.pop(resource, None)

        if not matched_exp:
            try:
                if hasattr(resource, "data") and resource.data:
                    resource.data.close()
            except Exception as e:
                logger.debug("Error closing unexpected resource data: %s", e)
            return

        if resource.status != RNS.Resource.COMPLETE:
            try:
                if hasattr(resource, "data") and resource.data:
                    resource.data.close()
            except Exception as e:
                logger.debug("Error closing incomplete resource data: %s", e)
            return

        data = None
        try:
            data = resource.data.read()
        except Exception as e:
            logger.warning("Failed to read resource data: %s", e)
        finally:
            try:
                if hasattr(resource, "data") and resource.data:
                    resource.data.close()
            except Exception as e:
                logger.debug("Error closing resource data in finally block: %s", e)

        if data is None:
            return

        if matched_exp.sha256:
            computed_hash = hashlib.sha256(data).digest()
            if computed_hash != matched_exp.sha256:
                logger.warning("Resource SHA256 mismatch for kind=%s", matched_exp.kind)
                return

        if matched_exp.kind == RES_KIND_NOTICE:
            try:
                encoding = matched_exp.encoding or "utf-8"
                text = data.decode(encoding)
                env = {
                    K_T: T_NOTICE,
                    K_BODY: text,
                    K_ROOM: matched_exp.room,
                }
                if self.on_notice:
                    try:
                        self.on_notice(env)
                    except Exception as e:
                        logger.exception("Error in on_notice callback: %s", e)
            except UnicodeDecodeError as e:
                logger.warning("Failed to decode NOTICE resource as text: %s", e)
            except Exception as e:
                logger.exception("Unexpected error processing NOTICE resource: %s", e)
        elif matched_exp.kind == RES_KIND_MOTD:
            try:
                encoding = matched_exp.encoding or "utf-8"
                text = data.decode(encoding)
                env = {
                    K_T: T_NOTICE,
                    K_BODY: text,
                    K_ROOM: None,
                }
                if self.on_notice:
                    try:
                        self.on_notice(env)
                    except Exception as e:
                        logger.exception("Error in on_notice callback for MOTD: %s", e)
            except UnicodeDecodeError as e:
                logger.warning("Failed to decode MOTD resource as text: %s", e)
            except Exception as e:
                logger.exception("Unexpected error processing MOTD resource: %s", e)

    def _send(self, env: dict) -> None:
        with self._lock:
            link = self.link
        if link is None:
            raise RuntimeError("not connected")
        payload = encode(env)

        if not self._packet_would_fit(link, payload):
            msg_type = env.get(K_T)
            if self.on_resource_warning:
                if msg_type == T_MSG:
                    warning = (
                        "Message is too large to send. Please shorten your message."
                    )
                elif msg_type == T_NOTICE:
                    warning = "Notice is too large to send. Please shorten the notice."
                else:
                    warning = "Message is too large to send over this link."
                try:
                    self.on_resource_warning(warning)
                except Exception:
                    pass
            raise MessageTooLargeError("Message exceeds link MDU")

        RNS.Packet(link, payload).send()

    def _on_packet(self, data: bytes) -> None:
        try:
            env = decode(data)
            validate_envelope(env)
        except Exception as e:
            logger.debug("Failed to decode/validate packet: %s", e)
            return

        t = env.get(K_T)
        logger.debug("Received packet type: %s", t)

        if t == T_PING:
            body = env.get(K_BODY)
            try:
                self._send(make_envelope(T_PONG, src=self.identity.hash, body=body))
            except Exception:
                pass
            return

        if t == T_PONG:
            if self.on_pong:
                try:
                    self.on_pong(env)
                except Exception:
                    pass
            return

        if t == T_RESOURCE_ENVELOPE:
            body = env.get(K_BODY)
            if not isinstance(body, dict):
                return

            try:
                rid = body.get(B_RES_ID)
                kind = body.get(B_RES_KIND)
                size = body.get(B_RES_SIZE)
                sha256 = body.get(B_RES_SHA256)
                encoding = body.get(B_RES_ENCODING)

                if not isinstance(rid, (bytes, bytearray)):
                    return
                if not isinstance(kind, str):
                    return
                if not isinstance(size, int) or size <= 0:
                    return
                if sha256 is not None and not isinstance(sha256, (bytes, bytearray)):
                    return
                if encoding is not None and not isinstance(encoding, str):
                    return

                if size > self.config.max_resource_bytes:
                    return

                now = time.monotonic()
                room = env.get(K_ROOM)

                with self._lock:
                    if (
                        len(self._resource_expectations)
                        >= self.config.max_pending_resource_expectations
                    ):
                        oldest_rid = min(
                            self._resource_expectations.keys(),
                            key=lambda r: self._resource_expectations[r].created_at,
                        )
                        del self._resource_expectations[oldest_rid]

                    self._resource_expectations[bytes(rid)] = _ResourceExpectation(
                        id=bytes(rid),
                        kind=kind,
                        size=size,
                        sha256=bytes(sha256) if sha256 else None,
                        encoding=encoding,
                        created_at=now,
                        expires_at=now + self.config.resource_expectation_ttl_s,
                        room=room if isinstance(room, str) else None,
                    )
            except Exception as e:
                logger.warning("Failed to process resource envelope: %s", e)
            return

        if t == T_WELCOME:
            logger.debug("Received T_WELCOME")
            self._welcomed.set()
            if self.on_welcome:
                try:
                    self.on_welcome(env)
                except Exception as e:
                    logger.exception("Error in on_welcome callback: %s", e)
            else:
                logger.warning("Received WELCOME but on_welcome callback is None")
            return

        if t == T_JOINED:
            room = env.get(K_ROOM)
            if isinstance(room, str) and room:
                r = room.strip().lower()
                with self._lock:
                    self.rooms.add(r)
                if self.on_joined:
                    try:
                        self.on_joined(r, env)
                    except Exception as e:
                        logger.exception("Error in on_joined callback: %s", e)
            return

        if t == T_PARTED:
            room = env.get(K_ROOM)
            if isinstance(room, str) and room:
                r = room.strip().lower()
                with self._lock:
                    self.rooms.discard(r)
                if self.on_parted:
                    try:
                        self.on_parted(r, env)
                    except Exception as e:
                        logger.exception("Error in on_parted callback: %s", e)
            return

        if t == T_MSG:
            if self.on_message:
                try:
                    self.on_message(env)
                except Exception as e:
                    logger.exception("Error in on_message callback: %s", e)
            return

        if t == T_NOTICE:
            logger.debug("Received T_NOTICE, on_notice=%s", self.on_notice)
            if self.on_notice:
                try:
                    self.on_notice(env)
                except Exception as e:
                    logger.exception("Error in on_notice callback: %s", e)
            else:
                logger.warning("Received NOTICE but on_notice callback is None")
            return

        if t == T_ERROR:
            if self.on_error:
                try:
                    self.on_error(env)
                except Exception as e:
                    logger.exception("Error in on_error callback: %s", e)
            return
