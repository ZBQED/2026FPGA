import contextlib
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[1] / "scripts/install_skill.py"
spec = importlib.util.spec_from_file_location("installer_under_test", SOURCE)
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


class InstallationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.bundle = self.root / "bundle"
        self.source = self.bundle / installer.NAME
        (self.source / "scripts").mkdir(parents=True)
        (self.source / "requirements.txt").write_text("numpy>=1.21\n", encoding="utf-8")
        (self.source / "scripts/run.py").write_text("# fixture, never executed\n", encoding="utf-8")
        entries = {p.relative_to(self.bundle).as_posix(): {
            "bytes": p.stat().st_size, "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
            for p in self.bundle.rglob("*") if p.is_file()}
        (self.bundle / "files_sha256.json").write_text(json.dumps({"schema": "sha256-inventory-v1", "files": entries}))
        self.project = self.root / "project"
        self.destination = self.project / ".agents/skills" / installer.NAME

    def tearDown(self):
        self.temporary.cleanup()

    def run_installer(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = installer.main(["--project", str(self.project)], bundle=self.bundle)
        return code, json.loads(output.getvalue())

    def test_venv_failure_removes_partial_install(self):
        with patch.object(installer.subprocess, "run", side_effect=subprocess.CalledProcessError(1, "venv")):
            code, report = self.run_installer()
        self.assertEqual(code, 2)
        self.assertEqual(report["rollback"], "removed_this_attempt")
        self.assertFalse(self.destination.exists())

    def test_dependency_failure_removes_partial_install(self):
        def subprocess_result(command, **kwargs):
            if "pip" in command:
                raise subprocess.CalledProcessError(1, command)
            return subprocess.CompletedProcess(command, 1 if "import numpy" in command else 0)
        with patch.object(installer.subprocess, "run", side_effect=subprocess_result):
            code, _ = self.run_installer()
        self.assertEqual(code, 2)
        self.assertFalse(self.destination.exists())

    def test_self_test_failure_removes_partial_install(self):
        def subprocess_result(command, **kwargs):
            if command[-1] == "test":
                raise subprocess.CalledProcessError(1, command)
            return subprocess.CompletedProcess(command, 0)
        with patch.object(installer.subprocess, "run", side_effect=subprocess_result):
            code, _ = self.run_installer()
        self.assertEqual(code, 2)
        self.assertFalse(self.destination.exists())

    def test_failed_install_can_retry_to_success(self):
        with patch.object(installer.subprocess, "run", side_effect=subprocess.CalledProcessError(1, "venv")):
            self.run_installer()
        with patch.object(installer.subprocess, "run", return_value=subprocess.CompletedProcess([], 0)), \
             patch.object(installer.subprocess, "check_output", return_value='{"python":"test","numpy":"test"}'):
            code, report = self.run_installer()
        self.assertEqual(code, 0)
        self.assertEqual(report["status"], "installed")
        self.assertTrue((self.destination / "installation.json").exists())

    def test_existing_install_preserved(self):
        self.destination.mkdir(parents=True)
        marker = self.destination / "keep.txt"
        marker.write_text("existing user content")
        with patch.object(installer.subprocess, "run") as runner:
            code, report = self.run_installer()
        self.assertEqual(code, 2)
        self.assertEqual(report["rollback"], "not_created")
        self.assertEqual(marker.read_text(), "existing user content")
        runner.assert_not_called()

    def test_corrupt_bundle_rejected_before_copy(self):
        (self.source / "requirements.txt").write_text("changed")
        code, _ = self.run_installer()
        self.assertEqual(code, 2)
        self.assertFalse(self.destination.exists())

    def test_keyboard_interrupt_rolls_back(self):
        with patch.object(installer.subprocess, "run", side_effect=KeyboardInterrupt):
            code, report = self.run_installer()
        self.assertEqual(code, 130)
        self.assertEqual(report["rollback"], "removed_this_attempt")
        self.assertFalse(self.destination.exists())


if __name__ == "__main__":
    unittest.main()
