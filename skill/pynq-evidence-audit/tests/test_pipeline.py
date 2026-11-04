import copy
import csv
import importlib.util
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("check_pipeline", ROOT / "scripts/check_pipeline.py")
pipeline = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pipeline)


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.contract = json.loads((ROOT / "examples/pipeline_contract.json").read_text())
        with (ROOT / "examples/pipeline_results.csv").open() as stream:
            self.rows = list(csv.DictReader(stream))

    def test_complete_frame(self):
        self.assertEqual(pipeline.check(self.contract, self.rows, 2)["status"], "passed")

    def test_missing_branch(self):
        self.assertEqual(pipeline.check(self.contract, self.rows[:-1], 2)["status"], "failed")

    def test_stale_roi(self):
        self.rows[0]["roi_frame_id"] = "old_frame"
        self.assertEqual(pipeline.check(self.contract, self.rows, 2)["status"], "failed")

    def test_changed_models_and_preprocessing(self):
        for field in ("model_sha256", "preprocess_sha256", "output_contract"):
            rows = copy.deepcopy(self.rows)
            rows[0][field] = "wrong"
            self.assertEqual(pipeline.check(self.contract, rows, 2)["status"], "failed")

    def test_mismatched_captured_input(self):
        self.rows[0]["source_sha256"] = "f" * 64
        self.assertEqual(pipeline.check(self.contract, self.rows, 2)["status"], "failed")

    def test_duplicate_result(self):
        self.assertEqual(pipeline.check(self.contract, self.rows + [self.rows[0]], 2)["status"], "failed")

    def test_failed_result(self):
        self.rows[0]["status"] = "error"
        self.assertEqual(pipeline.check(self.contract, self.rows, 2)["status"], "failed")

    def test_missing_frame(self):
        self.assertEqual(pipeline.check(self.contract, self.rows, 3)["status"], "failed")

    def test_invalid_contract(self):
        self.contract["branches"]["region_a"]["model_sha256"] = ""
        with self.assertRaises(ValueError):
            pipeline.check(self.contract, self.rows, 2)


if __name__ == "__main__":
    unittest.main()
