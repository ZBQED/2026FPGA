"""Install a manifest-verified release; rollback only this invocation's directory."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

NAME = "pynq-evidence-audit"


def verify_bundle(bundle):
    manifest = json.loads((bundle / "files_sha256.json").read_text(encoding="utf-8"))
    if manifest.get("schema") != "sha256-inventory-v1" or not manifest.get("files"):
        raise ValueError("invalid release manifest")
    expected = set(manifest["files"])
    actual = {p.relative_to(bundle).as_posix() for p in bundle.rglob("*") if p.is_file()}
    if actual != expected | {"files_sha256.json"}:
        raise ValueError("release contains missing or unexpected files")
    for name, record in manifest["files"].items():
        path = bundle / name
        if not path.resolve().is_relative_to(bundle.resolve()) or path.is_symlink():
            raise ValueError("invalid release path")
        if path.stat().st_size != record["bytes"] or hashlib.sha256(path.read_bytes()).hexdigest() != record["sha256"]:
            raise ValueError("release file changed: " + name)


def main(argv=None, bundle=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, default=Path.cwd())
    parser.add_argument("--skills-dir", type=Path, help="skill parent directory for another compatible client")
    args = parser.parse_args(argv)
    if sys.version_info < (3, 9):
        parser.error("Python 3.9 or newer is required")
    if bundle is None:
        parser.error("use the release's skill/install.py entry point")
    bundle = Path(bundle).resolve()
    destination = ((args.skills_dir or args.project / ".agents" / "skills") / NAME).resolve()
    created_destination = False
    try:
        verify_bundle(bundle)
        if destination.exists():
            raise ValueError("destination exists; choose another project or skill directory")
        if destination.is_relative_to(bundle / NAME):
            raise ValueError("destination cannot be inside source skill")
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.mkdir()  # Atomic ownership claim; never take over an existing directory.
        created_destination = True
        shutil.copytree(bundle / NAME, destination, dirs_exist_ok=True)
        # Keep the venv at its final path; relocation can break installed entry points.
        with tempfile.TemporaryDirectory(prefix="pynq_install_", dir=destination.parent) as temporary:
            env = {**os.environ, "TEMP": temporary, "TMP": temporary, "TMPDIR": temporary,
                   "PYTHONDONTWRITEBYTECODE": "1", "PYTHONIOENCODING": "utf-8"}
            python = destination / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
            subprocess.run([sys.executable, "-B", "-m", "venv", str(destination / ".venv")], env=env, check=True)
            probe = subprocess.run([str(python), "-B", "-c", "import numpy"], env=env, capture_output=True)
            if probe.returncode:
                subprocess.run([str(python), "-B", "-m", "pip", "install", "--no-compile", "--no-cache-dir",
                                "--disable-pip-version-check", "--only-binary=:all:", "-r", str(destination / "requirements.txt")], env=env, check=True)
            subprocess.run([str(python), "-B", str(destination / "scripts/run.py"), "test"], env=env, check=True)
            environment = json.loads(subprocess.check_output([str(python), "-B", "-c",
                "import json,sys,numpy; print(json.dumps({'python':sys.version.split()[0],'numpy':numpy.__version__}))"], env=env, text=True))
        receipt = {"status": "installed", "skill": NAME, "python": str(python),
                   "source_manifest_sha256": hashlib.sha256((bundle / "files_sha256.json").read_bytes()).hexdigest(),
                   "self_test": "passed", "environment": environment}
        (destination / "installation.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"status": "installed", "skill_path": str(destination), "self_test": "passed"}))
        return 0
    except (OSError, ValueError, subprocess.SubprocessError, KeyboardInterrupt) as error:
        cleanup = "not_created"
        if created_destination:
            try:
                if destination.is_symlink() or destination.resolve() != destination:
                    raise OSError("destination identity changed; automatic rollback skipped")
                shutil.rmtree(destination)  # Only the absolute directory claimed by this attempt.
                cleanup = "removed_this_attempt"
            except OSError as cleanup_error:
                cleanup = "failed: " + str(cleanup_error)
        print(json.dumps({"status": "failed", "reason": str(error) or "interrupted",
                          "destination": str(destination), "rollback": cleanup}))
        return 130 if isinstance(error, KeyboardInterrupt) else 2
