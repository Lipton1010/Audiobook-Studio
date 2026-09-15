import json
import sys
import tempfile
import threading
import types
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock


APP_DIR = Path(__file__).resolve().parents[1] / "app"
sys.path.insert(0, str(APP_DIR))
sys.modules.setdefault("fitz", types.ModuleType("fitz"))

import server


class FinishedOutputApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.jobs, self.library = root / "jobs", root / "library"
        self.jobs.mkdir()
        self.library.mkdir()
        self.job_id = "11111111-1111-1111-1111-111111111111"
        self.job = self.jobs / self.job_id
        (self.job / "output").mkdir(parents=True)
        self.local = self.job / "output" / "Synthetic.m4b"
        self.local.write_bytes(b"local")
        self.copy = self.library / "Synthetic" / "Synthetic.mp3"
        self.copy.parent.mkdir()
        self.copy.write_bytes(b"library")
        (self.copy.parent / ".storybird-job.json").write_text(json.dumps({"job_id": self.job_id}), encoding="utf-8")
        self.state = {"id": self.job_id, "title": "Synthetic", "status": "done",
                      "audiobook_dir": str(self.copy.parent)}
        (self.job / "state.json").write_text(json.dumps(self.state), encoding="utf-8")
        self.jobs_patch = mock.patch.object(server, "JOBS_DIR", self.jobs)
        self.library_patch = mock.patch.object(server, "AUDIOBOOKS_DIR", self.library)
        self.jobs_patch.start()
        self.library_patch.start()
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.httpd.server_port}"

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=5)
        self.library_patch.stop()
        self.jobs_patch.stop()
        self.temp.cleanup()

    def post(self, suffix, body=b"{}", headers=None):
        request = urllib.request.Request(self.base + f"/api/jobs/{self.job_id}/{suffix}", data=body,
                                         method="POST", headers=headers or {})
        with urllib.request.urlopen(request, timeout=5) as response:
            return json.load(response)

    def test_cover_updates_job_and_library_copies_in_one_operation(self):
        with mock.patch.object(server, "_validated_cover_png", return_value=b"\x89PNG\r\n\x1a\ncover"), \
             mock.patch.object(server, "ffmpeg_status", return_value={"path": "ffmpeg"}), \
             mock.patch.object(server, "replace_finished_artwork") as replace:
            response = self.post("cover", b"cover")
        self.assertTrue(response["ok"])
        self.assertEqual(set(replace.call_args.args[0]), {self.local, self.copy})
        self.assertEqual(replace.call_args.kwargs["cover_target"], self.job / "cover_override.png")

    def test_cover_and_export_require_current_done_job(self):
        self.state["status"] = "narrating"
        server.save_state(self.state)
        for suffix, body, headers in (("cover", b"cover", {}),
                                      ("export", b'{"format":"m4b"}', {"Content-Type": "application/json"})):
            with self.assertRaises(urllib.error.HTTPError) as raised:
                self.post(suffix, body, headers)
            self.assertEqual(raised.exception.code, 409)

    def test_export_reuses_selected_job_output_and_rejects_malformed_format(self):
        response = self.post("export", b'{"format":"m4b"}')
        self.assertEqual(response, {"ok": True, "output": {"name": self.local.name, "bytes": 5}})
        with self.assertRaises(urllib.error.HTTPError) as raised:
            self.post("export", b'{"format":"zip"}')
        self.assertEqual(raised.exception.code, 400)

    def test_cover_and_delete_are_serialized_per_job(self):
        entered, release = threading.Event(), threading.Event()

        def replace(*_args, **_kwargs):
            entered.set()
            release.wait(2)

        with mock.patch.object(server, "_validated_cover_png", return_value=b"\x89PNG\r\n\x1a\ncover"), \
             mock.patch.object(server, "ffmpeg_status", return_value={"path": "ffmpeg"}), \
             mock.patch.object(server, "replace_finished_artwork", side_effect=replace):
            cover = threading.Thread(target=lambda: self.post("cover", b"cover"))
            cover.start()
            self.assertTrue(entered.wait(2))
            delete = threading.Thread(target=lambda: self.post(
                "delete", b'{"mode":"library","confirmed":true}', {"Content-Type": "application/json"}))
            delete.start()
            self.assertTrue(self.job.exists())
            release.set()
            cover.join(3)
            delete.join(3)
        self.assertTrue(self.job.exists())
        self.assertTrue(server.load_state(self.job_id)["library_hidden"])

    def test_regeneration_keeps_old_checkpoints_and_copies_preview_scope(self):
        old_segments = self.job / "segments"
        old_segments.mkdir()
        checkpoint = old_segments / "seg_000001.wav"
        checkpoint.write_bytes(b"accepted checkpoint")
        (self.job / "narration_scope.json").write_text('{"end_page": 9}', encoding="utf-8")
        pdf = Path(self.temp.name) / "Synthetic.pdf"
        pdf.write_bytes(b"%PDF-synthetic")
        with mock.patch.object(server, "_review_pdf_path", return_value=pdf), \
             mock.patch.object(server, "missing_voice_error", return_value=None), \
             mock.patch.object(server, "missing_gpu_error", return_value=None), \
             mock.patch.object(server, "missing_ffmpeg_error", return_value=None), \
             mock.patch.object(server, "missing_vibevoice_error", return_value=None), \
             mock.patch.object(server, "enqueue") as enqueue:
            regenerated = server.regenerate_job(self.job_id, "vibevoice")
        new_job = self.jobs / regenerated["id"]
        self.assertEqual(regenerated["status"], "queued")
        self.assertTrue(regenerated["preview_required"])
        self.assertEqual(checkpoint.read_bytes(), b"accepted checkpoint")
        self.assertFalse((new_job / "segments").exists())
        self.assertEqual((new_job / "narration_scope.json").read_text(encoding="utf-8"), '{"end_page": 9}')
        enqueue.assert_called_once_with(regenerated["id"])

    def test_generated_delete_does_not_remove_files_before_intent_is_saved(self):
        with mock.patch.object(server, "save_state", return_value=False), \
             mock.patch.object(server, "delete_generated_files") as delete:
            with self.assertRaises(urllib.error.HTTPError) as raised:
                self.post("delete", b'{"mode":"generated","confirmed":true}', {"Content-Type": "application/json"})
        self.assertEqual(raised.exception.code, 500)
        delete.assert_not_called()
        self.assertTrue(self.local.exists())
        self.assertEqual(server.load_state(self.job_id)["status"], "done")

    def test_generated_delete_reports_500_and_keeps_durable_deleting_state_after_files_removed(self):
        calls = 0

        def save_intent(state):
            nonlocal calls
            calls += 1
            if calls == 1:
                (self.job / "state.json").write_text(json.dumps(state), encoding="utf-8")
                return True
            return False

        def delete_files(*_args):
            self.local.unlink()
            return 5

        with mock.patch.object(server, "save_state", side_effect=save_intent), \
             mock.patch.object(server, "delete_generated_files", side_effect=delete_files):
            with self.assertRaises(urllib.error.HTTPError) as raised:
                self.post("delete", b'{"mode":"generated","confirmed":true}', {"Content-Type": "application/json"})
        self.assertEqual(raised.exception.code, 500)
        self.assertIn("file operation finished", raised.exception.read().decode("utf-8"))
        self.assertFalse(self.local.exists())
        self.assertEqual(server.load_state(self.job_id)["status"], "deleting")

    def test_startup_recovers_interrupted_generated_delete_as_failed(self):
        self.state["status"] = "deleting"
        self.state["delete_requested_at"] = 123
        server.save_state(self.state)
        server.mark_interrupted_jobs()
        recovered = server.load_state(self.job_id)
        self.assertEqual(recovered["status"], "delete_failed")
        self.assertIn("interrupted", recovered["error"].lower())


if __name__ == "__main__":
    unittest.main()
