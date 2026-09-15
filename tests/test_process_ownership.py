import os
import json
import subprocess
import sys
import tempfile
import time
import types
import unittest
from pathlib import Path
from unittest import mock

APP_DIR = Path(__file__).resolve().parents[1] / "app"
sys.path.insert(0, str(APP_DIR))
sys.modules.setdefault("fitz", types.ModuleType("fitz"))

import server


def _process_is_running(pid):
    if os.name != "nt":
        return False
    import ctypes
    from ctypes import wintypes
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    kernel32.GetExitCodeProcess.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    handle = kernel32.OpenProcess(0x1000, False, pid)
    if not handle:
        return False
    code = wintypes.DWORD()
    try:
        return bool(kernel32.GetExitCodeProcess(handle, ctypes.byref(code)) and code.value == 259)
    finally:
        kernel32.CloseHandle(handle)


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

    @unittest.skipUnless(os.name == "nt", "Windows Job Objects are Windows-only")
    def test_terminate_processes_closes_job_and_kills_descendant(self):
        root = Path(tempfile.mkdtemp())
        trigger, child_pid = root / "trigger", root / "child.pid"
        script = "\n".join([
            "from pathlib import Path",
            "import subprocess, sys, time",
            "trigger, output = map(Path, sys.argv[1:])",
            "while not trigger.exists(): time.sleep(.01)",
            "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])",
            "output.write_text(str(child.pid))",
            "time.sleep(30)",
        ])
        parent = subprocess.Popen([sys.executable, "-c", script, str(trigger), str(child_pid)],
                                  creationflags=server.WINDOWS_NO_WINDOW)
        try:
            server._assign_worker_to_job(parent)
            trigger.write_text("go", encoding="utf-8")
            for _ in range(100):
                if child_pid.exists():
                    break
                time.sleep(.05)
            self.assertTrue(child_pid.exists())
            descendant = int(child_pid.read_text(encoding="utf-8"))
            self.assertTrue(_process_is_running(descendant))
            server._terminate_processes([parent])
            time.sleep(.1)
            self.assertFalse(_process_is_running(descendant))
        finally:
            server._close_worker_job([parent])
            if parent.poll() is None:
                parent.kill()
                parent.wait(timeout=10)
            child_pid.unlink(missing_ok=True)
            trigger.unlink(missing_ok=True)
            root.rmdir()

    def test_terminate_processes_closes_only_the_passed_worker_job(self):
        old, current = mock.Mock(), mock.Mock()
        old.poll.return_value = current.poll.return_value = 0
        old_job, current_job = mock.Mock(), mock.Mock()
        old._audiobook_job, current._audiobook_job = old_job, current_job

        server._terminate_processes([old])

        old_job.close.assert_called_once()
        current_job.close.assert_not_called()


class CancelOwnershipTests(unittest.TestCase):
    def tearDown(self):
        server._cancel_flags.clear()
        server._clear_active_processes("active")

    def test_cancel_without_an_active_handle_preserves_another_worker_job(self):
        active = mock.Mock()
        active.poll.return_value = None
        active_job = mock.Mock()
        active._audiobook_job = active_job
        server._set_active_processes("active", [active])
        queued = {"id": "queued", "status": "queued", "backend": "chatterbox"}

        with mock.patch.object(server, "load_state", return_value=queued), \
             mock.patch.object(server, "save_state", return_value=True):
            server.request_cancel("queued")

        active_job.close.assert_not_called()
        active.kill.assert_not_called()

    @unittest.skipUnless(os.name == "nt", "Windows Job Objects are Windows-only")
    def test_canceling_queued_job_preserves_active_worker_descendant(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            trigger, child_pid = root / "trigger", root / "child.pid"
            script = "\n".join([
                "from pathlib import Path",
                "import subprocess, sys, time",
                "trigger, output = map(Path, sys.argv[1:])",
                "while not trigger.exists(): time.sleep(.01)",
                "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])",
                "output.write_text(str(child.pid))",
                "time.sleep(30)",
            ])
            active = subprocess.Popen([sys.executable, "-c", script, str(trigger), str(child_pid)],
                                      creationflags=server.WINDOWS_NO_WINDOW)
            try:
                server._assign_worker_to_job(active)
                server._set_active_processes("active", [active])
                trigger.write_text("go", encoding="utf-8")
                for _ in range(100):
                    if child_pid.exists():
                        break
                    time.sleep(.05)
                self.assertTrue(child_pid.exists())
                descendant = int(child_pid.read_text(encoding="utf-8"))
                with mock.patch.object(server, "load_state", return_value={"id": "queued", "status": "queued"}), \
                     mock.patch.object(server, "save_state", return_value=True):
                    server.request_cancel("queued")
                self.assertTrue(_process_is_running(descendant))
            finally:
                server._terminate_processes([active])
                server._clear_active_processes("active")


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
