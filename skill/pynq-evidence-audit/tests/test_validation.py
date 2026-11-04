import copy
import csv
import importlib.util
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


def module(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / (name + ".py"))
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


reports = module("check_reports")
latency = module("check_latency")
manifest = module("check_manifest")


class ReportTests(unittest.TestCase):
    def setUp(self):
        self.util = (ROOT / "examples/utilization.rpt").read_text()
        self.time = (ROOT / "examples/timing.rpt").read_text()

    def test_pass_and_fractional_bram(self):
        result = reports.check(self.util, self.time, 80)
        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["resources"]["bram"]["used"], 1.5)

    def test_over_resource_budget(self):
        self.assertEqual(reports.check(self.util, self.time, 1)["status"], "failed")

    def test_hold_and_pulse_violation(self):
        for changed in (self.time.replace("0.05", "-0.05"), self.time.replace("2.0 0 0 10", "-0.1 -0.1 1 10")):
            self.assertEqual(reports.check(self.util, changed, 80)["status"], "failed")

    def test_positive_wns_with_missing_io_constraints(self):
        self.assertEqual(reports.check(self.util, self.time.replace("no_input_delay (0)", "no_input_delay (2)"), 80)["status"], "failed")

    def test_synthesis_not_routed(self):
        self.assertEqual(reports.check(self.util.replace("Routed", "Synthesized"), self.time, 80)["status"], "failed")

    def test_missing_resource_not_zero(self):
        with self.assertRaises(ValueError):
            reports.check(self.util.replace("DSPs", "unrecognized"), self.time, 80)

    def test_missing_coverage_not_pass(self):
        with self.assertRaises(ValueError):
            reports.check(self.util, self.time.replace("checking no_clock", "unknown no_clock"), 80)

    def test_mismatched_device(self):
        self.assertEqual(reports.check(self.util, self.time.replace("7z020", "7z010"), 80)["status"], "failed")

    def test_no_endpoints(self):
        self.assertEqual(reports.check(self.util, self.time.replace("0 100", "0 0"), 80)["status"], "failed")

    def test_clb_resource_aliases(self):
        changed = self.util.replace("Slice LUTs", "CLB LUTs").replace("Slice Registers", "CLB Registers")
        self.assertEqual(reports.check(changed, self.time, 80)["status"], "passed")

    def test_repeated_distribution_row(self):
        repeated = self.util + "\n| Slice Registers | 120 | 0 | 0 | 106400 | 0.11 |\n"
        self.assertEqual(reports.check(repeated, self.time, 80)["status"], "passed")

    def test_conflicting_duplicate_row(self):
        repeated = self.util + "\n| Slice Registers | 121 | 0 | 0 | 106400 | 0.11 |\n"
        with self.assertRaises(ValueError):
            reports.check(repeated, self.time, 80)


class LatencyTests(unittest.TestCase):
    def setUp(self):
        with (ROOT / "examples/frames.csv").open() as stream:
            self.rows = list(csv.DictReader(stream))

    def test_all_frame_latency(self):
        result = latency.check(self.rows, 3, 40)
        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["latency"]["p95_ms"], 30)
        self.assertEqual(result["latency"]["fastest_ms"], 20)

    def test_strict_boundary(self):
        self.assertEqual(latency.check(self.rows, 3, 30)["status"], "failed")

    def test_missing_rows(self):
        self.assertEqual(latency.check(self.rows, 4, 40)["status"], "failed")

    def test_dropped_frame(self):
        self.rows[1]["status"] = "dropped"
        self.assertEqual(latency.check(self.rows, 3, 40)["status"], "failed")

    def test_mixed_clock_and_duplicate(self):
        for key in ("clock_id", "frame_id"):
            rows = copy.deepcopy(self.rows)
            rows[1][key] = "different" if key == "clock_id" else rows[0][key]
            with self.assertRaises(ValueError):
                latency.check(rows, 3, 40)

    def test_submit_is_not_display(self):
        self.rows[1]["display_evidence"] = "submit_only"
        self.assertEqual(latency.check(self.rows, 3, 40)["status"], "failed")

    def test_reversed_counter(self):
        self.rows[0]["result_ns"] = "0"
        with self.assertRaises(ValueError):
            latency.check(self.rows, 3, 40)


class ManifestTests(unittest.TestCase):
    def test_change_missing_extra_and_relocation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            payload = root / "a.txt"
            payload.write_bytes(b"abc")
            data = {"schema": "sha256-inventory-v1", "files": {"a.txt": {"bytes": 3, "sha256": manifest.digest(payload)}}}
            self.assertEqual(manifest.verify(root, data, True)["status"], "passed")
            payload.write_bytes(b"abd")
            self.assertEqual(manifest.verify(root, data)["status"], "failed")
            payload.unlink()
            self.assertEqual(manifest.verify(root, data)["status"], "failed")
            payload.write_bytes(b"abc")
            (root / "extra").write_bytes(b"x")
            self.assertEqual(manifest.verify(root, data, True)["status"], "failed")

    def test_path_traversal(self):
        with tempfile.TemporaryDirectory() as directory:
            for name in ("../outside", "C:/outside", "/outside", "a\\b"):
                data = {"schema": "sha256-inventory-v1", "files": {name: {"bytes": 0, "sha256": "0" * 64}}}
                with self.assertRaises(ValueError):
                    manifest.verify(Path(directory).resolve(), data)

    def test_empty_manifest(self):
        with self.assertRaises(ValueError):
            manifest.verify(ROOT, {"schema": "sha256-inventory-v1", "files": {}})


if __name__ == "__main__":
    unittest.main()
