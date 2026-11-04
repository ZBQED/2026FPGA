"""Check frame, branch, model and preprocessing identity before multi-branch fusion."""

import argparse
import csv
import hashlib
import io
import json
from pathlib import Path
import re


def check(contract, rows, expected_frames):
    branches = contract.get("branches")
    if contract.get("schema") != "pipeline-contract-v1" or not isinstance(branches, dict) or not branches:
        raise ValueError("nonempty pipeline-contract-v1 branches required")
    for name, branch in branches.items():
        if not name or not isinstance(branch, dict):
            raise ValueError("invalid branch")
        for key in ("model_sha256", "preprocess_sha256"):
            if not re.fullmatch(r"[0-9a-f]{64}", branch.get(key, "")):
                raise ValueError("each branch requires a model and preprocessing SHA-256")
        if not branch.get("output_contract"):
            raise ValueError("each branch requires an output contract identifier")
    if expected_frames <= 0 or not rows:
        raise ValueError("nonempty input and positive expected frame count required")
    issues, frames, sources = [], {}, {}
    for row in rows:
        frame, branch = row["frame_id"], row["branch"]
        if not frame or branch not in branches:
            raise ValueError("empty frame or unknown branch")
        seen = frames.setdefault(frame, set())
        if branch in seen:
            issues.append("duplicate branch result: " + frame + "/" + branch)
        seen.add(branch)
        if row["source_frame_id"] != frame or row["roi_frame_id"] != frame:
            issues.append("stale source/ROI result: " + frame + "/" + branch)
        source = row["source_sha256"]
        if not re.fullmatch(r"[0-9a-f]{64}", source):
            raise ValueError("invalid source SHA-256")
        if frame in sources and sources[frame] != source:
            issues.append("different captured inputs merged: " + frame)
        sources[frame] = source
        for key in ("model_sha256", "preprocess_sha256", "output_contract"):
            if row[key] != branches[branch][key]:
                issues.append(key + " differs: " + frame + "/" + branch)
        if row["status"] != "ok":
            issues.append("failed branch: " + frame + "/" + branch)
    if len(frames) != expected_frames:
        issues.append("frame count differs from capture count")
    for frame, seen in frames.items():
        missing = sorted(set(branches) - seen)
        if missing:
            issues.append("missing branches: " + frame + ":" + ",".join(missing))
    return {"status": "passed" if not issues else "failed", "issues": issues,
            "frames": len(frames), "expected_frames": expected_frames, "rows": len(rows),
            "branches": sorted(branches),
            "evidence_kind": "synthetic" if contract.get("example_only") else "supplied_records",
            "scope": "identity and completeness only; numerical accuracy and physical execution are separate"}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--results", type=Path, required=True)
    parser.add_argument("--expected-frames", type=int, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    if args.output and args.output.exists():
        parser.error("output already exists")
    try:
        config, raw = args.contract.read_bytes(), args.results.read_bytes()
        report = check(json.loads(config.decode("utf-8-sig")),
                       list(csv.DictReader(io.StringIO(raw.decode("utf-8-sig")))), args.expected_frames)
        report["input_sha256"] = {"contract": hashlib.sha256(config).hexdigest(),
                                  "results": hashlib.sha256(raw).hexdigest()}
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as error:
        report = {"status": "failed", "issues": [str(error)]}
    encoded = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(encoded)
    print(encoded, end="")
    return 0 if report["status"] == "passed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
