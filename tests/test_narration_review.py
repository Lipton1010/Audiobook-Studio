import json
import math
import struct
import sys
import tempfile
import threading
import types
import unittest
import urllib.error
import urllib.request
import wave
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
import narration_review as review
try:
    import fitz
except ModuleNotFoundError:
    sys.modules.setdefault("fitz", types.ModuleType("fitz"))
import server
from vibevoice_plan import sha256_file
from vibevoice_quality import assess
from vibevoice_units import repair_units


class NarrationReviewTests(unittest.TestCase):
    def test_requested_parent_reassembly_archives_the_prior_audio(self):
        try:
            import vibevoice_worker as worker
        except ModuleNotFoundError:
            self.skipTest('requires isolated narration runtime')
        self.decide(0, 'accept')
        self.decide(1, 'accept')
        segments = self.units_dir.parent
        self.assertTrue(worker._recover_parent_from_units(self.job, self.parent, self.units, self.units_dir, segments))
        path = segments / 'seg_000000.json'
        old_audio = (segments / 'seg_000000.wav').read_bytes()
        saved = json.loads(path.read_text())
        saved['force_regenerate'] = True
        review.write(path, saved)
        self.assertFalse(worker._valid_segment(segments, self.parent))
        self.assertTrue(worker._recover_parent_from_units(self.job, self.parent, self.units, self.units_dir, segments))
        backups = list((self.job / worker.REJECTED_DIR).glob('*_before_requested_update_*.wav'))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_bytes(), old_audio)

    def test_paused_audio_stream_does_not_block_decisions(self):
        http = ThreadingHTTPServer(('127.0.0.1', 0), server.Handler)
        serving = threading.Thread(target=http.serve_forever, daemon=True)
        streaming, release = threading.Event(), threading.Event()
        original = server.Handler._serve_audio
        def paused(handler, path, **kwargs):
            streaming.set()
            release.wait(5)
            original(handler, path, **kwargs)
        base = f'http://127.0.0.1:{http.server_port}/api/jobs/{self.job.name}/audio-review'
        def read_audio():
            with urllib.request.urlopen(base + '/0/audio', timeout=6) as response:
                response.read()
        with mock.patch.object(server, 'JOBS_DIR', self.root), \
             mock.patch.object(server, 'load_state', return_value={'status': 'audio_review_required'}), \
             mock.patch.object(server.Handler, '_serve_audio', paused):
            serving.start()
            reader = threading.Thread(target=read_audio, daemon=True)
            reader.start()
            try:
                self.assertTrue(streaming.wait(2))
                item = review.detail(self.job)['items'][0]
                request = urllib.request.Request(base + '/0', data=json.dumps({
                    'action': 'retry', 'fingerprint': item['fingerprint']}).encode(),
                    headers={'Content-Type': 'application/json'})
                with urllib.request.urlopen(request, timeout=2) as response:
                    self.assertEqual(response.status, 200)
            finally:
                release.set()
                reader.join(6)
                http.shutdown()
                serving.join()
                http.server_close()

    def test_restore_for_listening_preserves_audio_and_requires_new_choice(self):
        before = (self.units_dir / 'seg_000000.wav').read_bytes()
        self.decide(0, 'retry')
        result = self.decide(0, 'listen')
        item = next(item for item in result['items'] if item['index'] == 0)
        self.assertIsNone(item['decision'])
        receipt = json.loads((self.units_dir / 'seg_000000.json').read_text())
        self.assertNotIn('force_regenerate', receipt)
        self.assertTrue(receipt['listen_again'])
        self.assertEqual((self.units_dir / 'seg_000000.wav').read_bytes(), before)
        self.decide(0, 'accept')
        self.assertNotIn('listen_again', json.loads((self.units_dir / 'seg_000000.json').read_text()))

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.job = self.root / "abc-123"
        self.units_dir = self.job / "vibevoice_segments" / "units"
        self.units_dir.mkdir(parents=True)
        self.parent = {"index": 0, "identity": "synthetic-parent", "text_sha256": "synthetic-text",
                       "text": "First synthetic passage stays right here. Second synthetic passage stays right here."}
        self.units = repair_units(self.parent, target_words=6, max_words=6)
        review.write(self.job / "vibevoice_plan.json", {"passages": [self.parent]})
        for unit in self.units:
            stem = self.units_dir / f"seg_{unit['index']:06d}"
            wav = stem.with_suffix(".wav")
            with wave.open(str(wav), "wb") as stream:
                stream.setparams((1, 2, 24000, 0, "NONE", "not compressed"))
                stream.writeframes(b"".join(struct.pack("<h", int(2000 * math.sin(i / 10))) for i in range(4800)))
            report_path = self.job / f"report_{unit['index']}.json"
            heard = "Synthetic unrelated words differ from source."
            report = assess(unit["text"], heard)
            report.update(transcript=heard, unit_identity=unit["identity"], unit_text_sha256=unit["text_sha256"], audio_sha256=sha256_file(wav))
            review.write(report_path, report)
            review.write(stem.with_suffix(".json"), {
                "identity": unit["identity"], "text_sha256": unit["text_sha256"],
                "wav_sha256": sha256_file(wav), "quality_report": str(report_path),
                "report_sha256": sha256_file(report_path), "unit_index": unit["unit_index"],
                "parent_index": 0, "report_identity": unit["identity"],
                "report_wav_sha256": sha256_file(wav), "attempt": 3})
        with self.assertRaises(review.ListeningRequired):
            review.hold(self.job, self.parent, self.units)

    def decide(self, index=0, action="accept"):
        item = review.detail(self.job)["items"][index]
        return review.decide(self.job, item["index"], item["fingerprint"], action)

    def set_transcript(self, index, text):
        path = self.units_dir / f"seg_{index:06d}.json"
        receipt = json.loads(path.read_text())
        report_path = Path(receipt["quality_report"])
        report = json.loads(report_path.read_text())
        report.update(assess(self.units[index]["text"], text), transcript=text)
        review.write(report_path, report)
        receipt["report_sha256"] = sha256_file(report_path)
        review.write(path, receipt)

    def test_review_excludes_passing_peer_but_retains_cumulative_failures(self):
        self.set_transcript(1, self.units[1]["text"].replace("Second", "Another"))
        self.assertEqual([x["index"] for x in review.detail(self.job)["items"]], [0])
        # Individually sub-threshold losses still require review when their
        # combined passage exceeds the unchanged five-word gate.
        for index in range(2):
            self.set_transcript(index, " ".join(self.units[index]["text"].split()[3:]))
        self.assertEqual([x["index"] for x in review.detail(self.job)["items"]], [0, 1])
        self.decide(0)
        self.assertEqual(review.detail(self.job)["unresolved_count"], 0)

    def test_homophone_only_peer_is_hidden_but_owner_listen_again_is_preserved(self):
        self.set_transcript(1, self.units[1]["text"].replace("right here", "write hear"))
        self.assertEqual([item["index"] for item in review.detail(self.job)["items"]], [0])
        path = self.units_dir / "seg_000001.json"
        receipt = json.loads(path.read_text())
        receipt["listen_again"] = True
        review.write(path, receipt)
        items = review.detail(self.job)["items"]
        self.assertEqual([item["index"] for item in items], [0, 1])
        self.assertEqual(items[1]["differences"], [])
        self.assertIsNone(items[1]["decision"])

    def test_reassessment_recovers_candidate_without_fabricating_listening_approval(self):
        try:
            import vibevoice_worker as worker
        except ModuleNotFoundError:
            self.skipTest("requires isolated VibeVoice runtime")
        for index in range(2):
            self.set_transcript(index, self.units[index]["text"])
        pending = self.units_dir.parent / review.CANDIDATES_DIR
        pending.mkdir()
        for suffix in (".wav", ".json"):
            source = self.units_dir / ("seg_000000" + suffix)
            (pending / source.name).write_bytes(source.read_bytes())
        review.record(self.job, self.parent, self.units, [0])
        self.assertEqual(review.detail(self.job)["unresolved_count"], 0)
        before = (pending / "seg_000000.wav").read_bytes()
        self.assertTrue(worker._recover_parent_from_units(self.job, self.parent, self.units, self.units_dir, self.units_dir.parent))
        self.assertEqual((self.units_dir / "seg_000000.wav").read_bytes(), before)
        self.assertNotIn("listening_approval", json.loads((self.units_dir / "seg_000000.json").read_text()))
        self.assertFalse(review.entries(self.job))

    def test_explicit_decisions_preserve_audio_and_reports(self):
        before = {p: p.read_bytes() for p in self.job.rglob("*") if p.suffix in (".wav",) or p.name.startswith("report_")}
        self.assertEqual(review.detail(self.job)["unresolved_count"], 2)
        self.assertEqual(self.decide()["unresolved_count"], 1)
        self.assertEqual(self.decide(1, "retry")["unresolved_count"], 0)
        for path, payload in before.items():
            self.assertEqual(path.read_bytes(), payload)
        receipt = json.loads((self.units_dir / "seg_000000.json").read_text())
        self.assertTrue(review.approved(receipt, self.units[0]))
        receipt["wav_sha256"] = "changed"
        self.assertFalse(review.approved(receipt, self.units[0]))

    def test_stale_decision_audio_report_and_plan_are_rejected(self):
        with self.assertRaises(ValueError):
            review.decide(self.job, 0, "stale", "accept")
        with self.assertRaises(ValueError):
            review.decide(self.job, 999, "stale", "accept")
        wav = self.units_dir / "seg_000000.wav"
        payload = wav.read_bytes()
        wav.write_bytes(payload + b"changed")
        with self.assertRaises(ValueError):
            review.detail(self.job)
        wav.write_bytes(payload)
        plan = self.job / "vibevoice_plan.json"
        review.write(plan, {"passages": [{**self.parent, "text": "Changed source"}]})
        with self.assertRaises(ValueError):
            review.detail(self.job)

    def test_http_review_audio_range_and_resume_gate(self):
        state = {"id": self.job.name, "status": "audio_review_required"}
        http = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        thread = threading.Thread(target=http.serve_forever, daemon=True)
        with mock.patch.object(server, "JOBS_DIR", self.root), \
             mock.patch.object(server, "load_state", return_value=state), \
             mock.patch.object(server, "queue_persisted") as queue:
            thread.start()
            try:
                base = f"http://127.0.0.1:{http.server_port}/api/jobs/{self.job.name}/audio-review"
                def request(suffix="", body=None, headers=None):
                    req = urllib.request.Request(base + suffix, data=None if body is None else json.dumps(body).encode(),
                                                 headers=headers or {"Content-Type": "application/json"})
                    return urllib.request.urlopen(req)
                with request() as response:
                    self.assertEqual(json.load(response)["unresolved_count"], 2)
                with self.assertRaises(urllib.error.HTTPError) as blocked:
                    request("/start", {})
                self.assertEqual(blocked.exception.code, 409)
                queue.assert_not_called()
                with request("/0/audio", headers={"Range": "bytes=0-43"}) as response:
                    self.assertEqual(response.status, 206)
                    self.assertEqual(response.read(), (self.units_dir / "seg_000000.wav").read_bytes()[:44])
                for item in review.detail(self.job)["items"]:
                    with request(f"/{item['index']}", {"fingerprint": item["fingerprint"], "action": "accept"}) as response:
                        self.assertEqual(response.status, 200)
                with request("/start", {}) as response:
                    self.assertEqual(response.status, 200)
                queue.assert_called_once_with(state)
                state["status"] = "narrating"
                with self.assertRaises(urllib.error.HTTPError) as busy:
                    request("/0", {"action": "retry"})
                self.assertEqual(busy.exception.code, 409)
            finally:
                http.shutdown()
                thread.join()
                http.server_close()

    def test_worker_recovery_requires_approval_and_preserves_peers(self):
        try:
            import vibevoice_worker as worker
        except ModuleNotFoundError:
            self.skipTest("requires isolated VibeVoice runtime")
        self.assertFalse(worker._valid_unit(self.units_dir, self.units[0]))
        self.decide()
        self.assertTrue(worker._valid_unit(self.units_dir, self.units[0]))
        first_hash = sha256_file(self.units_dir / "seg_000000.wav")
        self.decide(1, "retry")
        self.assertFalse(worker._valid_unit(self.units_dir, self.units[1], allow_needs_repair=True))
        self.decide(1)
        with mock.patch.object(worker, "_load_model", side_effect=AssertionError("model not needed")):
            self.assertTrue(worker._recover_parent_from_units(self.job, self.parent, self.units, self.units_dir, self.units_dir.parent))
        self.assertEqual(sha256_file(self.units_dir / "seg_000000.wav"), first_hash)
        saved = json.loads((self.units_dir.parent / "seg_000000.json").read_text())
        self.assertTrue(saved["parent_quality"]["ok"])
        self.assertIn("raw_assessment", saved["unit_reports"][0])
        self.assertTrue(worker._valid_segment(self.units_dir.parent, self.parent))

    def test_rejected_candidate_preserves_old_checkpoint_until_listening_acceptance(self):
        try:
            import vibevoice_worker as worker
        except ModuleNotFoundError:
            self.skipTest("requires isolated VibeVoice runtime")
        unit = self.units[0]
        pending = self.units_dir.parent / review.CANDIDATES_DIR
        pending.mkdir()
        old_wav = (self.units_dir / "seg_000000.wav").read_bytes()
        old_receipt = (self.units_dir / "seg_000000.json").read_bytes()
        candidate = self.job / "candidate.wav"
        candidate.write_bytes(old_wav)
        worker._publish_unit(pending, unit, candidate, self.job / "report_0.json", 3)
        with self.assertRaises(review.ListeningRequired):
            review.hold(self.job, self.parent, self.units, [0])
        self.assertFalse(worker._valid_unit(pending, unit))
        self.assertEqual((self.units_dir / "seg_000000.json").read_bytes(), old_receipt)
        self.assertEqual(review.audio_path(self.job, 0).parent, pending)
        self.decide()
        self.decide(1)
        self.assertTrue(worker._valid_unit(pending, unit))
        self.assertTrue(worker._recover_parent_from_units(self.job, self.parent, self.units, self.units_dir, self.units_dir.parent))
        self.assertTrue(worker._valid_unit(self.units_dir, unit))
        archives = list((self.job / worker.REJECTED_DIR).glob("*_before_review_*.json"))
        self.assertEqual(len(archives), 1)
        self.assertEqual(archives[0].read_bytes(), old_receipt)
        self.assertFalse((self.job / review.FILENAME).exists())

    def test_resume_regenerates_only_the_selected_clip(self):
        try:
            import vibevoice_worker as worker
        except ModuleNotFoundError:
            self.skipTest("requires isolated VibeVoice runtime")
        self.decide()
        self.decide(1, "retry")
        peer = self.units_dir / "seg_000000.wav"
        before = peer.read_bytes()
        rendered_indices = []
        def render(_torch, _processor, _model, _voice, items, _config, unit_dir):
            result = []
            for unit, attempt in items:
                rendered_indices.append(unit["index"])
                path = unit_dir / f"seg_{unit['index']:06d}.tmp.wav"
                path.write_bytes(before)
                result.append((unit, attempt, path, None))
            return result
        def check(_checker, _wav, unit, _label):
            path = self.job / "new-report.json"
            review.write(path, {**assess(unit["text"], unit["text"]), "transcript": unit["text"]})
            result = mock.Mock()
            result.wait.return_value = (True, path)
            return result
        with mock.patch.object(worker, "load_plan", return_value=({"passages": [self.parent]}, {})), \
             mock.patch.object(worker, "_units_for_parent", return_value=self.units), \
             mock.patch.object(worker, "_assert_no_ocr"), \
             mock.patch.object(worker, "_prepare_voice"), \
             mock.patch.object(worker, "_load_model", return_value=(object(), object(), object())), \
             mock.patch.object(worker, "_QualityChecker"), \
             mock.patch.object(worker, "_QualityCheck", side_effect=check), \
             mock.patch.object(worker, "_render_items", side_effect=render), \
             mock.patch.object(worker, "_batch_size", return_value=1):
            worker.run_generate(self.job)
        self.assertEqual(rendered_indices, [1])
        self.assertEqual(peer.read_bytes(), before)
        self.assertTrue(worker._valid_segment(self.units_dir.parent, self.parent))
        self.assertEqual(len(list((self.job / worker.REJECTED_DIR).glob("*_before_listening_retry_*.wav"))), 1)

    def test_multiple_flagged_passages_allow_all_later_clips_but_block_assembly(self):
        try:
            import vibevoice_worker as worker
        except ModuleNotFoundError:
            self.skipTest("requires isolated VibeVoice runtime")
        job = self.root / "def-456"
        job.mkdir()
        parents = [{**self.parent, "index": i, "identity": f"parent-{i}",
                    "text": self.parent["text"] + " Third synthetic passage stays right here."} for i in range(3)]
        review.write(job / "vibevoice_plan.json", {"passages": parents})
        sample = (self.units_dir / "seg_000000.wav").read_bytes()
        rendered_indices = []
        def render(_torch, _processor, _model, _voice, items, _config, unit_dir):
            result = []
            for unit, attempt in items:
                rendered_indices.append(unit["index"])
                path = unit_dir / f"seg_{unit['index']:06d}.tmp.wav"
                path.write_bytes(sample)
                result.append((unit, attempt, path, None))
            return result
        def check(_checker, _wav, unit, label):
            failed = unit["parent_index"] < 2 and unit["unit_index"] == 0
            transcript = "Unexpected words replace the entire sentence." if failed else unit["text"]
            path = job / f"report_{unit['index']}_{label}.json"
            report = assess(unit["text"], transcript)
            review.write(path, {**report, "transcript": transcript})
            result = mock.Mock()
            result.wait.return_value = (report["ok"], path)
            return result
        with mock.patch.object(worker, "load_plan", return_value=({"passages": parents}, {
            "quality_max_retries": 0, "quality_workers": 2,
        })), \
             mock.patch.object(worker, "_units_for_parent", side_effect=lambda p, c: repair_units(p, 6, 6)), \
             mock.patch.object(worker, "_assert_no_ocr"), mock.patch.object(worker, "_prepare_voice"), \
             mock.patch.object(worker, "_load_model", return_value=(object(), object(), object())) as model, \
             mock.patch.object(worker, "_QualityChecker"), \
             mock.patch.object(worker, "_QualityCheck", side_effect=check), \
             mock.patch.object(worker, "_render_items", side_effect=render), \
             mock.patch.object(worker, "_batch_size", return_value=2), \
             mock.patch.object(worker, "_cross_parent_enabled", return_value=False):
            with self.assertRaises(review.ListeningRequired):
                worker.run_generate(job)
            self.assertEqual(rendered_indices, [0, 1, 2, 10000, 10001, 10002, 20000, 20001, 20002])
            detail = review.detail(job)
            self.assertEqual(detail["passage_count"], 2)
            self.assertEqual([item["passage"] for item in detail["items"]], [1, 2])
            self.assertTrue(worker._valid_segment(job / worker.SEGMENTS_DIR, parents[2]))
            self.assertFalse(worker._valid_segment(job / worker.SEGMENTS_DIR, parents[0]))
            with mock.patch.object(worker, "assemble") as assemble:
                with self.assertRaises(review.ListeningRequired):
                    worker.run_assemble(job)
                assemble.assert_not_called()
            # A resume without decisions reuses all work, including rejected clips.
            before = list(rendered_indices)
            model.reset_mock()
            with self.assertRaises(review.ListeningRequired):
                worker.run_generate(job)
            model.assert_not_called()
            self.assertEqual(rendered_indices, before)
            # Decisions from both passages coexist and assemble without generation.
            for item in detail["items"]:
                review.decide(job, item["index"], item["fingerprint"], "accept")
            worker.run_generate(job)
            model.assert_not_called()
            self.assertFalse(review.entries(job))
            self.assertTrue(all(worker._valid_segment(job / worker.SEGMENTS_DIR, p) for p in parents))
            with mock.patch.object(worker, "assemble", return_value="synthetic.wav") as assemble:
                worker.run_assemble(job)
                assemble.assert_called_once()
            # Pausing immediately after the first flag keeps it durable, while
            # unfinished peer clips and later passages still run on resume.
            job = self.root / "pause-789"
            job.mkdir()
            review.write(job / "vibevoice_plan.json", {"passages": parents})
            rendered_indices.clear()
            original_record = review.record
            def pause_after_flag(*args):
                original_record(*args)
                raise SystemExit(2)
            with mock.patch.object(review, "record", side_effect=pause_after_flag):
                with self.assertRaises(SystemExit):
                    worker.run_generate(job)
            self.assertEqual(len(review.entries(job)), 1)
            with self.assertRaises(review.ListeningRequired):
                worker.run_generate(job)
            self.assertEqual(rendered_indices.count(0), 1)
            self.assertTrue(worker._valid_segment(job / worker.SEGMENTS_DIR, parents[2]))
            self.assertEqual(review.detail(job)["passage_count"], 2)
