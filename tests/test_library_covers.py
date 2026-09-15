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


class _Pixmap:
    def tobytes(self, fmt):
        assert fmt == "png"
        return b"\x89PNG\r\n\x1a\nsynthetic-cover"


class _Page:
    rect = types.SimpleNamespace(width=612, height=792)

    def get_pixmap(self, dpi=None, matrix=None, alpha=False):
        if dpi is not None:
            assert dpi == 72
        else:
            assert matrix is not None
        assert alpha is False
        return _Pixmap()


class _Document:
    page_count = 1

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def load_page(self, index):
        assert index == 0
        return _Page()


class _Fitz:
    def open(self, pdf_path):
        return _Document()

    @staticmethod
    def Matrix(x, y):
        return (x, y)


class LibraryCoverRouteTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.library = Path(self.temp.name) / "library"
        self.library.mkdir()
        self.pdf = self.library / "Synthetic Cover.pdf"
        self.pdf.write_bytes(b"%PDF-synthetic")
        self.processed = Path(self.temp.name) / "processed"
        self.jobs = Path(self.temp.name) / "jobs"
        self.jobs.mkdir()
        self.roots_patch = mock.patch.object(server, "LIBRARY_ROOTS", [self.library])
        self.import_patch = mock.patch.object(server, "PDF_IMPORT_DIR", self.library)
        self.processed_patch = mock.patch.object(server, "PROCESSED_PDF_DIR", self.processed)
        self.pages_patch = mock.patch.object(server, "page_count", return_value=1)
        self.path_patch = mock.patch.object(server, "suggest_path", return_value="A")
        self.fitz_patch = mock.patch.object(server, "fitz", _Fitz())
        self.jobs_patch = mock.patch.object(server, "JOBS_DIR", self.jobs)
        for patch in (self.roots_patch, self.import_patch, self.processed_patch, self.pages_patch, self.path_patch, self.fitz_patch, self.jobs_patch):
            patch.start()
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.httpd.server_port}"

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=5)
        for patch in (self.jobs_patch, self.fitz_patch, self.path_patch, self.pages_patch, self.processed_patch, self.import_patch, self.roots_patch):
            patch.stop()
        self.temp.cleanup()

    def test_library_item_exposes_only_an_opaque_cover_route(self):
        with urllib.request.urlopen(self.base + "/api/library", timeout=5) as response:
            item = json.load(response)["items"][0]
        self.assertEqual(item["name"], "Synthetic Cover")
        self.assertRegex(item["cover_url"], r"^/api/library/cover/[0-9a-f]{24}$")
        self.assertNotIn(str(self.pdf), item["cover_url"])

    def test_cover_route_renders_a_png_for_an_active_library_pdf(self):
        token = server._library_cover_token(self.pdf)
        with urllib.request.urlopen(self.base + "/api/library/cover/" + token, timeout=5) as response:
            self.assertEqual(response.status, 200)
            self.assertEqual(response.headers.get_content_type(), "image/png")
            self.assertEqual(response.headers["Cache-Control"], "private, max-age=3600")
            self.assertTrue(response.read().startswith(b"\x89PNG"))

    def test_cover_route_rejects_unknown_and_invalid_tokens(self):
        for suffix in ("0" * 24, "../Synthetic%20Cover.pdf"):
            with self.assertRaises(urllib.error.HTTPError) as raised:
                urllib.request.urlopen(self.base + "/api/library/cover/" + suffix, timeout=5)
            self.assertEqual(raised.exception.code, 404)

    def test_preview_route_uses_one_based_pages_and_no_store_cache(self):
        token = server._library_cover_token(self.pdf)
        with urllib.request.urlopen(self.base + f"/api/library/preview/{token}?page=1", timeout=5) as response:
            self.assertEqual(response.status, 200)
            self.assertEqual(response.headers.get_content_type(), "image/png")
            self.assertEqual(response.headers["Cache-Control"], "private, no-store")
        with self.assertRaises(urllib.error.HTTPError) as raised:
            urllib.request.urlopen(self.base + f"/api/library/preview/{token}?page=2", timeout=5)
        self.assertEqual(raised.exception.code, 400)

    def test_unrenderable_cover_returns_an_error_for_the_ui_fallback(self):
        token = server._library_cover_token(self.pdf)
        with mock.patch.object(server, "_render_library_cover", side_effect=OSError("bad image")):
            with self.assertRaises(urllib.error.HTTPError) as raised:
                urllib.request.urlopen(self.base + "/api/library/cover/" + token, timeout=5)
        self.assertEqual(raised.exception.code, 500)

    def _done_job(self, status="done"):
        job_id = "a" * 36
        job_dir = self.jobs / job_id
        (job_dir / "output").mkdir(parents=True)
        audio = job_dir / "output" / "finished.mp3"
        audio.write_bytes(b"finished-audio")
        processed_pdf = self.processed / "Finished.pdf"
        self.processed.mkdir(exist_ok=True)
        processed_pdf.write_bytes(b"%PDF-finished")
        state = {"id": job_id, "title": "Finished", "status": status,
                 "pdf_path": str(processed_pdf), "processed_pdf_path": str(processed_pdf),
                 "page_from": 1, "page_to": 1, "path": "A"}
        (job_dir / "state.json").write_text(json.dumps(state), encoding="utf-8")
        return job_id, job_dir, audio, state

    def test_done_cover_falls_back_to_processed_pdf_then_override_without_touching_audio(self):
        job_id, job_dir, audio, state = self._done_job()
        with mock.patch.object(server, "_render_library_cover", return_value=b"png-from-pdf"):
            self.assertEqual(server._job_cover_bytes(state), (b"png-from-pdf", "image/png"))
        before = audio.read_bytes()
        (job_dir / "cover_override.png").write_bytes(b"\x89PNG\r\n\x1a\noverride")
        self.assertEqual(server._job_cover_bytes(state)[0], b"\x89PNG\r\n\x1a\noverride")
        self.assertEqual(audio.read_bytes(), before)

    def test_done_cover_upload_updates_finished_audio_without_rewriting_job_state(self):
        job_id, job_dir, audio, _state = self._done_job()
        before_state = (job_dir / "state.json").read_bytes()
        request = urllib.request.Request(self.base + f"/api/jobs/{job_id}/cover",
                                         data=b"synthetic-upload", method="POST")
        def updated(paths, _artwork, _ffmpeg, *, cover_target):
            cover_target.write_bytes(b"\x89PNG\r\n\x1a\nnormalized")
            for path in paths:
                path.write_bytes(b"updated-audio")

        with mock.patch.object(server, "_validated_cover_png", return_value=b"\x89PNG\r\n\x1a\nnormalized"), \
             mock.patch.object(server, "ffmpeg_status", return_value={"path": "ffmpeg"}), \
             mock.patch.object(server, "replace_finished_artwork", side_effect=updated):
            with urllib.request.urlopen(request, timeout=5) as response:
                self.assertTrue(json.load(response)["cover_url"].startswith(f"/api/jobs/{job_id}/cover?v="))
        self.assertEqual((job_dir / "cover_override.png").read_bytes(), b"\x89PNG\r\n\x1a\nnormalized")
        self.assertEqual((job_dir / "state.json").read_bytes(), before_state)
        self.assertEqual(audio.read_bytes(), b"updated-audio")

    def test_cover_upload_rejects_non_done_job_before_decoding(self):
        job_id, _job_dir, _audio, _state = self._done_job(status="narrating")
        request = urllib.request.Request(self.base + f"/api/jobs/{job_id}/cover",
                                         data=b"synthetic-upload", method="POST")
        with mock.patch.object(server, "_validated_cover_png") as decode:
            with self.assertRaises(urllib.error.HTTPError) as raised:
                urllib.request.urlopen(request, timeout=5)
        self.assertEqual(raised.exception.code, 409)
        decode.assert_not_called()

    def test_approved_mark_and_default_cover_assets_are_served(self):
        for asset in ("storybird-mark.svg", "storybird-library-book.svg"):
            with urllib.request.urlopen(self.base + "/" + asset, timeout=5) as response:
                self.assertEqual(response.status, 200)
                self.assertEqual(response.headers.get_content_type(), "image/svg+xml")
                self.assertIn(b"<svg", response.read())


if __name__ == "__main__":
    unittest.main()
