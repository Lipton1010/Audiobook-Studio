import os
import json
import subprocess
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


class LegacyPidSafetyTests(unittest.TestCase):
    def test_stale_pid_file_is_deleted_without_killing_its_process(self):
        with tempfile.TemporaryDirectory() as temp:
            job_dir = Path(temp)
            # The current test runner is an unquestionably live, unrelated
            # process. A reused PID must never be treated as worker ownership.
            (job_dir / "worker_pids.txt").write_text(
                str(os.getpid()), encoding="utf-8"
            )
            with mock.patch.object(server.subprocess, "run") as run:
                server._discard_legacy_worker_pid_file(job_dir)
            run.assert_not_called()
            self.assertFalse((job_dir / "worker_pids.txt").exists())


class WorkerOwnershipTests(unittest.TestCase):
    def test_spawn_failure_stops_worker_if_job_assignment_fails(self):
        proc = mock.Mock()
        proc.poll.return_value = None
        with mock.patch.object(server.subprocess, "Popen", return_value=proc), \
             mock.patch.object(
                 server, "_assign_worker_to_job", side_effect=OSError("cannot assign")
             ):
            with self.assertRaisesRegex(OSError, "cannot assign"):
                server._spawn_worker(Path("job"), mock.Mock(), [])
        proc.kill.assert_called_once()
        proc.wait.assert_called_once_with(timeout=10)

    @unittest.skipUnless(os.name == "nt", "Windows Job Objects are Windows-only")
    def test_closing_job_object_terminates_owned_child(self):
        child = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            creationflags=server.WINDOWS_NO_WINDOW,
        )
        job = server._WindowsWorkerJob()
        try:
            job.assign(child)
            job.close()
            child.wait(timeout=10)
            self.assertIsNotNone(child.returncode)
        finally:
            job.close()
            if child.poll() is None:
                child.kill()
                child.wait(timeout=10)


class RunNarrationCleanupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.jobs_dir = Path(self.temp.name)
        self.job_id = "33333333-3333-3333-3333-333333333333"
        self.job_dir = self.jobs_dir / self.job_id
        self.job_dir.mkdir()
        self.state = {
            "id": self.job_id,
            "title": "Synthetic",
            "path": "A",
            "pdf_path": "synthetic.pdf",
            "engine": "batched",
            "format": "wav",
        }
        (self.job_dir / "blocks.json").write_text(
            json.dumps({"blocks": [{"type": "body", "text": "Synthetic prose."}]}),
            encoding="utf-8",
        )
        self.common = [
            mock.patch.object(server, "JOBS_DIR", self.jobs_dir),
            mock.patch.object(server, "extract_book_meta", return_value=({}, None, [])),
            mock.patch.object(server, "ensure_segments_fresh"),
            mock.patch.object(server, "save_state"),
            mock.patch.object(server, "log_line"),
            mock.patch.object(server, "voice_wav_path", return_value="synthetic.wav"),
            mock.patch.object(server, "scaled_batch_token_budget", return_value=300),
        ]
        for patcher in self.common:
            patcher.start()

    def tearDown(self):
        server._cancel_flags.pop(self.job_id, None)
        server._clear_active_processes(self.job_id)
        for patcher in reversed(self.common):
            patcher.stop()
        self.temp.cleanup()

    def test_worker_failure_cleans_legacy_metadata_and_active_handles(self):
        (self.job_dir / "worker_pids.txt").write_text("123", encoding="utf-8")
        proc = mock.Mock()
        proc.wait.return_value = 1
        proc.poll.return_value = 1
        with mock.patch.object(server, "_spawn_worker", return_value=proc):
            with self.assertRaisesRegex(RuntimeError, "exit codes"):
                server.run_narration(self.state)
        self.assertFalse((self.job_dir / "worker_pids.txt").exists())
        self.assertIsNone(server._active_procs["job_id"])
        self.assertEqual(server._active_procs["procs"], [])

    def test_cancel_during_spawn_registration_stops_owned_worker(self):
        proc = mock.Mock()
        proc.poll.return_value = None
        proc.wait.return_value = 0

        def spawn(*_args, **_kwargs):
            server._cancel_flags[self.job_id] = True
            return proc

        with mock.patch.object(server, "_spawn_worker", side_effect=spawn):
            with self.assertRaises(server._Cancelled):
                server.run_narration(self.state)
        proc.kill.assert_called_once()
        self.assertIsNone(server._active_procs["job_id"])

    def test_stalled_batch_stops_owned_worker_and_preserves_segments(self):
        seg_dir = self.job_dir / "segments"
        seg_dir.mkdir()
        segment = seg_dir / "seg_000000.wav"
        segment.write_bytes(b"completed audio")
        proc = mock.Mock()
        proc.poll.return_value = None
        proc.wait.side_effect = [subprocess.TimeoutExpired("worker", 5), 0]

        def spawn(*_args, **_kwargs):
            progress = self.job_dir / "narration_progress.json"
            progress.write_text('{}', encoding="utf-8")
            os.utime(progress, (100, 100))
            return proc

        with mock.patch.object(server, "_spawn_worker", side_effect=spawn), \
             mock.patch.object(server.time, "time", return_value=401):
            with self.assertRaisesRegex(RuntimeError, "five minutes"):
                server.run_narration(self.state)
        proc.kill.assert_called_once()
        self.assertEqual(segment.read_bytes(), b"completed audio")
        self.assertIsNone(server._active_procs["job_id"])


if __name__ == "__main__":
    unittest.main()
