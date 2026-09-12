import json
import sys
import tempfile
import types
import unittest
from pathlib import Path


APP_DIR = Path(__file__).resolve().parents[1] / "app"
sys.path.insert(0, str(APP_DIR))

from narration_eta import MIN_BUCKET_SAMPLES, estimate_remaining_seconds, write_progress

sys.modules.setdefault("fitz", types.ModuleType("fitz"))
import server


class BucketEtaTests(unittest.TestCase):
    def test_waits_for_enough_buckets_to_calibrate(self):
        observations = [(i, 2.0 + i * 0.5) for i in range(MIN_BUCKET_SAMPLES - 1)]
        self.assertIsNone(estimate_remaining_seconds(observations, [30, 31]))

    def test_forecasts_increasing_bucket_cost(self):
        observations = [(i, 2.0 + i * 0.5) for i in range(1, 21)]
        remaining = list(range(21, 26))
        expected = sum(2.0 + i * 0.5 for i in remaining)
        self.assertAlmostEqual(
            estimate_remaining_seconds(observations, remaining), expected
        )

    def test_constant_bucket_lengths_use_mean_duration(self):
        observations = [(100, float(i)) for i in range(1, 21)]
        self.assertAlmostEqual(
            estimate_remaining_seconds(observations, [100, 100]), 21.0
        )

    def test_progress_sidecar_is_valid_json(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "progress.json"
            self.assertTrue(write_progress(path, {"eta_sec": 12.3}))
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["eta_sec"], 12.3)


class ServerProgressTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.job_dir = Path(self.temp.name)
        (self.job_dir / "segments").mkdir()
        (self.job_dir / "plan_total.txt").write_text("100", encoding="utf-8")
        self.state = {
            "engine": "batched",
            "num_workers": 1,
            "narrate_started_at": 1.0,
            "narrate_baseline_done": 0,
        }

    def tearDown(self):
        self.temp.cleanup()

    def test_batched_worker_eta_replaces_chunk_average(self):
        (self.job_dir / "narration_progress.json").write_text(
            json.dumps({"eta_sec": 456.7}), encoding="utf-8"
        )
        with unittest.mock.patch("server.time.time", return_value=101.0):
            progress = server._narration_progress(self.job_dir, self.state)
        self.assertEqual(progress["eta_sec"], 456.7)

    def test_missing_batched_worker_eta_does_not_invent_chunk_rate(self):
        with unittest.mock.patch("server.time.time", return_value=101.0):
            progress = server._narration_progress(self.job_dir, self.state)
        self.assertIsNone(progress["eta_sec"])

    def test_generation_eta_is_hidden_during_assembly(self):
        (self.job_dir / "plan_total.txt").write_text("1", encoding="utf-8")
        (self.job_dir / "segments" / "seg_000000.wav").write_bytes(b"")
        (self.job_dir / "narration_progress.json").write_text(
            json.dumps({"eta_sec": 0.0}), encoding="utf-8"
        )
        progress = server._narration_progress(self.job_dir, self.state)
        self.assertIsNone(progress["eta_sec"])
        self.assertEqual(progress["message"], "assembling")


class PackagingTests(unittest.TestCase):
    def test_patch_installer_includes_eta_helper(self):
        installer = APP_DIR.parent / "install" / "AudiobookStudio_Patch.iss"
        self.assertIn(
            'Source: "..\\app\\narration_eta.py"',
            installer.read_text(encoding="utf-8"),
        )


if __name__ == "__main__":
    unittest.main()
