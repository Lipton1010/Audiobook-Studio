import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
import server


class OcrErrorTests(unittest.TestCase):
    def response(self, body, status=500):
        response = requests.Response()
        response.status_code = status
        response.url = "http://localhost:11434/api/generate"
        response._content = body.encode()
        return response

    def call(self, response):
        with mock.patch("builtins.open", mock.mock_open(read_data=b"image")), \
                mock.patch.object(server.requests, "post", return_value=response):
            return server.ocr_page("page.jpg")

    def test_repeat_error_explains_cause_and_resume_limitation(self):
        response = self.response(json.dumps({"error": "prediction aborted, token repeat limit reached"}))
        with self.assertRaisesRegex(RuntimeError, "token repeat limit reached.*resuming unchanged"):
            self.call(response)

    def test_non_json_and_invalid_error_keep_http_failure(self):
        for body in ("<html>server failed</html>", "[]", '{"error": null}', '{}'):
            with self.subTest(body=body), self.assertRaises(requests.HTTPError):
                self.call(self.response(body))

    def test_error_detail_is_bounded(self):
        with self.assertRaises(RuntimeError) as caught:
            self.call(self.response(json.dumps({"error": "x" * 1000})))
        self.assertLess(len(str(caught.exception)), 450)

    def test_success_preserves_transcription(self):
        self.assertEqual(self.call(self.response('{"response": "A synthetic page."}', 200)),
                         "A synthetic page.")

    def test_unload_uses_configured_model_and_requires_confirmation(self):
        with mock.patch.object(server, "OCR_MODEL", "custom-ocr"), \
                mock.patch.object(server.requests, "post", return_value=self.response('{"done": true}', 200)) as post:
            server._release_ocr()
        post.assert_called_once_with(server.OLLAMA_URL,
                                     json={"model": "custom-ocr", "keep_alive": 0}, timeout=60)
        for response in (self.response('{"error":"busy"}'), self.response('{"done":false}', 200)):
            with mock.patch.object(server.requests, "post", return_value=response), \
                    self.assertRaisesRegex(RuntimeError, "Could not release OCR"):
                server._release_ocr()

    def test_path_b_releases_ocr_before_starting_narration_and_stops_on_failure(self):
        state = {"id": "test", "path": "B", "backend": "vibevoice"}
        blocks = [{"type": "body", "text": "A synthetic passage."}]
        with mock.patch.object(server.visual_review, "project", return_value=(blocks, [], [], {})), \
                mock.patch.object(server.visual_review, "review_payload", return_value={"narration_scope": None}), \
                mock.patch.object(server.visual_review, "_write"), \
                mock.patch.object(server, "_release_ocr") as release, \
                mock.patch.object(server, "_run_vibevoice_narration") as narrate:
            narrate.side_effect = lambda *args: release.assert_called_once_with()
            server.run_narration(state)
            narrate.assert_called_once()
            narrate.reset_mock()
            release.side_effect = RuntimeError("unload failed")
            with self.assertRaisesRegex(RuntimeError, "unload failed"):
                server.run_narration(state)
            narrate.assert_not_called()
            state["path"] = "A"
            narrate.side_effect = None
            release.reset_mock()
            server.run_narration(state)
            release.assert_not_called()

    def test_failed_page_is_identified_and_never_cached(self):
        with tempfile.TemporaryDirectory() as root:
            job = Path(root) / "test"
            (job / "pages").mkdir(parents=True)
            (job / "images").mkdir()
            (job / "pages/page_0003.md").write_text("Existing page", encoding="utf-8")
            (job / "images/page_0004.jpg").write_bytes(b"image")
            state = {"id": "test", "path": "B", "pdf_path": "unused.pdf",
                     "page_from": 3, "page_to": 4}
            with mock.patch.object(server, "JOBS_DIR", Path(root)), \
                    mock.patch.object(server, "save_state"), \
                    mock.patch.object(server, "log_line"), \
                    mock.patch.object(server, "_cancelled", return_value=False), \
                    mock.patch.object(server, "ocr_page", side_effect=RuntimeError("OCR service error")):
                with self.assertRaisesRegex(RuntimeError, "PDF page 4: OCR service error"):
                    server.run_extraction(state)
            self.assertEqual((job / "pages/page_0003.md").read_text(), "Existing page")
            self.assertFalse((job / "pages/page_0004.md").exists())
            self.assertFalse((job / "blocks.json").exists())


if __name__ == "__main__":
    unittest.main()
