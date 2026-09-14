import importlib
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
import pipeline_text as pt
import visual_review


def _blocks(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))["blocks"]


class VisualReviewProjectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.job_dir = Path(self.temp.name)
        self.source = [
            {"type": "heading", "text": "Chapter One", "source_page": 4},
            {"type": "body", "text": "Before the display.", "source_page": 4},
            {
                "type": "visual",
                "text": "Red rises from 2 to 7; blue falls from 9 to 3.",
                "visual_kind": "chart",
                "source_page": 5,
            },
            {"type": "dialogue", "text": "\u201cAfter it, we continue.\u201d", "source_page": 5},
        ]
        visual_review._write(
            self.job_dir / "source_blocks.json",
            {"blocks": self.source, "source_available": True},
        )
        visual_review._write(self.job_dir / "blocks.json", {"blocks": self.source})

    def tearDown(self):
        self.temp.cleanup()

    def item(self):
        return visual_review.review_payload(self.job_dir)["items"][0]

    def decide(self, decision, spoken_text=""):
        item = self.item()
        visual_review.save_decision(
            self.job_dir, item["id"], item["fingerprint"], decision, spoken_text
        )
        self.assertTrue(visual_review.write_projection(self.job_dir))

    def test_review_context_does_not_consume_nearby_heading_or_prose(self):
        item = self.item()
        self.assertEqual(item["nearby_prose"]["before"], ["Chapter One", "Before the display."])
        self.assertEqual(item["nearby_prose"]["after"], ["\u201cAfter it, we continue.\u201d"])

        self.decide("skip")

        self.assertEqual(
            _blocks(self.job_dir / "blocks.json"),
            [self.source[0], self.source[1], self.source[3]],
        )
        self.assertEqual(_blocks(self.job_dir / "source_blocks.json"), self.source)

    def test_keep_describe_and_skip_have_exact_spoken_results(self):
        self.decide("keep")
        self.assertEqual(
            [block["text"] for block in _blocks(self.job_dir / "blocks.json")],
            ["Chapter One", "Before the display.", self.source[2]["text"],
             "\u201cAfter it, we continue.\u201d"],
        )

        self.decide("describe", "The red value climbs by five while blue drops by six.")
        projected = _blocks(self.job_dir / "blocks.json")
        self.assertEqual(projected[2]["text"], "The red value climbs by five while blue drops by six.")
        self.assertEqual(projected[2]["source_page"], 5)

        self.decide("skip")
        self.assertNotIn(self.source[2]["text"], [block["text"] for block in _blocks(self.job_dir / "blocks.json")])

    def test_stale_fingerprint_rejects_without_changing_saved_decision(self):
        self.decide("keep")
        before = (self.job_dir / "visual_review.json").read_bytes()
        item = self.item()

        with self.assertRaisesRegex(ValueError, "changed"):
            visual_review.save_decision(
                self.job_dir, item["id"], "0" * 64, "skip", ""
            )

        self.assertEqual((self.job_dir / "visual_review.json").read_bytes(), before)
        self.assertEqual(self.item()["decision"], "keep")

    def test_legacy_blocks_are_preserved_but_visuals_remain_unresolved(self):
        (self.job_dir / "source_blocks.json").unlink()
        original = (self.job_dir / "blocks.json").read_bytes()
        payload = visual_review.review_payload(self.job_dir)

        self.assertEqual(payload["unresolved_count"], 1)
        migrated = json.loads((self.job_dir / "source_blocks.json").read_text(encoding="utf-8"))
        self.assertFalse(migrated["source_available"])
        self.assertTrue(migrated["migrated_legacy"])
        self.assertEqual(migrated["blocks"], self.source)
        self.assertEqual((self.job_dir / "legacy_blocks.json").read_bytes(), original)

    def test_legacy_omission_marker_becomes_unresolved_instead_of_silent_acceptance(self):
        legacy = [{"type": "table", "text": "A reference table is omitted here.",
                   "source_page": 8}]
        (self.job_dir / "source_blocks.json").unlink()
        visual_review._write(self.job_dir / "blocks.json", {"blocks": legacy})

        payload = visual_review.review_payload(self.job_dir)

        self.assertEqual(payload["unresolved_count"], 1)
        self.assertTrue(payload["items"][0]["visual_kind"].startswith("legacy omitted"))
        self.assertFalse(payload["items"][0]["source_available"])

    def test_corrupt_source_fails_closed_without_overwriting_it(self):
        corrupt = b'{"blocks": '
        (self.job_dir / "source_blocks.json").write_bytes(corrupt)

        with self.assertRaisesRegex(ValueError, "source_blocks.json"):
            visual_review.review_payload(self.job_dir)

        self.assertEqual((self.job_dir / "source_blocks.json").read_bytes(), corrupt)

    def test_empty_visual_cannot_be_kept_as_if_it_had_spoken_text(self):
        empty = [{"type": "visual", "text": "", "visual_kind": "embedded image",
                  "source_page": 3}]
        visual_review._write(self.job_dir / "source_blocks.json",
                             {"blocks": empty, "source_available": True})
        item = visual_review.review_payload(self.job_dir)["items"][0]

        with self.assertRaisesRegex(ValueError, "no extracted text"):
            visual_review.save_decision(
                self.job_dir, item["id"], item["fingerprint"], "keep", ""
            )

        self.assertFalse((self.job_dir / "visual_review.json").exists())

    def test_legacy_code_heading_is_reflagged_with_available_source(self):
        (self.job_dir / "source_blocks.json").unlink()
        visual_review._write(self.job_dir / "blocks.json", {
            "blocks": [{"type": "heading", "text": "[AV12]", "source_page": 6}]
        })

        item = visual_review.review_payload(self.job_dir)["items"][0]

        self.assertEqual(item["original_text"], "[AV12]")
        self.assertEqual(item["visual_kind"], "standalone code")
        self.assertTrue(item["source_available"])
        self.assertNotIn("unavailable", item["suggestion"]["reason"].lower())

    def test_legacy_fragmented_log_is_grouped_without_neighbors(self):
        (self.job_dir / "source_blocks.json").unlink()
        visual_review._write(self.job_dir / "blocks.json", {"blocks": [
            {"type": "heading", "text": "ITERATION ONE", "source_page": 6},
            {"type": "heading", "text": "[AV12]", "source_page": 6},
            {"type": "body", "text": "05:14:24  online", "source_page": 6},
            {"type": "heading", "text": "[BC34]", "source_page": 6},
            {"type": "body", "text": "05:14:25  stable", "source_page": 6},
            {"type": "body", "text": '\u201cWe continue,\u201d Mina said.', "source_page": 6},
        ]})

        source, items, _decisions = visual_review.prepare(self.job_dir)

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["visual_kind"], "structured log")
        self.assertIn("[AV12]\n05:14:24  online\n[BC34]\n05:14:25  stable",
                      items[0]["original_text"])
        self.assertEqual(source[0]["text"], "ITERATION ONE")
        self.assertEqual(source[-1]["text"], '\u201cWe continue,\u201d Mina said.')


class VisualReviewCacheAndGateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.jobs_dir = Path(self.temp.name) / "jobs"
        self.jobs_dir.mkdir()
        self.job_id = "22222222-2222-2222-2222-222222222222"
        self.job_dir = self.jobs_dir / self.job_id
        self.job_dir.mkdir()
        self.voice = self.job_dir / "voice.wav"
        self.voice.write_bytes(b"synthetic voice")
        self.state = {
            "id": self.job_id, "title": "Synthetic", "status": "review_required",
            "path": "A", "voice": "Synthetic", "format": "wav", "engine": "batched",
            "pdf_path": str(self.job_dir / "missing.pdf"),
        }
        (self.job_dir / "state.json").write_text(json.dumps(self.state), encoding="utf-8")
        self.source = [
            {"type": "body", "text": "Opening prose.", "source_page": 1},
            {"type": "visual", "text": "A value moves from 1 to 4.",
             "visual_kind": "chart", "source_page": 1},
            {"type": "body", "text": "Closing prose.", "source_page": 1},
        ]
        visual_review._write(self.job_dir / "source_blocks.json",
                             {"blocks": self.source, "source_available": True})
        visual_review._write(self.job_dir / "blocks.json", {"blocks": self.source})
        self.jobs_patch = mock.patch.object(server, "JOBS_DIR", self.jobs_dir)
        self.voice_patch = mock.patch.object(server, "voice_wav_path", return_value=str(self.voice))
        self.jobs_patch.start()
        server._queue.clear()
        self.voice_patch.start()

    def tearDown(self):
        server._queue.clear()
        self.voice_patch.stop()
        self.jobs_patch.stop()
        self.temp.cleanup()

    def decide(self, decision="keep", spoken_text=""):
        item = visual_review.review_payload(self.job_dir)["items"][0]
        visual_review.save_decision(
            self.job_dir, item["id"], item["fingerprint"], decision, spoken_text
        )
        self.assertTrue(visual_review.write_projection(self.job_dir))

    def test_unresolved_visual_blocks_every_narration_entry_before_worker_setup(self):
        with mock.patch.object(server, "extract_book_meta") as metadata:
            with self.assertRaises(server._ReviewRequired):
                server.run_narration(dict(self.state))
        metadata.assert_not_called()

        held = server._hold_for_visual_review(dict(self.state))
        self.assertTrue(held)
        self.assertEqual(server.load_state(self.job_id)["status"], "review_required")

    def test_resolved_visual_without_full_preview_still_blocks_direct_narration(self):
        self.decide("describe", "The value rises from one to four.")
        with mock.patch.object(server, "extract_book_meta") as metadata:
            with self.assertRaises(server._ReviewRequired):
                server.run_narration(dict(self.state))
        metadata.assert_not_called()

    def test_all_skipped_projection_blocks_direct_narration_before_worker_setup(self):
        visual_review._write(self.job_dir / "source_blocks.json", {
            "blocks": [self.source[1]], "source_available": True,
        })
        item = visual_review.review_payload(self.job_dir)["items"][0]
        visual_review.save_decision(
            self.job_dir, item["id"], item["fingerprint"], "skip", ""
        )
        state = dict(self.state, review_previewed_hash=server._review_signature([]))

        with mock.patch.object(server, "extract_book_meta") as metadata:
            with self.assertRaisesRegex(server._ReviewRequired, "No spoken text"):
                server.run_narration(state)
        metadata.assert_not_called()

    def test_same_spoken_projection_preserves_segments_but_edit_clears_them(self):
        self.decide("keep")
        segments = self.job_dir / "segments"
        segments.mkdir()
        segment = segments / "seg_000000.wav"
        segment.write_bytes(b"validated")
        server.ensure_segments_fresh(self.job_dir, self.state)
        first_hash = (self.job_dir / "plan_hash.txt").read_text(encoding="utf-8")

        self.decide("describe", self.source[1]["text"])
        server.ensure_segments_fresh(self.job_dir, self.state)
        self.assertTrue(segment.exists())
        self.assertEqual((self.job_dir / "plan_hash.txt").read_text(encoding="utf-8"), first_hash)

        self.decide("describe", "The value increases by three.")
        with mock.patch.object(server, "log_line"):
            server.ensure_segments_fresh(self.job_dir, self.state)
        self.assertFalse(segment.exists())

    def test_worker_loop_holds_visual_job_and_advances_to_next_job(self):
        prose_id = "44444444-4444-4444-4444-444444444444"
        prose_dir = self.jobs_dir / prose_id
        prose_dir.mkdir()
        prose_state = dict(self.state, id=prose_id, title="Synthetic Prose", status="queued")
        (prose_dir / "state.json").write_text(json.dumps(prose_state), encoding="utf-8")
        visual_review._write(prose_dir / "blocks.json", {
            "blocks": [{"type": "body", "text": "Narratable prose."}]
        })
        visual_state = server.load_state(self.job_id)
        visual_state["status"] = "queued"
        server.save_state(visual_state)

        class QueueDrained(Exception):
            pass

        class FiniteCondition:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def wait(self):
                raise QueueDrained()

        narrated = []

        def narrate(st):
            narrated.append(st["id"])
            out = self.jobs_dir / st["id"] / "output"
            out.mkdir(exist_ok=True)
            (out / "synthetic.wav").write_bytes(b"RIFF synthetic")
            return st

        server._queue[:] = [self.job_id, prose_id]
        with mock.patch.object(server, "_queue_cv", FiniteCondition()), \
             mock.patch.object(server, "run_narration", side_effect=narrate), \
             mock.patch.object(server, "AUDIOBOOKS_DIR", Path(self.temp.name) / "audiobooks"), \
             mock.patch.object(server, "archive_completed_pdf", return_value=(None, None)), \
             mock.patch.object(server, "log_line"):
            with self.assertRaises(QueueDrained):
                server.worker_loop()

        self.assertEqual(narrated, [prose_id])
        self.assertEqual(server.load_state(self.job_id)["status"], "review_required")
        self.assertEqual(server.load_state(prose_id)["status"], "done")
        self.assertEqual(_blocks(self.job_dir / "source_blocks.json"), self.source)

    def test_decision_file_ahead_of_projection_still_marks_narration_stale(self):
        self.decide("keep")
        server._record_narrated_signature(self.state)
        item = visual_review.review_payload(self.job_dir)["items"][0]
        visual_review.save_decision(
            self.job_dir, item["id"], item["fingerprint"], "describe",
            "The value rises from one to four.",
        )

        self.assertTrue(server._narration_is_stale(self.state))

    def test_corrupt_narrated_signature_fails_closed(self):
        (self.job_dir / "narrated_projection_hash.txt").write_text(
            '{"signature":', encoding="utf-8"
        )

        self.assertTrue(server._narration_is_stale(self.state))


