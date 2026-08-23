import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

APP_DIR = Path(__file__).resolve().parents[1] / "app"
sys.path.insert(0, str(APP_DIR))
sys.modules.setdefault("fitz", types.ModuleType("fitz"))

import server


class ScaledBatchTokenBudgetTests(unittest.TestCase):
    """server.py cannot import torch (base env), so it can only size the
    batched engine's per-job budget from nvidia-smi's VRAM total. These
    pin the formula's behavior at the calibration point (a 4090, where
    1300 was measured), a smaller card, and an undetectable GPU."""

    def test_full_size_card_keeps_the_measured_ceiling(self):
        with mock.patch.object(server, "gpu_total_vram_gb", return_value=24.0):
            self.assertEqual(server.scaled_batch_token_budget(), 1300)

    def test_smaller_card_scales_down(self):
        with mock.patch.object(server, "gpu_total_vram_gb", return_value=8.0):
            budget = server.scaled_batch_token_budget()
        self.assertLess(budget, 1300)
        self.assertGreaterEqual(budget, 150)

    def test_unknown_gpu_stays_conservative(self):
        with mock.patch.object(server, "gpu_total_vram_gb", return_value=None):
            self.assertEqual(server.scaled_batch_token_budget(), 300)

    def test_explicit_env_override_wins_over_small_card(self):
        with mock.patch.object(server, "gpu_total_vram_gb", return_value=4.0), \
             mock.patch.dict("os.environ", {"AUDIOBOOK_BATCH_TOKEN_BUDGET": "700"}), \
             mock.patch.object(server, "BATCH_TOKEN_BUDGET", 700):
            self.assertEqual(server.scaled_batch_token_budget(), 700)


class MissingGpuErrorTests(unittest.TestCase):
    def test_no_gpu_detected_returns_a_message(self):
        with mock.patch.object(server, "gpu_total_vram_gb", return_value=None):
            err = server.missing_gpu_error()
        self.assertIsNotNone(err)
        self.assertIn("NVIDIA GPU", err)

    def test_gpu_present_returns_none(self):
        with mock.patch.object(server, "gpu_total_vram_gb", return_value=12.0):
            self.assertIsNone(server.missing_gpu_error())


class NarrationFailureMessageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.job_dir = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_falls_back_to_generic_message_without_error_json(self):
        msg = server._narration_failure_message(self.job_dir, [1])
        self.assertIn("exit codes", msg)

    def test_uses_worker_written_clean_message_when_present(self):
        (self.job_dir / "error.json").write_text(
            json.dumps({"reason": "gpu_oom", "message": "GPU ran out of VRAM."}),
            encoding="utf-8",
        )
        msg = server._narration_failure_message(self.job_dir, [1])
        self.assertEqual(msg, "GPU ran out of VRAM.")

    def test_malformed_error_json_falls_back_without_crashing(self):
        (self.job_dir / "error.json").write_text("not json", encoding="utf-8")
        msg = server._narration_failure_message(self.job_dir, [1])
        self.assertIn("exit codes", msg)


class ReportCrashTests(unittest.TestCase):
    def test_disabled_by_default_makes_no_network_call(self):
        with mock.patch.object(server.CFG, "error_webhook_url", None), \
             mock.patch("server.requests.post") as post:
            server._report_crash({"id": "j1", "title": "Book"}, "narrating", RuntimeError("boom"))
        post.assert_not_called()

    def test_configured_webhook_posts_structured_fields_only(self):
        with mock.patch.object(server.CFG, "error_webhook_url", "https://discord.example/webhook"), \
             mock.patch.object(server, "_gpu_report_info", return_value="Fake GPU, 8192 MiB"), \
             mock.patch("server.requests.post") as post:
            server._report_crash(
                {"id": "j1", "title": "Some Book", "engine": "batched"},
                "narrating",
                RuntimeError("GPU ran out of VRAM."),
            )
        post.assert_called_once()
        url, kwargs = post.call_args[0][0], post.call_args[1]
        self.assertEqual(url, "https://discord.example/webhook")
        payload_str = json.dumps(kwargs["json"])
        self.assertIn("GPU ran out of VRAM.", payload_str)
        self.assertIn("Some Book", payload_str)
        self.assertIn("Fake GPU", payload_str)
        # Never send book text: this test's stand-in for chunk prose must
        # never appear in the report payload.
        self.assertNotIn("chunk_text_should_never_appear", payload_str)

    def test_network_failure_does_not_raise(self):
        with mock.patch.object(server.CFG, "error_webhook_url", "https://discord.example/webhook"), \
             mock.patch.object(server, "_gpu_report_info", return_value="Fake GPU"), \
             mock.patch("server.requests.post", side_effect=OSError("no network")), \
             mock.patch.object(server, "log_line"):
            server._report_crash({"id": "j1", "title": "Book"}, "narrating", RuntimeError("boom"))
        # Reaching here without an exception is the assertion.


class CheckForUpdateTests(unittest.TestCase):
    def test_newer_tag_reports_update_available(self):
        resp = mock.Mock(status_code=200)
        resp.json.return_value = {"tag_name": "v9.9.9", "html_url": "https://x/releases/v9.9.9"}
        with mock.patch.object(server, "APP_VERSION", "1.0.1"), \
             mock.patch("server.requests.get", return_value=resp):
            result = server.check_for_update()
        self.assertTrue(result["update_available"])
        self.assertEqual(result["latest"], "v9.9.9")
        self.assertEqual(result["release_url"], "https://x/releases/v9.9.9")

    def test_same_or_older_tag_reports_no_update(self):
        resp = mock.Mock(status_code=200)
        resp.json.return_value = {"tag_name": "v1.0.1"}
        with mock.patch.object(server, "APP_VERSION", "1.0.1"), \
             mock.patch("server.requests.get", return_value=resp):
            result = server.check_for_update()
        self.assertFalse(result["update_available"])

    def test_network_failure_reports_no_update_without_raising(self):
        with mock.patch.object(server, "APP_VERSION", "1.0.1"), \
             mock.patch("server.requests.get", side_effect=OSError("no network")):
            result = server.check_for_update()
        self.assertFalse(result["update_available"])

    def test_non_200_reports_no_update(self):
        with mock.patch.object(server, "APP_VERSION", "1.0.1"), \
             mock.patch("server.requests.get", return_value=mock.Mock(status_code=404)):
            result = server.check_for_update()
        self.assertFalse(result["update_available"])


if __name__ == "__main__":
    unittest.main()
