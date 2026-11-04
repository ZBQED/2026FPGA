import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import numpy as np

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


def module(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / (name + ".py"))
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


audit = module("collect_evidence")
arrays = module("compare_arrays")


class AuditTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.bit = self.root / "design.bit"
        self.hwh = self.root / "design.hwh"
        self.bit.write_bytes(b"test-only-placeholder-bitstream")
        self.hwh.write_text('<EDKSYSTEM VIVADOVERSION="test"><SYSTEMINFO DEVICE="test"/>'
                            '<MODULE MODTYPE="axi_dma" VLNV="xilinx.com:ip:axi_dma:7.1"/>'
                            '</EDKSYSTEM>', encoding="utf-8")

    def tearDown(self):
        self.temp.cleanup()

    def args(self, *extra):
        return audit.parse_args(["--bit", str(self.bit), "--hwh", str(self.hwh), "--samples", "0", *extra])

    def test_metadata_and_expected_hash(self):
        result = audit.collect(self.args("--expected-bit-sha256", audit.sha256_file(self.bit),
                                         "--require-ip", "axi_dma"))
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["hwh_metadata"]["module_nodes"], 1)
        self.assertTrue(result["input_files"]["bit"]["hash_matches"])
        self.assertIsNone(result["pl_utilization"]["lut"])

    def test_wrong_hash_does_not_pass(self):
        result = audit.collect(self.args("--expected-bit-sha256", "0" * 64))
        self.assertEqual(result["status"], "issues_found")

    def test_missing_ip_does_not_pass(self):
        result = audit.collect(self.args("--require-ip", "nonexistent_ip"))
        self.assertEqual(result["required_ip_check"]["missing"], ["nonexistent_ip"])
        self.assertEqual(result["status"], "issues_found")

    def test_missing_file_is_reported(self):
        self.bit.unlink()
        self.assertEqual(audit.collect(self.args())["status"], "issues_found")

    def test_corrupt_xml_is_reported(self):
        self.hwh.write_text("<broken>", encoding="utf-8")
        self.assertEqual(audit.collect(self.args())["status"], "issues_found")

    def test_loaded_state_mismatch(self):
        state = self.root / "state.json"
        state.write_text(json.dumps({"bitfile_name": str(self.root / "other.bit")}), encoding="utf-8")
        result = audit.collect(self.args("--state", str(state)))
        self.assertFalse(result["loaded_state"]["recorded_path_matches"])
        self.assertEqual(result["status"], "issues_found")

    def test_existing_output_not_overwritten(self):
        target = self.root / "existing.json"
        target.write_text("preserve", encoding="utf-8")
        completed = subprocess.run([sys.executable, str(SCRIPTS / "collect_evidence.py"),
                                    "--bit", str(self.bit), "--samples", "0", "--output", str(target)],
                                   capture_output=True, text=True)
        self.assertEqual(completed.returncode, 2)
        self.assertEqual(target.read_text(), "preserve")

    def test_cpu_core_conventions(self):
        before = {"monotonic": 10, "system": {"total_ticks": 1000, "idle_ticks": 400},
                  "process": {"pid": 42, "start_ticks": 7, "cpu_ticks": 100}}
        after = {"monotonic": 11, "system": {"total_ticks": 1200, "idle_ticks": 500},
                 "process": {"pid": 42, "start_ticks": 7, "cpu_ticks": 200}}
        result = audit.interval_metrics(before, after, 100, 2)
        self.assertEqual(result["system_cpu_percent"], 50)
        self.assertEqual(result["process_cpu_percent_one_core"], 100)
        self.assertEqual(result["process_cpu_percent_machine"], 50)

    def test_pid_reuse_rejected(self):
        before = {"monotonic": 10, "system": {"total_ticks": 100, "idle_ticks": 20},
                  "process": {"pid": 42, "start_ticks": 7, "cpu_ticks": 100}}
        after = {"monotonic": 11, "system": {"total_ticks": 300, "idle_ticks": 120},
                 "process": {"pid": 42, "start_ticks": 8, "cpu_ticks": 10}}
        with self.assertRaises(ValueError):
            audit.interval_metrics(before, after, 100, 2)

    def test_process_stat_parsing_with_spaces(self):
        directory = self.root / "42"
        directory.mkdir()
        fields = ["0"] * 22
        fields[0], fields[11], fields[12], fields[19] = "S", "100", "5", "99"
        (directory / "stat").write_text("42 (app ) with spaces) " + " ".join(fields))
        (directory / "status").write_text("VmRSS:\t10 kB\nThreads:\t2\n")
        result = audit.read_process(42, self.root)
        self.assertEqual(result["cpu_ticks"], 105)
        self.assertEqual(result["start_ticks"], 99)
        self.assertEqual(result["VmRSS_bytes"], 10240)


