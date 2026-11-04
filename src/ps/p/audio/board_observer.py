"""Read-only live status in /run (RAM); never records or sends network messages."""
import json
import os
from pathlib import Path
import time
import uuid

ROOT = Path("/run/b-speech-ui")
STATE = {"session_id": str(uuid.uuid4()), "started_at": time.time(),
         "phase": "starting", "event_count": 0, "events": [], "last_result": None}
LAST_WRITE = 0.
TRANSPORT = None


def publish(phase=None, force=True, **fields):
    global LAST_WRITE
    try:
        STATE.update(fields)
        if phase is not None:
            STATE["phase"] = phase
            STATE["phase_since_monotonic"] = time.monotonic()
        now = time.monotonic()
        if not force and now - LAST_WRITE < .5:
            return
        STATE.update(updated_at=time.time(), updated_monotonic=now)
        ROOT.mkdir(parents=True, exist_ok=True)
        tmp = ROOT / "state.tmp"
        tmp.write_text(json.dumps(STATE, ensure_ascii=False, allow_nan=False), encoding="utf-8")
        os.chmod(str(tmp), 0o644)
        tmp.replace(ROOT / "state.json")
        LAST_WRITE = now
    except Exception as exc:
        # A dashboard failure must not stop capture, inference or delivery.
        if STATE.get("observer_error") != str(exc):
            print("OBSERVER_WARNING " + str(exc), flush=True)
            STATE["observer_error"] = str(exc)


def level(dbfs, peak):
    fields = dict(level_dbfs=float(dbfs), peak=float(peak))
    if TRANSPORT is not None:
        fields.update(communication_stats=TRANSPORT.snapshot(),
                      remote_context_available=TRANSPORT.get_capture_context_snapshot()[0] is not None)
    publish(force=False, **fields)


def record_result(result):
    STATE["event_count"] += 1
    event = dict(result)
    event["observer_sequence"] = STATE["event_count"]
    event["observed_at"] = time.time()
    STATE["events"].append(event)
    STATE["events"] = STATE["events"][-50:]
    publish("result", last_result=event)


class LocalOnlySender:
    """Explicitly never sends a result recorded without a valid remote turn."""
    host = None

    def send_result(self, result, **kwargs):
        return False

    def close(self):
        pass
