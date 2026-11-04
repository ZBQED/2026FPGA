"""Bounded, asynchronous TCP transport for freshly produced B speech results.

There is no file watcher or disk replay. The audio thread only enqueues a JSON
copy; all connects, writes, ACK reads, heartbeats and retries run in one worker.
Audio, feature extraction, model output and original timestamps are untouched.
"""

import json
import math
import select
import socket
import threading
import time
import uuid
from collections import deque


PROTOCOL_VERSION = "integration_network_v0.1"
TERMINAL_ACKS = frozenset(("accepted", "duplicate", "rejected", "ignored"))
MAX_ID = (1 << 63) - 1
CAPTURE_CONTEXT_VERSION = "voice_turn_v1"


class ReliableResultSender:
    def __init__(self, host, port=9000, source="B", *, heartbeat_interval=1.0,
                 ack_timeout=0.75, result_ttl=8.0, max_attempts=4,
                 max_pending=8, reconnect_interval=0.5, connect_timeout=1.0,
                 io_timeout=0.2, peer_timeout=3.5, logger=None):
        if source != "B":
            raise ValueError("This sender is exclusively the B speech node")
        if host is not None and (not isinstance(host, str) or not host.strip()):
            raise ValueError("host must be a non-empty address or None")
        if type(port) is not int or not 1 <= port <= 65535:
            raise ValueError("port must be in 1..65535")
        for name, value in (("heartbeat_interval", heartbeat_interval), ("ack_timeout", ack_timeout),
                            ("result_ttl", result_ttl), ("reconnect_interval", reconnect_interval),
                            ("connect_timeout", connect_timeout), ("io_timeout", io_timeout),
                            ("peer_timeout", peer_timeout)):
            if isinstance(value, bool) or not math.isfinite(value) or value <= 0:
                raise ValueError(name + " must be positive and finite")
        if type(max_attempts) is not int or max_attempts < 1 or type(max_pending) is not int or max_pending < 1:
            raise ValueError("max_attempts and max_pending must be positive integers")
        self.host, self.port, self.source = host, port, source
        self.boot_id = str(uuid.uuid4())
        self.heartbeat_interval, self.ack_timeout, self.result_ttl = heartbeat_interval, ack_timeout, result_ttl
        self.max_attempts, self.max_pending = max_attempts, max_pending
        self.reconnect_interval, self.connect_timeout = reconnect_interval, connect_timeout
        self.io_timeout, self.peer_timeout = io_timeout, peer_timeout
        self._logger = logger or (lambda line: print(line, flush=True))
        self._condition = threading.Condition()
        self._stop = threading.Event()
        self._queue = deque()
        self._sequence = 0
        self._last_utterance = -1
        self._socket = None
        self._buffer = b""
        self._control = {}
        self._next_connect = 0.0
        self._next_heartbeat = 0.0
        self._last_peer_ack = 0.0
        self._capture_token = None
        self._capture_generation = 0
        self._capture_updated_at = 0.0
        self._capture_ack_sequence = 0
        self._stats = dict(enqueued=0, acked=0, dropped=0, send_attempts=0,
                           connections=0, heartbeats=0, protocol_errors=0,
                           last_error="", connected=False)
        self._thread = None
        if host is not None:
            self._thread = threading.Thread(target=self._run, name="b-result-sender", daemon=True)
            self._thread.start()

    def _log(self, text):
        try:
            self._logger(text)
        except Exception:
            # A diagnostic sink cannot take down capture or the transport.
            pass

    def _next_envelope_locked(self, message_type, payload):
        if self._sequence >= MAX_ID:
            raise ValueError("Sequence exhausted; restart to obtain a new boot_id")
        self._sequence += 1
        return {"protocol_version": PROTOCOL_VERSION, "source": self.source,
                "message_type": message_type, "boot_id": self.boot_id,
                "sequence": self._sequence, "timestamp_ms": time.time_ns() // 1000000,
                "payload": payload}

    @staticmethod
    def _encode(envelope):
        return (json.dumps(envelope, ensure_ascii=False, allow_nan=False, separators=(",", ":")) + "\n").encode("utf-8")

    def send_result(self, result, *, capture_context=None):
        """Queue one newly generated utterance, without performing network I/O."""
        if self.host is None:
            return False
        if not isinstance(result, dict):
            raise ValueError("Result must be a JSON object")
        utterance = result.get("utterance_id")
        if type(utterance) is not int or not 0 <= utterance <= MAX_ID:
            raise ValueError("A fresh result requires an integer utterance_id in 0..2^63-1")
        # Freeze caller-owned nested lists and dicts once. Retries send these
        # exact bytes, preserving the capture timestamp, sequence and identity.
        payload = json.loads(json.dumps(result, ensure_ascii=False, allow_nan=False))
        with self._condition:
            if capture_context is not None and self._capture_snapshot_locked() != capture_context:
                self._log("B TCP discarded result: capture context changed before enqueue")
                return False
            if self._stop.is_set() or utterance <= self._last_utterance:
                return False
            pending = {"sequence": None, "utterance_id": utterance,
                       "payload": payload, "wire": None, "created": time.monotonic(),
                       "attempts": 0, "retry_at": 0.0}
            self._last_utterance = utterance
            if len(self._queue) >= self.max_pending:
                old = self._queue.popleft()
                self._stats["dropped"] += 1
                self._log("B TCP queue full: discarded utterance {} (no disk replay)".format(old["utterance_id"]))
            self._queue.append(pending)
            self._stats["enqueued"] += 1
            self._condition.notify_all()
        return True

    def snapshot(self):
        with self._condition:
            result = dict(self._stats)
            result.update(boot_id=self.boot_id, sequence=self._sequence, queue_depth=len(self._queue))
            return result

    def _clear_capture_context_locked(self):
        if self._capture_token is not None:
            self._capture_generation += 1
        self._capture_token = None
        self._capture_updated_at = 0.0

    def _capture_snapshot_locked(self):
        if self._stop.is_set() or time.monotonic() - self._capture_updated_at > self.peer_timeout:
            self._clear_capture_context_locked()
        return self._capture_token, self._capture_generation

    def get_capture_context_snapshot(self):
        """Local generation also detects a disconnect/reconnect within one block."""
        with self._condition:
            return self._capture_snapshot_locked()

    def get_capture_context(self):
        """Return the current receiver-issued turn token, or None when unavailable."""
        return self.get_capture_context_snapshot()[0]

    def _update_capture_context_locked(self, payload, sequence):
        # A delayed result ACK must not roll back a newer heartbeat's context.
        if sequence <= self._capture_ack_sequence:
            return
        self._capture_ack_sequence = sequence
        context = payload.get("voice_capture_context")
        token = context.get("token") if isinstance(context, dict) else None
        valid = isinstance(context, dict) and context.get("version") == CAPTURE_CONTEXT_VERSION
        if token is not None:
            try:
                valid = valid and isinstance(token, str) and str(uuid.UUID(token)) == token
            except (ValueError, AttributeError):
                valid = False
        if not valid or token is None:
            self._clear_capture_context_locked()
            return
        # If no caller observed an ACK gap, still invalidate any old recording
        # before accepting a refreshed token after the local expiry interval.
        self._capture_snapshot_locked()
        if token != self._capture_token:
            self._capture_generation += 1
        self._capture_token = token
        self._capture_updated_at = time.monotonic()

    def close(self, drain_timeout=2.0):
        # A --once audio run reaches finally immediately after enqueue. Give
        # its fresh result a bounded chance to obtain an ACK before shutdown.
        # This wait happens only at shutdown, never in send_result()/capture.
        if self._thread is not None and threading.current_thread() is not self._thread:
            deadline = time.monotonic() + max(0.0, float(drain_timeout))
            with self._condition:
                while self._queue and self._thread.is_alive() and time.monotonic() < deadline:
                    self._condition.wait(min(0.05, max(0.0, deadline - time.monotonic())))
        self._stop.set()
        with self._condition:
            self._condition.notify_all()
        if self._thread is not None and threading.current_thread() is not self._thread:
            self._thread.join(self.connect_timeout + self.io_timeout + 1.0)

    def _disconnect(self, reason=""):
        if self._socket is not None:
            try:
                self._socket.close()
            except OSError:
                pass
        self._socket = None
        self._buffer = b""
        self._control.clear()
        self._next_connect = time.monotonic() + self.reconnect_interval
        with self._condition:
            self._clear_capture_context_locked()
            self._stats["connected"] = False
            if reason:
                self._stats["last_error"] = reason

    def _send_control(self, kind):
        with self._condition:
            envelope = self._next_envelope_locked(kind, {"role": "speech_node", "board": "PYNQ-Z2"})
        self._socket.sendall(self._encode(envelope))
        self._control[envelope["sequence"]] = kind
        while len(self._control) > 16:
            del self._control[min(self._control)]
        if kind == "heartbeat":
            with self._condition:
                self._stats["heartbeats"] += 1

    def _connect(self):
        connection = socket.create_connection((self.host, self.port), timeout=self.connect_timeout)
        connection.settimeout(self.io_timeout)
        connection.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
        self._socket = connection
        self._last_peer_ack = time.monotonic()
        self._send_control("hello")
        self._next_heartbeat = time.monotonic()
        with self._condition:
            self._stats["connected"] = True
            self._stats["connections"] += 1
            self._stats["last_error"] = ""
        self._log("B TCP connected to {}:{} boot_id={}".format(self.host, self.port, self.boot_id))

    def _handle_ack(self, envelope):
        if (not isinstance(envelope, dict) or envelope.get("protocol_version") != PROTOCOL_VERSION
                or envelope.get("source") != "A" or envelope.get("message_type") != "ack"):
            return
        payload = envelope.get("payload")
        if (not isinstance(payload, dict) or payload.get("ack_boot_id") != self.boot_id
                or type(payload.get("ack_sequence")) is not int
                or not isinstance(payload.get("status"), str)
                or payload.get("status") not in TERMINAL_ACKS):
            return
        sequence = payload["ack_sequence"]
        if sequence in self._control:
            # Control ACKs are not acknowledgments of a speech result.
            if payload.get("utterance_id") is not None:
                return
            del self._control[sequence]
            with self._condition:
                self._last_peer_ack = time.monotonic()
                self._update_capture_context_locked(payload, sequence)
            return
        with self._condition:
            for pending in self._queue:
                if pending["sequence"] != sequence:
                    continue
                if type(payload.get("utterance_id")) is not int or payload["utterance_id"] != pending["utterance_id"]:
                    return
                self._queue.remove(pending)
                self._stats["acked"] += 1
                self._condition.notify_all()
                self._last_peer_ack = time.monotonic()
                self._update_capture_context_locked(payload, sequence)
                self._log("B TCP ACK utterance={} status={}".format(pending["utterance_id"], payload["status"]))
                return

    def _read_acks(self):
        if not select.select([self._socket], [], [], 0)[0]:
            return
        chunk = self._socket.recv(16384)
        if not chunk:
            raise ConnectionError("Peer closed TCP connection")
        self._buffer += chunk
        if len(self._buffer) > 65536:
            raise ConnectionError("ACK buffer exceeds 64 KiB")
        while b"\n" in self._buffer:
            line, self._buffer = self._buffer.split(b"\n", 1)
            try:
                envelope = json.loads(line.decode("utf-8"))
            except (UnicodeError, ValueError):
                with self._condition:
                    self._stats["protocol_errors"] += 1
                continue
            self._handle_ack(envelope)

    def _expire(self, now):
        with self._condition:
            while self._queue:
                pending = self._queue[0]
                expired = now - pending["created"] >= self.result_ttl
                exhausted = pending["attempts"] >= self.max_attempts and now >= pending["retry_at"]
                if not expired and not exhausted:
                    break
                self._queue.popleft()
                self._stats["dropped"] += 1
                self._log("B TCP discarded utterance={} reason={} (no disk replay)".format(
                    pending["utterance_id"], "expired" if expired else "retry limit"))

    def _send_pending(self, now):
        with self._condition:
            if not self._queue:
                return
            pending = self._queue[0]
            if now < pending["retry_at"] or pending["attempts"] >= self.max_attempts:
                return
            if pending["wire"] is None:
                # Assign on first send, so new messages are sequenced in wire
                # order even if an audio result was queued before the hello.
                envelope = self._next_envelope_locked("speech_result", pending.pop("payload"))
                pending["sequence"] = envelope["sequence"]
                pending["wire"] = self._encode(envelope)
            pending["attempts"] += 1
            pending["retry_at"] = now + self.ack_timeout
            self._stats["send_attempts"] += 1
            wire = pending["wire"]
        self._socket.sendall(wire)

    def _run(self):
        try:
            while not self._stop.is_set():
                now = time.monotonic()
                self._expire(now)
                try:
                    if self._socket is None and now >= self._next_connect:
                        self._connect()
                    if self._socket is not None:
                        self._read_acks()
                        now = time.monotonic()
                        if now - self._last_peer_ack > self.peer_timeout:
                            raise ConnectionError("Peer ACK timeout")
                        if now >= self._next_heartbeat:
                            self._send_control("heartbeat")
                            self._next_heartbeat = time.monotonic() + self.heartbeat_interval
                        # Recheck age after a slow connect, before any send.
                        self._expire(time.monotonic())
                        self._send_pending(time.monotonic())
                except (OSError, ConnectionError, ValueError) as exc:
                    self._disconnect(str(exc))
                with self._condition:
                    if not self._stop.is_set():
                        self._condition.wait(0.025)
        finally:
            self._disconnect()
            with self._condition:
                self._stats["dropped"] += len(self._queue)
                self._queue.clear()
