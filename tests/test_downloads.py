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

import launcher
import server


class WebviewDownloadSettingTests(unittest.TestCase):
    def test_downloads_are_enabled_explicitly(self):
        fake_webview = types.SimpleNamespace(settings={"ALLOW_DOWNLOADS": False})
        launcher._enable_webview_downloads(fake_webview)
        self.assertTrue(fake_webview.settings["ALLOW_DOWNLOADS"])


class NativeWindowTests(unittest.TestCase):
    def test_native_window_uses_storybird_title_and_enabled_downloads(self):
        calls = {}
        window = types.SimpleNamespace()

        def create_window(**kwargs):
            calls["window"] = kwargs
            return window

        def start(*args, **kwargs):
            calls["start"] = (args, kwargs)

        fake_webview = types.SimpleNamespace(
            settings={"ALLOW_DOWNLOADS": False},
            create_window=create_window,
            start=start,
        )
        with mock.patch.object(launcher, "_set_windows_app_id") as set_app_id:
            launcher._open_native_window(fake_webview, "http://127.0.0.1:8765")

        self.assertTrue(fake_webview.settings["ALLOW_DOWNLOADS"])
        set_app_id.assert_called_once_with()
        self.assertEqual(calls["window"]["title"], "Storybird")
        self.assertEqual(calls["window"]["url"], "http://127.0.0.1:8765")
        self.assertEqual(calls["start"][0], (launcher._set_windows_window_icon,))
        self.assertEqual(calls["start"][1]["args"], (window,))


class DownloadHeadTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.jobs_dir = Path(self.temp.name) / "jobs"
        self.jobs_dir.mkdir()
        self.job_id = "11111111-1111-1111-1111-111111111111"
        self.job_dir = self.jobs_dir / self.job_id
        (self.job_dir / "output").mkdir(parents=True)
        (self.job_dir / "state.json").write_text(
            '{"id":"%s","title":"Synthetic Test","status":"done"}' % self.job_id,
            encoding="utf-8",
        )
        self.audio = self.job_dir / "output" / "synthetic.wav"
        self.audio.write_bytes(b"RIFF-synthetic-test")
        self.jobs_patch = mock.patch.object(server, "JOBS_DIR", self.jobs_dir)
        self.jobs_patch.start()
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.httpd.server_port}"

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=5)
        self.jobs_patch.stop()
        self.temp.cleanup()

    def head(self, path):
        request = urllib.request.Request(self.base + path, method="HEAD")
        return urllib.request.urlopen(request, timeout=5)

    def get(self, path):
        return urllib.request.urlopen(self.base + path, timeout=5)

    def test_beta_report_head_announces_zip_download(self):
        with self.head(f"/api/jobs/{self.job_id}/beta-log") as response:
            self.assertEqual(response.status, 200)
            self.assertEqual(response.headers.get_content_type(), "application/zip")
            self.assertIn("beta test report.zip", response.headers["Content-Disposition"])
            self.assertEqual(response.read(), b"")

    def test_audio_head_announces_existing_file(self):
        with self.head(f"/api/jobs/{self.job_id}/audio/synthetic.wav") as response:
            self.assertEqual(response.status, 200)
            self.assertEqual(response.headers.get_content_type(), "audio/wav")
            self.assertEqual(int(response.headers["Content-Length"]), self.audio.stat().st_size)
            self.assertEqual(response.read(), b"")

    def test_audio_head_returns_visible_failure_status_for_missing_file(self):
        with self.assertRaises(urllib.error.HTTPError) as raised:
            self.head(f"/api/jobs/{self.job_id}/audio/missing.wav")
        self.assertEqual(raised.exception.code, 404)

    def test_assembler_temporary_audio_is_never_listed_or_served(self):
        temporary = self.job_dir / "output" / ".synthetic.tmp123.m4b"
        temporary.write_bytes(b"unfinished")
        self.assertEqual([item["name"] for item in server.job_detail(self.job_id)["outputs"]],
                         ["synthetic.wav"])
        for request in (self.head, self.get):
            with self.assertRaises(urllib.error.HTTPError) as rejected:
                request(f"/api/jobs/{self.job_id}/audio/{temporary.name}")
            self.assertEqual(rejected.exception.code, 404)
        with self.get(f"/api/jobs/{self.job_id}/audio/{self.audio.name}") as response:
            self.assertEqual(response.read(), self.audio.read_bytes())


if __name__ == "__main__":
    unittest.main()
