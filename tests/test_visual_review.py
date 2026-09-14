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


class VisualReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.jobs = Path(self.temp.name) / "jobs"
        self.jobs.mkdir()
        self.patch = mock.patch.object(server, "JOBS_DIR", self.jobs)
        self.patch.start()
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.httpd.server_port}"

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=5)
        self.patch.stop()
        self.temp.cleanup()

    def make_job(self, status="review_required", source=True):
        job_id = "11111111-1111-1111-1111-111111111111"
        job_dir = self.jobs / job_id
        job_dir.mkdir()
        state = {"id": job_id, "title": "Synthetic", "status": status, "path": "A",
                 "pdf_path": "missing.pdf", "voice": "Test"}
        (job_dir / "state.json").write_text(json.dumps(state), encoding="utf-8")
        blocks = [
            {"type": "body", "text": "Before prose.", "source_page": 1},
            {"type": "visual", "text": "Figure 1: red circle.", "visual_kind": "figure", "source_page": 1},
            {"type": "body", "text": "After prose.", "source_page": 1},
        ]
        (job_dir / "blocks.json").write_text(json.dumps({"blocks": blocks}), encoding="utf-8")
        if source:
            (job_dir / "source_blocks.json").write_text(
                json.dumps({"blocks": blocks, "source_available": True}), encoding="utf-8")
        return job_id, job_dir

    def request(self, method, path, body=None):
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(self.base + path, data=data, method=method,
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=5) as response:
            return response.status, json.load(response)

    def test_review_is_durable_and_requires_preview_before_queueing(self):
        job_id, job_dir = self.make_job()
        _, review = self.request("GET", f"/api/jobs/{job_id}/visual-review")
        item = review["items"][0]
        self.assertEqual(item["nearby_prose"], {"before": ["Before prose."], "after": ["After prose."]})
        self.assertEqual(review["unresolved_count"], 1)
        _, saved = self.request("POST", f"/api/jobs/{job_id}/visual-review/{item['id']}", {
            "fingerprint": item["fingerprint"], "decision": "describe", "spoken_text": "A red circle is shown.",
        })
        self.assertEqual(saved["unresolved_count"], 0)
        self.assertEqual(json.loads((job_dir / "source_blocks.json").read_text())["blocks"][1]["text"], "Figure 1: red circle.")
        projected = json.loads((job_dir / "blocks.json").read_text())["blocks"]
        self.assertEqual(projected[1]["text"], "A red circle is shown.")
        with self.assertRaises(urllib.error.HTTPError) as raised:
            self.request("POST", f"/api/jobs/{job_id}/visual-review/start", {})
        self.assertEqual(raised.exception.code, 409)
        _, preview = self.request("GET", f"/api/jobs/{job_id}/visual-review/preview")
        self.assertIn("A red circle is shown.", preview["text"])
        self.request("POST", f"/api/jobs/{job_id}/visual-review/start", {})
        self.assertEqual(server.load_state(job_id)["status"], "queued")

    def test_legacy_visual_stays_unresolved_without_raw_source(self):
        job_id, job_dir = self.make_job(source=False)
        _, review = self.request("GET", f"/api/jobs/{job_id}/visual-review")
        self.assertTrue(review["items"][0]["source_available"])
        self.assertEqual(review["unresolved_count"], 1)
        self.assertTrue((job_dir / "source_blocks.json").exists())

    def test_partial_cached_pages_do_not_replace_legacy_source(self):
        job_id, job_dir = self.make_job(source=False)
        pages = job_dir / "pages"
        pages.mkdir()
        (pages / "page_0001.md").write_text("A table | 1 | 2", encoding="utf-8")
        state = server.load_state(job_id)
        state.update({"page_from": 1, "page_to": 2})
        server.save_state(state)
        _, review = self.request("GET", f"/api/jobs/{job_id}/visual-review")
        self.assertTrue(review["items"][0]["source_available"])
        source = json.loads((job_dir / "source_blocks.json").read_text())
        self.assertTrue(source["migrated_legacy"])

    def test_changed_done_review_hides_stale_audio_without_deleting_it(self):
        job_id, job_dir = self.make_job(status="done")
        output = job_dir / "output"
        output.mkdir()
        audio = output / "book.mp3"
        audio.write_bytes(b"old audio")
        self.request("POST", f"/api/jobs/{job_id}/visual-review/reopen", {})
        _, review = self.request("GET", f"/api/jobs/{job_id}/visual-review")
        item = review["items"][0]
        self.request("POST", f"/api/jobs/{job_id}/visual-review/{item['id']}", {
            "fingerprint": item["fingerprint"], "decision": "describe", "spoken_text": "A manually described red circle.",
        })
        self.assertTrue(audio.exists())
        self.assertTrue(server.load_state(job_id)["narration_stale"])
        self.assertNotIn("outputs", server.job_detail(job_id))

    def test_explicit_regeneration_snapshots_old_job_and_library_audio(self):
        job_id, job_dir = self.make_job(status="done")
        output = job_dir / "output"
        output.mkdir()
        (output / "book.mp3").write_bytes(b"prior job audio")
        library = Path(self.temp.name) / "library"
        library.mkdir()
        (library / "book.mp3").write_bytes(b"prior library audio")
        state = server.load_state(job_id)
        state["audiobook_dir"] = str(library)
        server.save_state(state)
        self.request("POST", f"/api/jobs/{job_id}/visual-review/reopen", {})
        _, review = self.request("GET", f"/api/jobs/{job_id}/visual-review")
        item = review["items"][0]
        self.request("POST", f"/api/jobs/{job_id}/visual-review/{item['id']}", {
            "fingerprint": item["fingerprint"], "decision": "skip",
        })
        self.request("GET", f"/api/jobs/{job_id}/visual-review/preview")
        self.request("POST", f"/api/jobs/{job_id}/visual-review/start", {})
        snapshot = Path(server.load_state(job_id)["previous_output_snapshot"])
        self.assertEqual((snapshot / "job_output" / "book.mp3").read_bytes(), b"prior job audio")
        self.assertEqual((snapshot / "library_output" / "book.mp3").read_bytes(), b"prior library audio")

    def test_all_skipped_visuals_cannot_start_empty_narration(self):
        job_id, _job_dir = self.make_job()
        _, review = self.request("GET", f"/api/jobs/{job_id}/visual-review")
        item = review["items"][0]
        self.request("POST", f"/api/jobs/{job_id}/visual-review/{item['id']}", {
            "fingerprint": item["fingerprint"], "decision": "skip",
        })
        self.request("GET", f"/api/jobs/{job_id}/visual-review/preview")
        # The fixture still has prose, so replace the preserved source with only
        # the reviewed visual to exercise the pre-GPU empty-plan guard.
        source = {"blocks": [{"type": "visual", "text": "diagram", "visual_kind": "diagram"}], "source_available": True}
        (self.jobs / job_id / "source_blocks.json").write_text(json.dumps(source), encoding="utf-8")
        _, review = self.request("GET", f"/api/jobs/{job_id}/visual-review")
        item = review["items"][0]
        self.request("POST", f"/api/jobs/{job_id}/visual-review/{item['id']}", {
            "fingerprint": item["fingerprint"], "decision": "skip",
        })
        self.request("GET", f"/api/jobs/{job_id}/visual-review/preview")
        with self.assertRaises(urllib.error.HTTPError) as raised:
            self.request("POST", f"/api/jobs/{job_id}/visual-review/start", {})
        self.assertEqual(raised.exception.code, 409)

    def test_legacy_structured_log_is_one_visual_without_consuming_neighbors(self):
        import visual_review
        blocks = visual_review._legacy_visuals([
            {"type": "heading", "text": "CHAPTER ONE"},
            {"type": "heading", "text": "[AV12]"},
            {"type": "body", "text": "12:04 system ready"},
            {"type": "heading", "text": "[BC34]"},
            {"type": "body", "text": "12:05 door unlocked"},
            {"type": "dialogue", "text": "\"Do you hear that?\""},
            {"type": "body", "text": "They left the room."},
        ])
        self.assertEqual([block["type"] for block in blocks], ["heading", "visual", "dialogue", "body"])
        self.assertEqual(blocks[1]["visual_kind"], "structured log")
        self.assertIn("[AV12]", blocks[1]["text"])
        self.assertIn("12:05", blocks[1]["text"])

    def test_blank_path_b_ocr_page_is_reviewed_and_survives_cache_recovery(self):
        job_id = "33333333-3333-3333-3333-333333333333"
        job_dir = self.jobs / job_id
        job_dir.mkdir()
        state = {"id": job_id, "path": "B", "pdf_path": "synthetic.pdf",
                 "page_from": 1, "page_to": 1, "status": "queued"}
        with mock.patch.object(server, "save_state"), mock.patch.object(server, "log_line"), \
                mock.patch.object(server.pt, "rasterize_page"), mock.patch.object(server, "ocr_page", return_value=""):
            server.run_extraction(state)
        source = json.loads((job_dir / "source_blocks.json").read_text())["blocks"]
        self.assertEqual(source, [{"type": "visual", "text": "", "visual_kind": "unreadable OCR page", "source_page": 1}])
        (job_dir / "source_blocks.json").unlink()
        import visual_review
        recovered, items, _decisions = visual_review.prepare(job_dir, state)
        self.assertEqual(recovered[0]["visual_kind"], "unreadable OCR page")
        self.assertEqual(items[0]["decision"], None)


if __name__ == "__main__":
    unittest.main()