class ArrayTests(unittest.TestCase):
    def test_within_tolerance(self):
        result = arrays.compare(np.array([1., 2.]), np.array([1.000001, 2.]), 1e-5, 0)
        self.assertEqual(result["status"], "passed")

    def test_mismatch(self):
        result = arrays.compare(np.array([1., 2.]), np.array([1., 3.]), 0, 0)
        self.assertEqual(result["mismatch_count"], 1)

    def test_shapes_not_broadcast(self):
        result = arrays.compare(np.ones((2, 1)), np.ones((2,)), 0, 0)
        self.assertEqual(result["reason"], "shape_mismatch")

    def test_nonfinite_rejected(self):
        result = arrays.compare(np.array([np.nan]), np.array([np.nan]), 0, 0)
        self.assertEqual(result["reason"], "nonfinite_input")

    def test_empty_arrays_rejected(self):
        result = arrays.compare(np.array([]), np.array([]), 0, 0)
        self.assertEqual(result["status"], "failed")

    def test_large_exact_integers_not_rounded_to_equal(self):
        result = arrays.compare(np.array([2**63], dtype=np.uint64),
                                np.array([2**63 + 1], dtype=np.uint64), 0, 0)
        self.assertEqual(result["mismatch_count"], 1)
        self.assertEqual(result["max_abs_error"], "1")

    def test_large_integer_mixed_float_is_not_equal(self):
        result = arrays.compare(np.array([2**53 + 1], dtype=np.int64),
                                np.array([float(2**53)]), 0, 0)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["max_abs_error"], "1")
        self.assertEqual(result["first_mismatch_index"], [0])

    def test_large_float_mixed_integer_is_not_equal(self):
        result = arrays.compare(np.array([float(2**53)]),
                                np.array([2**53 + 1], dtype=np.int64), 0, 0)
        self.assertEqual(result["mismatch_count"], 1)

    def test_mixed_equal_values(self):
        result = arrays.compare(np.array([-2, 0, 4], dtype=np.int64),
                                np.array([-2., 0., 4.]), 0, 0)
        self.assertEqual(result["status"], "passed")

    def test_mixed_absolute_boundary(self):
        reference, actual = np.array([2**53 + 1], dtype=np.int64), np.array([float(2**53)])
        self.assertEqual(arrays.compare(reference, actual, 1, 0)["status"], "passed")
        self.assertEqual(arrays.compare(reference, actual, 0.5, 0)["status"], "failed")

    def test_mixed_relative_tolerance_uses_reference(self):
        reference, actual = np.array([4], dtype=np.int32), np.array([5.])
        self.assertEqual(arrays.compare(reference, actual, 0, 0.25)["status"], "passed")
        self.assertEqual(arrays.compare(reference, actual, 0, 0.125)["status"], "failed")

    def test_unsigned_maximum_mixed_float(self):
        result = arrays.compare(np.array([2**64 - 1], dtype=np.uint64),
                                np.array([float(2**64)]), 0, 0)
        self.assertEqual(result["mismatch_count"], 1)
        self.assertEqual(result["max_abs_error"], "1")

    def test_mixed_scalar_fraction(self):
        result = arrays.compare(np.array(1, dtype=np.int32), np.array(1.5), 0, 0)
        self.assertEqual(result["max_abs_error"], "0.5")
        self.assertEqual(result["first_mismatch_index"], [])

    def test_npz_key_required(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "array.npz"
            np.savez(path, feature=np.array([1, 2]))
            with self.assertRaises(ValueError):
                arrays.load_array(path)
            self.assertTrue(np.array_equal(arrays.load_array(path, "feature"), [1, 2]))

    def test_cli_tolerances_and_exit(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            np.save(root / "reference.npy", np.array([1.]))
            np.save(root / "actual.npy", np.array([2.]))
            command = [sys.executable, str(SCRIPTS / "compare_arrays.py"), str(root / "reference.npy"),
                       str(root / "actual.npy"), "--atol", "0", "--rtol", "0"]
            completed = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(completed.returncode, 2)
            self.assertEqual(json.loads(completed.stdout)["status"], "failed")


if __name__ == "__main__":
    unittest.main()
