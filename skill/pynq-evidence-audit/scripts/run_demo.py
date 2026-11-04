"""Run an offline synthetic example, including deliberately failing validations."""

import argparse
import csv
import json
import os
from pathlib import Path
import subprocess
import sys
import numpy as np


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True, help="new directory on a data drive")
    args = parser.parse_args()
    root = args.output_dir.resolve()
    if root.exists():
        parser.error("choose a new output directory")
    root.mkdir(parents=True)
    package = Path(__file__).resolve().parents[1]
    (root / "fixture.bit").write_bytes(b"SYNTHETIC-NOT-A-LOADABLE-BITSTREAM")
    (root / "fixture.hwh").write_text('<EDKSYSTEM><MODULE MODTYPE="axi_dma"/></EDKSYSTEM>', encoding="utf-8")
    np.save(root / "reference.npy", np.array([0, 1, 255], dtype=np.uint32))
    np.save(root / "actual.npy", np.array([0, 1, 255], dtype=np.uint32))
    np.save(root / "bad.npy", np.array([0, 2, 255], dtype=np.uint32))
    results = []

    def run(script, arguments, expected):
        command = [sys.executable, "-B", str(package / "scripts" / (script + ".py")), *map(str, arguments)]
        completed = subprocess.run(command, capture_output=True, text=True, encoding="utf-8",
                                   env={**os.environ, "PYTHONIOENCODING": "utf-8"})
        results.append({"script": script, "expected_exit": expected, "actual_exit": completed.returncode,
                        "report": json.loads(completed.stdout) if completed.stdout.strip() else completed.stderr})
        if completed.returncode != expected:
            raise RuntimeError(script + ": " + completed.stdout + completed.stderr)

    run("collect_evidence", ["--bit", root / "fixture.bit", "--hwh", root / "fixture.hwh",
                              "--require-ip", "axi_dma", "--samples", "0"], 0)
    for actual, expected in (("actual.npy", 0), ("bad.npy", 2)):
        run("compare_arrays", [root / "reference.npy", root / actual, "--atol", "0", "--rtol", "0"], expected)
    run("check_reports", ["--utilization", package / "examples/utilization.rpt", "--timing",
                          package / "examples/timing.rpt", "--max-percent", "80"], 0)
    run("check_latency", [package / "examples/frames.csv", "--expected-frames", "3", "--limit-ms", "40"], 0)
    run("check_latency", [package / "examples/frames.csv", "--expected-frames", "3", "--limit-ms", "30"], 2)
    run("check_pipeline", ["--contract", package / "examples/pipeline_contract.json", "--results",
                           package / "examples/pipeline_results.csv", "--expected-frames", "2"], 0)
    with (package / "examples/pipeline_results.csv").open() as stream:
        rows = list(csv.DictReader(stream))
    rows[0]["roi_frame_id"] = "stale"
    stale = root / "stale_pipeline.csv"
    with stale.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    run("check_pipeline", ["--contract", package / "examples/pipeline_contract.json", "--results", stale,
                           "--expected-frames", "2"], 2)
    manifest_root = root / "handoff"
    manifest_root.mkdir()
    payload = manifest_root / "input.txt"
    payload.write_text("fixture", encoding="utf-8")
    run("check_manifest", ["create", manifest_root, root / "manifest.json"], 0)
    run("check_manifest", ["verify", manifest_root, root / "manifest.json", "--strict"], 0)
    payload.write_text("changed", encoding="utf-8")
    run("check_manifest", ["verify", manifest_root, root / "manifest.json", "--strict"], 2)
    summary = {"status": "passed", "evidence_kind": "synthetic_offline_only", "checks": results}
    (root / "demo_result.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "passed", "checks": len(results), "output_dir": str(root)}))


if __name__ == "__main__":
    main()
