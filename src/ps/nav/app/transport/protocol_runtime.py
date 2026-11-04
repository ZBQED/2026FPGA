"""Shared phase-2 runtime helpers using only the Python standard library."""

from __future__ import annotations

import json
import math
import re
import time
import uuid
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PHASE1_ROOT = PROJECT_ROOT / "phase1_udp"
VOICE_CATALOG_PATH = PHASE1_ROOT / "config" / "voice_intents_v1.json"
SIGN_CATALOG_PATH = PHASE1_ROOT / "config" / "sign_intents_v1.json"
NETWORK_PATH = PHASE1_ROOT / "config" / "network_v1.json"


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def encode_datagram(message: dict[str, Any], max_bytes: int) -> bytes:
    payload = json.dumps(message, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(payload) > max_bytes:
        raise ValueError(f"UDP message is {len(payload)} bytes; limit is {max_bytes}")
    return payload


def decode_datagram(payload: bytes, max_bytes: int) -> dict[str, Any]:
    if len(payload) > max_bytes:
        raise ValueError("UDP message exceeds configured limit")
    message = json.loads(payload.decode("utf-8-sig"))
    if not isinstance(message, dict):
        raise ValueError("UDP message must be a JSON object")
    return message


def valid_uuid(value: Any) -> bool:
    try:
        uuid.UUID(str(value))
    except (ValueError, TypeError, AttributeError):
        return False
    return True


def valid_uint32(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= 0xFFFFFFFF


def valid_confidence(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
        and 0.0 <= float(value) <= 1.0
    )


def voice_runtime_action(intent: dict[str, Any]) -> dict[str, Any]:
    """Interpret the exact Excel action without changing the source catalog."""
    if intent.get("type") == "业务":
        match = re.fullmatch(r"播放\s+(.+\.mp4)", str(intent.get("system_action", "")).strip())
        if not match:
            raise ValueError(f"Invalid source system action: {intent.get('system_action')!r}")
        return {
            "type": "play_sign_video",
            "asset": match.group(1),
            "forward_over_udp": True,
        }
    reject_actions = {
        "SILENCE": {"type": "continue_listening", "forward_over_udp": False},
        "UNKNOWN_SPEECH": {"type": "request_repeat", "forward_over_udp": True},
        "BACKGROUND_NOISE": {"type": "discard", "forward_over_udp": False},
    }
    try:
        return dict(reject_actions[str(intent["code"])])
    except KeyError as error:
        raise ValueError(f"Unknown source reject code: {intent.get('code')!r}") from error


def with_voice_runtime_action(intent: dict[str, Any]) -> dict[str, Any]:
    runtime_intent = dict(intent)
    runtime_intent["runtime_action"] = voice_runtime_action(intent)
    return runtime_intent


class MessageClock:
    def __init__(self, source: str) -> None:
        self.source = source
        self.boot_id = str(uuid.uuid4())
        self.started = time.monotonic()
        self.sequence = 0

    def next_sequence(self) -> int:
        value = self.sequence
        self.sequence = (self.sequence + 1) & 0xFFFFFFFF
        return value

    def common(self, message_type: str, sequence: int | None = None) -> dict[str, Any]:
        return {
            "magic": "MEDCOMM",
            "protocol_version": 1,
            "catalog_version": "voice-v1",
            "message_type": message_type,
            "source": self.source,
            "boot_id": self.boot_id,
            "sequence": self.next_sequence() if sequence is None else sequence,
            "sender_uptime_ms": int((time.monotonic() - self.started) * 1000),
        }
