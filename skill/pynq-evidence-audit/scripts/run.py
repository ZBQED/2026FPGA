"""Run a packaged tool using the installed isolated Python when available."""

import os
from pathlib import Path
import subprocess
import sys

TOOLS = {"collect": "collect_evidence", "compare": "compare_arrays", "reports": "check_reports",
         "latency": "check_latency", "manifest": "check_manifest", "pipeline": "check_pipeline",
         "demo": "run_demo"}


def main():
    root = Path(__file__).resolve().parents[1]
    if len(sys.argv) < 2 or sys.argv[1] not in (*TOOLS, "test"):
        print("Usage: python scripts/run.py {" + ",".join((*TOOLS, "test")) + "} [arguments]")
        return 2
    python = root / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    executable = str(python) if python.exists() else sys.executable
    action = sys.argv[1]
    arguments = (["-m", "unittest", "discover", "-s", str(root / "tests"), "-v"] if action == "test"
                 else [str(root / "scripts" / (TOOLS[action] + ".py")), *sys.argv[2:]])
    return subprocess.call([executable, "-B", *arguments], env={**os.environ,
                            "PYTHONDONTWRITEBYTECODE": "1", "PYTHONIOENCODING": "utf-8"})


if __name__ == "__main__":
    raise SystemExit(main())
