"""Validate same-frame capture-to-display CSV evidence on one monotonic clock."""

import argparse
import csv
import hashlib
import io
import json
import math
from pathlib import Path
import statistics


def check(rows, expected_frames, limit_ms):
    if not rows:
        raise ValueError("empty measurement window")
    issues, latencies, displays = [], [], []
    if len(rows) != expected_frames:
        issues.append("row count differs from expected captured frame count")
    identities = set()
    runs, clocks = set(), set()
    for row in rows:
        identity = row["frame_id"]
        if not identity or identity in identities:
            raise ValueError("empty or duplicate frame_id")
        identities.add(identity)
        runs.add(row["run_id"])
        clocks.add(row["clock_id"])
        if row["status"] != "ok":
            issues.append("incomplete frame: " + identity + ":" + row["status"])
            continue
        if row["display_evidence"] not in ("presentation_feedback", "external_probe"):
            issues.append("frame " + identity + " lacks display-completion evidence")
        values = [int(row[key]) for key in ("capture_ns", "result_ns", "display_ns")]
        if values[0] < 0 or values != sorted(values):
            raise ValueError("relative counters must satisfy 0 <= capture <= result <= display")
        latencies.append((values[2] - values[0]) / 1e6)
        displays.append(values[2])
    if len(runs) != 1 or "" in runs or len(clocks) != 1 or "" in clocks:
        raise ValueError("require one run and one declared monotonic clock domain")
    ordered = sorted(latencies)
    summary = None
    if ordered:
        summary = {"fastest_ms": ordered[0], "mean_ms": statistics.mean(ordered), "max_ms": max(ordered),
                   "p50_ms": ordered[math.ceil(.50 * len(ordered)) - 1],
                   "p95_ms": ordered[math.ceil(.95 * len(ordered)) - 1],
                   "p99_ms": ordered[math.ceil(.99 * len(ordered)) - 1]}
        if max(ordered) >= limit_ms:
            issues.append("at least one complete frame fails strict latency < limit_ms")
    else:
        issues.append("no complete frames")
    span = max(displays) - min(displays) if displays else 0
    return {"status": "passed" if not issues else "failed", "issues": issues,
            "expected_frames": expected_frames, "rows": len(rows), "complete_frames": len(ordered),
            "limit_ms_exclusive": limit_ms, "latency": summary,
            "display_throughput_fps": (len(displays) - 1) * 1e9 / span if span > 0 else None,
            "quantile_method": "nearest rank", "run_id": sorted(runs), "clock_id": sorted(clocks),
            "scope": "validates relative counters; physical display evidence must be supplied separately"}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv", type=Path)
    parser.add_argument("--expected-frames", type=int, required=True)
    parser.add_argument("--limit-ms", type=float, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    if args.expected_frames <= 0 or not math.isfinite(args.limit_ms) or args.limit_ms <= 0:
        parser.error("expected-frames and finite limit-ms must be positive")
    if args.output and args.output.exists():
        parser.error("output already exists")
    try:
        raw = args.csv.read_bytes()
        report = check(list(csv.DictReader(io.StringIO(raw.decode("utf-8-sig")))),
                       args.expected_frames, args.limit_ms)
        report["input_sha256"] = hashlib.sha256(raw).hexdigest()
    except (OSError, ValueError, KeyError, TypeError) as error:
        report = {"status": "failed", "issues": [str(error)]}
    if report.get("latency"):
        report["latency"] = {"fastest_ms": report["latency"]["fastest_ms"]}
    report.pop("quantile_method", None)
    encoded = json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    if args.output:
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(encoded)
    print(encoded, end="")
    return 0 if report["status"] == "passed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