class VisualReviewHttpLifecycleTests(unittest.TestCase):
    def setUp(self):
        server._queue.clear()
        self.temp = tempfile.TemporaryDirectory()
        self.jobs_dir = Path(self.temp.name) / "jobs"
        self.jobs_dir.mkdir()
        self.job_id = "33333333-3333-3333-3333-333333333333"
        self.job_dir = self.jobs_dir / self.job_id
        self.job_dir.mkdir()
        self.state = {
            "id": self.job_id, "title": "Synthetic HTTP", "status": "review_required",
            "path": "A", "voice": "Synthetic", "pdf_path": "missing.pdf",
        }
        source = [
            {"type": "body", "text": "Before.", "source_page": 2},
            {"type": "visual", "text": "Chart values: 2, 5, 9.",
             "visual_kind": "chart", "source_page": 2},
            {"type": "body", "text": "After.", "source_page": 2},
        ]
        (self.job_dir / "state.json").write_text(json.dumps(self.state), encoding="utf-8")
        visual_review._write(self.job_dir / "source_blocks.json",
                             {"blocks": source, "source_available": True})
        visual_review._write(self.job_dir / "blocks.json", {"blocks": source})
        self.jobs_patch = mock.patch.object(server, "JOBS_DIR", self.jobs_dir)
        self.jobs_patch.start()
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.httpd.server_port}"

    def tearDown(self):
        server._queue.clear()
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=5)
        self.jobs_patch.stop()
        self.temp.cleanup()

    def request(self, method, suffix, body=None):
        data = json.dumps(body).encode("utf-8") if body is not None else None
        request = urllib.request.Request(
            self.base + f"/api/jobs/{self.job_id}/visual-review" + suffix,
            data=data, method=method, headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=5) as response:
            return json.load(response)

    def test_http_decision_preview_and_start_drive_persisted_job_lifecycle(self):
        review = self.request("GET", "")
        item = review["items"][0]
        saved = self.request("POST", "/" + item["id"], {
            "fingerprint": item["fingerprint"], "decision": "describe",
            "spoken_text": "The values rise from two to nine.",
        })
        self.assertEqual(saved["unresolved_count"], 0)
        self.assertEqual(server.load_state(self.job_id)["status"], "review_required")

        with self.assertRaises(urllib.error.HTTPError) as blocked:
            self.request("POST", "/start", {})
        self.assertEqual(blocked.exception.code, 409)

        preview = self.request("GET", "/preview")
        self.assertEqual(preview["unresolved_count"], 0)
        self.assertEqual(preview["text"], "Before.\n\nThe values rise from two to nine.\n\nAfter.")
        server.request_cancel(self.job_id)
        canceled = server.load_state(self.job_id)
        self.assertEqual(canceled["status"], "canceled")
        self.assertEqual(self.request("GET", "")["items"][0]["decision"], "describe")
        self.assertIn(self.job_id, server._cancel_flags)
        with mock.patch.object(server, "enqueue") as enqueue:
            self.request("POST", "/start", {})
        enqueue.assert_called_once_with(self.job_id)
        persisted = server.load_state(self.job_id)
        self.assertEqual(persisted["status"], "queued")
        self.assertEqual(persisted["visual_review_unresolved"], 0)
        self.assertNotIn("error", persisted)
        self.assertNotIn(self.job_id, server._cancel_flags)

    def test_queued_job_rejects_edit_without_changing_decision_or_projection(self):
        item = self.request("GET", "")["items"][0]
        state = server.load_state(self.job_id)
        state["status"] = "queued"
        server.save_state(state)
        before_blocks = (self.job_dir / "blocks.json").read_bytes()

        with self.assertRaises(urllib.error.HTTPError) as blocked:
            self.request("POST", "/" + item["id"], {
                "fingerprint": item["fingerprint"], "decision": "skip", "spoken_text": "",
            })

        self.assertEqual(blocked.exception.code, 409)
        self.assertFalse((self.job_dir / "visual_review.json").exists())
        self.assertEqual((self.job_dir / "blocks.json").read_bytes(), before_blocks)

    def test_resume_holds_state_lock_through_save_and_enqueue(self):
        state = server.load_state(self.job_id)
        state["status"] = "failed"
        server.save_state(state)
        lock = threading.RLock()
        observed = []

        def enqueue(job_id):
            observed.append((job_id, lock._is_owned()))

        request = urllib.request.Request(
            self.base + f"/api/jobs/{self.job_id}/resume", data=b"{}", method="POST",
            headers={"Content-Type": "application/json"},
        )
        with mock.patch.object(server, "_STATE_LOCK", lock), \
             mock.patch.object(server, "enqueue", side_effect=enqueue):
            with urllib.request.urlopen(request, timeout=5) as response:
                self.assertTrue(json.load(response)["ok"])

        self.assertEqual(observed, [(self.job_id, True)])
        self.assertEqual(server.load_state(self.job_id)["status"], "queued")

    def test_missing_source_pdf_returns_honest_page_preview_404(self):
        item = self.request("GET", "")["items"][0]
        self.assertIsNone(item["preview_url"])
        with self.assertRaises(urllib.error.HTTPError) as missing:
            self.request("GET", f"/{item['id']}/page-preview")
        self.assertEqual(missing.exception.code, 404)

    def test_direct_audio_route_rejects_output_after_spoken_review_edit(self):
        output = self.job_dir / "output"
        output.mkdir()
        (output / "old.mp3").write_bytes(b"stale audio")
        state = server.load_state(self.job_id)
        state["status"] = "done"
        server.save_state(state)
        item = self.request("GET", "")["items"][0]
        self.request("POST", "/" + item["id"], {
            "fingerprint": item["fingerprint"], "decision": "describe",
            "spoken_text": "A changed spoken description.",
        })
        request = urllib.request.Request(
            self.base + f"/api/jobs/{self.job_id}/audio/old.mp3", method="GET"
        )

        with self.assertRaises(urllib.error.HTTPError) as stale:
            urllib.request.urlopen(request, timeout=5)

        self.assertIn(stale.exception.code, (404, 409))

    def test_reviewed_start_runs_through_worker_loop_and_clears_stale_output(self):
        item = self.request("GET", "")["items"][0]
        self.request("POST", "/" + item["id"], {
            "fingerprint": item["fingerprint"], "decision": "describe",
            "spoken_text": "The chart rises from two to nine.",
        })
        self.request("GET", "/preview")
        self.request("POST", "/start", {})
        self.assertEqual(server._queue, [self.job_id])

        class QueueDrained(Exception):
            pass

        class FiniteCondition:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def wait(self):
                raise QueueDrained()

        narrated = []

        def narrate(st):
            narrated.extend(_blocks(self.job_dir / "blocks.json"))
            out = self.job_dir / "output"
            out.mkdir(exist_ok=True)
            (out / "current.wav").write_bytes(b"RIFF current")
            return st

        state = server.load_state(self.job_id)
        state["narration_stale"] = True
        server.save_state(state)
        with mock.patch.object(server, "_queue_cv", FiniteCondition()), \
             mock.patch.object(server, "run_narration", side_effect=narrate), \
             mock.patch.object(server, "AUDIOBOOKS_DIR", Path(self.temp.name) / "audiobooks"), \
             mock.patch.object(server, "archive_completed_pdf", return_value=(None, None)), \
             mock.patch.object(server, "log_line"):
            with self.assertRaises(QueueDrained):
                server.worker_loop()

        self.assertEqual([block["text"] for block in narrated],
                         ["Before.", "The chart rises from two to nine.", "After."])
        completed = server.load_state(self.job_id)
        self.assertEqual(completed["status"], "done")
        self.assertNotIn("narration_stale", completed)
        self.assertEqual(server.job_detail(self.job_id)["outputs"][0]["name"], "current.wav")


