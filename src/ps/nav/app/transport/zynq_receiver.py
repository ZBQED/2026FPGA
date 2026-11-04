"""ZYNQ-side UDP receiver with ACK, validation and deduplication."""

from __future__ import annotations

import argparse
import socket
import threading
import time
from collections import OrderedDict
from pathlib import Path
from typing import Any, Callable, Dict

from protocol_runtime import (
    MessageClock,
    NETWORK_PATH,
    VOICE_CATALOG_PATH,
    decode_datagram,
    encode_datagram,
    load_json,
    valid_confidence,
    valid_uint32,
    valid_uuid,
    voice_runtime_action,
    with_voice_runtime_action,
)


ActionHandler = Callable[[Dict[str, Any], float], None]


class ZynqUdpReceiver:
    def __init__(
        self,
        bind_ip: str,
        bind_port: int,
        *,
        catalog_path: Path = VOICE_CATALOG_PATH,
        network_path: Path = NETWORK_PATH,
        action_handler: ActionHandler | None = None,
        video_root: Path | None = None,
        drop_first_ack: bool = False,
        require_ordered_voice: bool = False,
    ) -> None:
        self.network = load_json(network_path)
        self.catalog = load_json(catalog_path)
        self.intents = {item["intent_id"]: item for item in self.catalog["intents"]}
        self.action_handler = action_handler or self._print_action
        self.video_root = video_root
        self.drop_first_ack = drop_first_ack
        self._dropped_ack = False
        self.clock = MessageClock("ZYNQ")
        self.dedup: OrderedDict[tuple[str, str, int], float] = OrderedDict()
        self.last_heartbeat_monotonic: float | None = None
        self.actions_executed = 0
        self.require_ordered_voice = require_ordered_voice
        self.voice_highest: OrderedDict[tuple[str, str], int] = OrderedDict()
        self.message_lock = threading.RLock()

        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.socket.bind((bind_ip, bind_port))
        self.socket.settimeout(0.05)

    @property
    def address(self) -> tuple[str, int]:
        host, port = self.socket.getsockname()
        return str(host), int(port)

    def close(self) -> None:
        self.socket.close()

    def voice_online(self) -> bool:
        if self.last_heartbeat_monotonic is None:
            return False
        timeout = self.network["udp"]["offline_timeout_ms"] / 1000.0
        return time.monotonic() - self.last_heartbeat_monotonic <= timeout

    def _print_action(self, intent: dict[str, Any], confidence: float) -> None:
        action = intent["runtime_action"]
        if action["type"] == "play_sign_video":
            print(
                f"[ZYNQ] intent={intent['code']} confidence={confidence:.3f} "
                f"play={action['asset']}"
            )
        else:
            print(f"[ZYNQ] intent={intent['code']} action={action['type']}")

    def _prune_dedup(self) -> None:
        now = time.monotonic()
        retention = self.network["udp"]["dedup_retention_ms"] / 1000.0
        while self.dedup:
            _, created = next(iter(self.dedup.items()))
            if now - created <= retention:
                break
            self.dedup.popitem(last=False)
        limit = self.network["udp"]["dedup_cache_entries"]
        while len(self.dedup) > limit:
            self.dedup.popitem(last=False)

    def _ack(self, request: dict[str, Any], status: str, error_code: int) -> dict[str, Any]:
        message = self.clock.common("ACK")
        message.update(
            {
                "ack_boot_id": request["boot_id"],
                "ack_sequence": request["sequence"],
                "status": status,
                "error_code": error_code,
            }
        )
        return message

    def _heartbeat_ack(self, request: dict[str, Any]) -> dict[str, Any]:
        message = self.clock.common("HEARTBEAT_ACK")
        message.update(
            {
                "ack_boot_id": request["boot_id"],
                "ack_sequence": request["sequence"],
            }
        )
        return message

    def _common_error(self, message: dict[str, Any]) -> int:
        if message.get("protocol_version") != 1:
            return 1
        if message.get("catalog_version") != "voice-v1":
            return 2
        if (
            message.get("magic") != "MEDCOMM"
            or message.get("source") != "PYNQ"
            or not valid_uuid(message.get("boot_id"))
            or not valid_uint32(message.get("sequence"))
            or not isinstance(message.get("sender_uptime_ms"), int)
            or message.get("sender_uptime_ms", -1) < 0
        ):
            return 3
        return 0

    def process_message(self, message: dict[str, Any]) -> dict[str, Any] | None:
        with self.message_lock:
            return self._process_message_locked(message)

    def _process_message_locked(self, message: dict[str, Any]) -> dict[str, Any] | None:
        can_ack = valid_uuid(message.get("boot_id")) and valid_uint32(message.get("sequence"))
        common_error = self._common_error(message)
        if common_error:
            return self._ack(message, "rejected", common_error) if can_ack else None

        message_type = message.get("message_type")
        if message_type == "HEARTBEAT":
            self.last_heartbeat_monotonic = time.monotonic()
            return self._heartbeat_ack(message)
        if message_type != "VOICE_RESULT":
            return self._ack(message, "rejected", 3)

        intent_id = message.get("intent_id")
        if not isinstance(intent_id, int) or intent_id not in self.intents:
            return self._ack(message, "rejected", 4)
        if not valid_confidence(message.get("confidence")):
            return self._ack(message, "rejected", 5)

        intent = self.intents[intent_id]
        runtime_action = voice_runtime_action(intent)
        if runtime_action.get("forward_over_udp") is not True:
            return self._ack(message, "rejected", 4)
        asset = runtime_action.get("asset")
        if self.video_root is not None and asset and not (self.video_root / asset).is_file():
            return self._ack(message, "rejected", 6)

        self._prune_dedup()
        key = (message["source"], message["boot_id"], message["sequence"])
        if key in self.dedup:
            return self._ack(message, "duplicate", 0)

        self.dedup[key] = time.monotonic()
        self._prune_dedup()
        if self.require_ordered_voice:
            stream = (message['source'], message['boot_id'])
            previous = self.voice_highest.get(stream)
            if previous is not None:
                distance = (message['sequence'] - previous) & 0xffffffff
                if not 0 < distance < 0x80000000:
                    # A newer result has already superseded this sequence.
                    # Use the existing terminal ACK so the sender stops retrying.
                    return self._ack(message, 'duplicate', 0)
            self.voice_highest[stream] = message['sequence']
            self.voice_highest.move_to_end(stream)
            while len(self.voice_highest) > self.network['udp']['dedup_cache_entries']:
                self.voice_highest.popitem(last=False)
        self.action_handler(with_voice_runtime_action(intent), float(message["confidence"]))
        self.actions_executed += 1
        return self._ack(message, "accepted", 0)

    def serve_once(self) -> bool:
        try:
            payload, peer = self.socket.recvfrom(self.network["udp"]["max_datagram_bytes"] + 1)
        except socket.timeout:
            return False
        try:
            message = decode_datagram(payload, self.network["udp"]["max_datagram_bytes"])
        except (UnicodeDecodeError, ValueError):
            return True
        response = self.process_message(message)
        if response is None:
            return True
        if self.drop_first_ack and response["message_type"] == "ACK" and not self._dropped_ack:
            self._dropped_ack = True
            return True
        self.socket.sendto(
            encode_datagram(response, self.network["udp"]["max_datagram_bytes"]), peer
        )
        return True

    def serve_forever(self, stop_event: threading.Event) -> None:
        while not stop_event.is_set():
            try:
                self.serve_once()
            except OSError:
                if not stop_event.is_set():
                    raise




