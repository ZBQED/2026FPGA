"""PYNQ-side UDP sender with retry and heartbeat support."""

from __future__ import annotations

import argparse
import socket
from pathlib import Path
from typing import Any

from protocol_runtime import (
    MessageClock,
    NETWORK_PATH,
    VOICE_CATALOG_PATH,
    decode_datagram,
    encode_datagram,
    load_json,
    voice_runtime_action,
)


class PynqUdpSender:
    def __init__(
        self,
        target: tuple[str, int],
        *,
        bind: tuple[str, int] = ("0.0.0.0", 0),
        catalog_path: Path = VOICE_CATALOG_PATH,
        network_path: Path = NETWORK_PATH,
    ) -> None:
        self.target = target
        self.network = load_json(network_path)
        self.catalog = load_json(catalog_path)
        self.by_id = {item["intent_id"]: item for item in self.catalog["intents"]}
        self.by_code = {item["code"]: item for item in self.catalog["intents"]}
        self.clock = MessageClock("PYNQ")
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.socket.bind(bind)

    def close(self) -> None:
        self.socket.close()

    def _exchange(self, message: dict[str, Any], expected_type: str) -> tuple[dict[str, Any], int]:
        udp = self.network["udp"]
        payload = encode_datagram(message, udp["max_datagram_bytes"])
        timeout_seconds = udp["ack_timeout_ms"] / 1000.0
        for attempt in range(1, udp["max_send_attempts"] + 1):
            self.socket.sendto(payload, self.target)
            self.socket.settimeout(timeout_seconds)
            try:
                while True:
                    response_payload, _ = self.socket.recvfrom(udp["max_datagram_bytes"] + 1)
                    response = decode_datagram(response_payload, udp["max_datagram_bytes"])
                    if (
                        response.get("message_type") == expected_type
                        and response.get("ack_boot_id") == message["boot_id"]
                        and response.get("ack_sequence") == message["sequence"]
                    ):
                        return response, attempt
            except socket.timeout:
                continue
        raise TimeoutError(
            f"No {expected_type} after {udp['max_send_attempts']} attempts "
            f"for sequence {message['sequence']}"
        )

    def send_voice_result(self, intent_id: int, confidence: float) -> tuple[dict[str, Any], int]:
        intent = self.by_id.get(intent_id)
        if intent is None:
            raise ValueError(f"Unknown voice intent_id: {intent_id}")
        if voice_runtime_action(intent).get("forward_over_udp") is not True:
            raise ValueError(f"Intent {intent['code']} is suppressed locally and must not be sent")
        message = self.clock.common("VOICE_RESULT")
        message.update({"intent_id": intent_id, "confidence": confidence})
        return self._exchange(message, "ACK")

    def send_voice_code(self, code: str, confidence: float) -> tuple[dict[str, Any], int]:
        intent = self.by_code.get(code)
        if intent is None:
            raise ValueError(f"Unknown voice intent code: {code}")
        return self.send_voice_result(intent["intent_id"], confidence)

    def send_heartbeat(self) -> tuple[dict[str, Any], int]:
        return self._exchange(self.clock.common("HEARTBEAT"), "HEARTBEAT_ACK")