class ExtractionBoundaryIntegrationTests(unittest.TestCase):
    def test_fragmented_log_group_does_not_swallow_heading_quote_or_prose(self):
        raw = """SYSTEM STATUS
[AV12]
05:14:24  online
[BC34]
05:14:25  stable
\"The system is ready,\" I said.
Ordinary prose continues here without numeric structure."""
        blocks = pt.tag_blocks(raw)
        visuals = [block for block in blocks if block["type"] == "visual"]

        self.assertEqual(len(visuals), 1)
        self.assertIn("[AV12]", visuals[0]["text"])
        self.assertIn("05:14:25", visuals[0]["text"])
        spoken = [block["text"] for block in blocks if block["type"] != "visual"]
        self.assertEqual(spoken, ["SYSTEM STATUS", '\"The system is ready,\" I said.',
                                  "Ordinary prose continues here without numeric structure."])

    def test_numeric_prose_sentence_is_not_misclassified_as_visual(self):
        sentence = "In 2024, revenue rose 12 percent while the team expanded into three regions."
        self.assertEqual(pt.tag_blocks(sentence), [{"type": "body", "text": sentence}])


class NarrationPlanIntegrationTests(unittest.TestCase):
    def test_projected_visual_description_reaches_real_build_plan_in_order(self):
        stubs = {
            "numpy": types.ModuleType("numpy"),
            "soundfile": types.ModuleType("soundfile"),
            "torch": types.ModuleType("torch"),
            "perth": types.ModuleType("perth"),
            "chatterbox": types.ModuleType("chatterbox"),
            "chatterbox.tts": types.ModuleType("chatterbox.tts"),
        }
        stubs["perth"].PerthImplicitWatermarker = object
        stubs["chatterbox.tts"].ChatterboxTTS = object
        stubs["chatterbox.tts"].punc_norm = lambda text: text
        with mock.patch.dict(sys.modules, stubs):
            sys.modules.pop("narrate_worker", None)
            worker = importlib.import_module("narrate_worker")
            blocks = [
                {"type": "body", "text": "Opening prose."},
                {"type": "body", "text": "The value increases by three."},
                {"type": "dialogue", "text": "\u201cClosing words.\u201d"},
            ]
            plan = worker.build_plan(blocks, worker.PAUSE_PROFILES["A"])
        sys.modules.pop("narrate_worker", None)
        spoken = [chunk["text"] for chunk in plan]
        self.assertEqual(spoken, ["Opening prose.", "The value increases by three.",
                                  "\u201cClosing words.\u201d"])


if __name__ == "__main__":
    unittest.main()
