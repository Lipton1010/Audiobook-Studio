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

        with mock.patch.object(server, "log_line"):
            freed = server.cleanup_completed_job_cache(job_id)

        self.assertEqual(freed, len(b"segment-data"))
        self.assertFalse((job_dir / "segments").exists())
        self.assertTrue((job_dir / "output" / "book.m4b").exists())
        self.assertTrue((job_dir / "blocks.json").exists())
        state = server.load_state(job_id)
        self.assertEqual(state["segment_cache_bytes"], 0)
        self.assertEqual(state["segment_cache_freed_bytes"], freed)

    def test_cleanup_rejects_noncompleted_job(self):
        job_id, job_dir = self.make_job(status="failed")
        with self.assertRaisesRegex(ValueError, "completed jobs"):
            server.cleanup_completed_job_cache(job_id)
        self.assertTrue((job_dir / "segments" / "seg_000000.wav").exists())


if __name__ == "__main__":
    unittest.main()
