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


class CacheCleanupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.jobs_dir = Path(self.temp.name)
        self.jobs_patch = mock.patch.object(server, "JOBS_DIR", self.jobs_dir)
        self.jobs_patch.start()

    def tearDown(self):
        self.jobs_patch.stop()
        self.temp.cleanup()

    def make_job(self, status="done"):
        job_id = "00000000-0000-0000-0000-000000000001"
        job_dir = self.jobs_dir / job_id
        (job_dir / "segments").mkdir(parents=True)
        (job_dir / "output").mkdir()
        (job_dir / "segments" / "seg_000000.wav").write_bytes(b"segment-data")
        (job_dir / "output" / "book.m4b").write_bytes(b"finished-audio")
        (job_dir / "blocks.json").write_text('{"blocks": []}', encoding="utf-8")
        (job_dir / "state.json").write_text(
            json.dumps({"id": job_id, "status": status}), encoding="utf-8"
        )
        return job_id, job_dir

    def test_cleanup_removes_only_segments_and_records_freed_bytes(self):
        job_id, job_dir = self.make_job()

        with mock.patch.object(server, "log_line"), mock.patch.object(server.CFG, "ffmpeg_path", return_value="fixture"), \
             mock.patch.object(server.job_cleanup, "validate_audio", return_value=1.0):
            preview = server.preview_completed_job_cleanup(job_id)
            self.assertTrue((job_dir / "segments" / "seg_000000.wav").exists())
            freed = server.cleanup_completed_job_cache(job_id, confirmed=True, preview_token=preview["token"])

        self.assertEqual(freed, len(b"segment-data"))
        self.assertFalse((job_dir / "segments" / "seg_000000.wav").exists())
        self.assertTrue((job_dir / "output" / "book.m4b").exists())
        self.assertTrue((job_dir / "blocks.json").exists())
        state = server.load_state(job_id)
        self.assertEqual(state["segment_cache_bytes"], 0)
        self.assertEqual(state["segment_cache_freed_bytes"], freed)

    def test_unconfirmed_cleanup_keeps_all_files(self):
        job_id, job_dir = self.make_job()
        with self.assertRaisesRegex(ValueError, "explicitly confirm"):
            server.cleanup_completed_job_cache(job_id)
        self.assertTrue((job_dir / "segments" / "seg_000000.wav").exists())

    def test_new_endpoint_preview_never_removes_working_audio(self):
        job_id, job_dir = self.make_job()
        handler = server.Handler.__new__(server.Handler)
        handler.path = f"/api/jobs/{job_id}/cleanup-working-files"
        handler._read_json = mock.Mock(return_value={"preview": True})
        with mock.patch.object(server, "_json_response") as response, \
             mock.patch.object(server.CFG, "ffmpeg_path", return_value="fixture"), \
             mock.patch.object(server.job_cleanup, "validate_audio", return_value=1.0):
            handler.do_POST()
        self.assertTrue((job_dir / "segments/seg_000000.wav").exists())
        self.assertEqual(response.call_args.args[1]["preview"]["files_count"], 1)

    def test_new_page_never_calls_old_servers_destructive_endpoint(self):
        html = (APP_DIR / "static/index.html").read_text(encoding="utf-8")
        self.assertIn("fetch(`/api/jobs/${j.id}/cleanup-working-files`", html)
        self.assertNotIn("fetch(`/api/jobs/${j.id}/cleanup-cache`", html)
        self.assertIn("response.status === 404", html)

    def test_cleanup_rejects_noncompleted_job(self):
        job_id, job_dir = self.make_job(status="failed")
        with self.assertRaisesRegex(ValueError, "completed jobs"):
            server.preview_completed_job_cleanup(job_id)
        self.assertTrue((job_dir / "segments" / "seg_000000.wav").exists())


if __name__ == "__main__":
    unittest.main()
