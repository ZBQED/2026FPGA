"""Map a ZYNQ sign recognizer Top-1 class to staff-screen text."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from protocol_runtime import SIGN_CATALOG_PATH, load_json, valid_confidence


class SignIntentMapper:
    def __init__(self, catalog_path: Path = SIGN_CATALOG_PATH) -> None:
        self.catalog = load_json(catalog_path)
        self.by_source_order = {
            item["source_order"]: item for item in self.catalog["intents"]
        }

    def map_top1(
        self, source_intent_order: int, confidence: float, sequence: int = 0
    ) -> dict[str, Any]:
        if source_intent_order not in self.by_source_order:
            raise ValueError(f"Unknown source intent order: {source_intent_order}")
        if not valid_confidence(confidence):
            raise ValueError("confidence must be between 0 and 1")
        intent = self.by_source_order[source_intent_order]
        return {
            "message_type": "SIGN_RESULT",
            "catalog_version": self.catalog["catalog_version"],
            "source": "ZYNQ_SIGN_RECOGNIZER",
            "sequence": sequence,
            "source_intent_order": intent["source_order"],
            "confidence": float(confidence),
            "gesture_expression": intent["gesture_expression"],
            "display_text": intent["output_text"],
        }




