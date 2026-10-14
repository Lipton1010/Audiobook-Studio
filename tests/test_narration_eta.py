import json
import os
import sys
import tempfile
import types
import unittest
from unittest import mock
from pathlib import Path


APP_DIR = Path(__file__).resolve().parents[1] / "app"
sys.path.insert(0, str(APP_DIR))

from narration_eta import MIN_BUCKET_SAMPLES, estimate_remaining_seconds, estimate_word_remaining_seconds, write_progress

sys.modules.setdefault("fitz", types.ModuleType("fitz"))
import server


class WordEtaTests(unittest.TestCase):
    def test_waits_for_representative_prose_not_opening_headings(self):
        self.assertIsNone(estimate_word_remaining_seconds(100, 50, 10000, 20))
        self.assertIsNone(estimate_word_remaining_seconds(100, 800, 10000, 2))

    def test_uses_only_this_runs_verified_work_and_remaining_word_weight(self):
        self.assertEqual(estimate_word_remaining_seconds(160, 600, 1800, 3), 480)
        self.assertEqual(estimate_word_remaining_seconds(320, 600, 1800, 3), 960)
        self.assertEqual(estimate_word_remaining_seconds(160, 600, 0, 3), 0)


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

    def test_tiny_headings_do_not_predict_cost_of_long_prose(self):
        observations = [(6 + i % 8, 2.0 + i * 0.03) for i in range(28)]
        self.assertIsNone(estimate_remaining_seconds(observations, [100, 120, 180]))

    def test_progress_sidecar_is_valid_json(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "progress.json"
            self.assertTrue(write_progress(path, {"eta_sec": 12.3}))
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["eta_sec"], 12.3)

    def test_locked_progress_file_preserves_last_update_and_recovers(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'progress.json'
            path.write_text('{"done": 1}')
            with mock.patch('narration_eta.os.replace', side_effect=PermissionError('Windows sharing violation')), \
                 mock.patch('narration_eta.time.sleep'):
                self.assertFalse(write_progress(path, {'done': 2}))
            self.assertEqual(json.loads(path.read_text()), {'done': 1})
            self.assertTrue(write_progress(path, {'done': 2}))

    def test_vibevoice_progress_lock_does_not_abort_narration(self):
        try:
            import vibevoice_worker as worker
        except ModuleNotFoundError:
            self.skipTest('requires isolated narration runtime')
        with tempfile.TemporaryDirectory() as temp, \
             mock.patch('narration_eta.os.replace', side_effect=PermissionError('Windows sharing violation')), \
             mock.patch('narration_eta.time.sleep'):
            worker._progress(Path(temp), 2, 4, 0, 'generating')


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
        with mock.patch("server.time.time", return_value=101.0):
            progress = server._narration_progress(self.job_dir, self.state)
        self.assertEqual(progress["eta_sec"], 456.7)

    def test_vibevoice_word_progress_and_eta_include_cpu_phase(self):
        self.state["backend"] = "vibevoice"
        path = self.job_dir / "vibevoice_progress.json"
        path.write_text(json.dumps({"done": 8, "total": 113, "status": "quality_check",
                                    "passage_index": 8, "verified_words": 600,
                                    "total_words": 6000, "eta_sec": 900}), encoding="utf-8")
        os.utime(path, (100, 100))
        with mock.patch("server.time.time", return_value=101):
            progress = server._narration_progress(self.job_dir, self.state)
        self.assertEqual(progress["progress_fraction"], 0.1)
        self.assertEqual(progress["eta_sec"], 900)
        self.assertTrue(progress["eta_rough"])
        self.assertIn("CPU", progress["message"])
        self.assertIn("passage 9 of 113", progress["message"])
        with mock.patch("server.time.time", return_value=221):
            stale = server._narration_progress(self.job_dir, self.state)
        self.assertIsNone(stale["eta_sec"])
        self.assertIn("CPU", stale["message"])

    def test_vibevoice_cache_loading_has_no_invented_eta(self):
        self.state["backend"] = "vibevoice"
        (self.job_dir / "vibevoice_progress.json").write_text(
            json.dumps({"done": 8, "total": 113, "status": "checking_cache"}), encoding="utf-8")
        progress = server._narration_progress(self.job_dir, self.state)
        self.assertIsNone(progress["eta_sec"])
        self.assertAlmostEqual(progress["progress_fraction"], 8 / 113)

    def test_generated_progress_includes_review_without_claiming_verification(self):
        self.state["backend"] = "vibevoice"
        (self.job_dir / "vibevoice_progress.json").write_text(json.dumps({
            "done": 5, "total": 10, "status": "quality_check", "review_passages": 2,
            "verified_words": 500, "generated_words": 700, "total_words": 1000,
        }), encoding="utf-8")
        progress = server._narration_progress(self.job_dir, self.state)
        self.assertEqual(progress["progress_fraction"], .7)
        self.assertEqual(progress["verified_fraction"], .5)
        self.assertEqual(progress["done"], 5)
        self.assertTrue(progress["generated_progress"])

    def test_missing_batched_worker_eta_does_not_invent_chunk_rate(self):
        with mock.patch("server.time.time", return_value=101.0):
            progress = server._narration_progress(self.job_dir, self.state)
        self.assertIsNone(progress["eta_sec"])

    def test_stalled_batch_hides_stale_eta_and_explains_delay(self):
        progress_file = self.job_dir / "narration_progress.json"
        progress_file.write_text(json.dumps({"eta_sec": 7530}), encoding="utf-8")
        os.utime(progress_file, (100, 100))
        with mock.patch("server.time.time", return_value=221):
            progress = server._narration_progress(self.job_dir, self.state)
        self.assertIsNone(progress["eta_sec"])
        self.assertIn("taking longer", progress["message"])

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
