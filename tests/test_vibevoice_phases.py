import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
try:
    import numpy as np
    import soundfile as sf
    import vibevoice_phases as phases
    import vibevoice_worker as w
except ModuleNotFoundError:
    phases = None


@unittest.skipUnless(phases is not None, "requires narration runtime dependencies")
class PhasedNarrationTests(unittest.TestCase):
    def setUp(self):
        root = Path(__file__).resolve().parents[1] / ".test-tmp"
        root.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=root)
        self.addCleanup(self.temp.cleanup)
        self.job = Path(self.temp.name)
        texts = ["The careful keeper placed the silver lantern beside the wooden door before walking home.",
                 "A quiet traveller carried the blue notebook through the forest and reached the village safely."]
        self.plan = {"passages": [{"index": i, "identity": f"parent-{i}", "text": text,
                                  "text_sha256": hashlib.sha256(text.encode()).hexdigest()}
                                 for i, text in enumerate(texts)]}
        self.config = {"workflow": phases.WORKFLOW, "quality_max_retries": 2}
        w._write_json(self.job / "vibevoice_config.json", self.config)
        w._write_json(self.job / "vibevoice_plan.json", self.plan)
        self.events = []
        self.bad = set()
        self.always_bad = False
        for target, value in [("load_plan", (self.plan, self.config))]:
            patch = mock.patch.object(w, target, return_value=value)
            patch.start()
            self.addCleanup(patch.stop)
        patch = mock.patch.object(phases, "parakeet_setup_error", return_value=None)
        patch.start()
        self.addCleanup(patch.stop)

    def phase(self, job, config, phase):
        rows = phases._phase_rows(job, self.plan, config, "render" if phase == "render" else "ready")
        self.events.append((phase, [row["unit"]["index"] for row in rows]))
        for row in rows:
            if phase == "render":
                pcm = np.sin(np.arange(24001) * 0.07).astype(np.float32) * 0.1
                sf.write(row["audio"], pcm, 24000, subtype="PCM_16")
                row.update(status="ready", audio_sha256=w.sha256_file(row["audio"]))
            else:
                unit = row["unit"]
                fail = unit["index"] in self.bad and (self.always_bad or row["attempt"] == 1)
                text = "This entirely unrelated speech contains none of the expected passage." if fail else unit["text"]
                report = job / w.SEGMENTS_DIR / phases.PENDING_DIR / f"report_{unit['index']}_{row['attempt']}.json"
                w._write_json(report, {"transcript": text})
                row.update(status="checked", report=str(report))
            phases._save(job, row)

    def run_worker(self):
        with mock.patch.object(phases, "_run_phase", side_effect=self.phase):
            phases.run_generate(self.job)

    def test_generates_all_parents_before_checking_and_repairs_only_failed_clip(self):
        self.bad.add(0)
        self.run_worker()
        self.assertEqual(self.events, [("render", [0, 10000]), ("check", [0, 10000]),
                                      ("render", [0]), ("check", [0])])
        for parent in self.plan["passages"]:
            self.assertTrue(w._valid_segment(self.job / w.SEGMENTS_DIR, parent))
        saved = w._receipt_path(self.job / w.SEGMENTS_DIR / w.UNITS_DIR, 10000)
        self.assertEqual(json.loads(saved.read_text())["attempt"], 1)

    def test_llm_equivalence_survives_parent_gate_resume_and_retains_raw_transcript(self):
        from test_transcript_review import receipt
        self.config["transcript_review"] = True
        source = "In 1999 and 1987 the keeper visited the village."
        heard = "In nineteen ninety nine and nineteen eighty seven the keeper visited the village."
        self.plan["passages"][0]["text"] = source
        self.plan["passages"][0]["text_sha256"] = hashlib.sha256(source.encode()).hexdigest()
        self.bad.add(10000)
        def phase(job, config, name):
            self.phase(job, config, name)
            if name == "check":
                for row in phases._phase_rows(job, self.plan, config, "checked"):
                    if row["unit"]["index"] == 0:
                        w._write_json(Path(row["report"]), {"transcript": heard})
        def adjudicate(expected, transcript):
            return receipt(expected, transcript, "equivalent" if transcript == heard else "error")
        with mock.patch("transcript_review.Reviewer") as reviewer, mock.patch.object(w, "_assert_no_ocr"), \
                mock.patch.object(phases, "_run_phase", side_effect=phase):
            reviewer.return_value.__enter__.return_value.review.side_effect = adjudicate
            phases.run_generate(self.job)
        self.assertEqual(self.events, [("render", [0, 10000]), ("check", [0, 10000]),
                                      ("render", [10000]), ("check", [10000])])
        folder = self.job / w.SEGMENTS_DIR / w.UNITS_DIR
        unit = w._units_for_parent(self.plan["passages"][0], self.config)[0]
        self.assertTrue(w._valid_unit(folder, unit))
        report = w._unit_report(folder, unit)
        self.assertEqual(report["transcript"], heard)
        self.assertEqual(report["comparison_transcript"], source)
        saved = json.loads(w._receipt_path(folder, unit["index"]).read_text())
        self.assertNotIn("listening_approval", saved)
        baseline = {p: w.sha256_file(p) for p in (self.job / w.SEGMENTS_DIR).rglob("*") if p.is_file()}
        self.events.clear()
        self.run_worker()
        self.assertEqual(self.events, [])
        self.assertEqual(baseline, {p: w.sha256_file(p) for p in baseline})

    def test_uncertain_review_retains_audio_for_listening_without_blind_regeneration(self):
        from test_transcript_review import receipt
        self.config["transcript_review"] = True
        self.bad.add(0)
        with mock.patch("transcript_review.Reviewer") as reviewer, mock.patch.object(w, "_assert_no_ocr"):
            reviewer.return_value.__enter__.return_value.review.side_effect = (
                lambda expected, heard: receipt(expected, heard, "uncertain"))
            with self.assertRaises(w.narration_review.ListeningRequired):
                self.run_worker()
        self.assertEqual(self.events, [("render", [0, 10000]), ("check", [0, 10000])])
        detail = w.narration_review.detail(self.job)
        self.assertEqual(detail["unresolved_count"], 1)
        self.assertEqual(detail["items"][0]["transcript_review"]["decision"], "uncertain")

    def test_failed_llm_call_keeps_checked_audio_and_resume_needs_no_render_or_asr(self):
        from test_transcript_review import receipt
        self.config["transcript_review"] = True
        self.bad.add(0)
        with mock.patch("transcript_review.Reviewer") as reviewer, mock.patch.object(w, "_assert_no_ocr"):
            reviewer.return_value.__enter__.return_value.review.side_effect = TimeoutError("review timeout")
            with self.assertRaises(TimeoutError):
                self.run_worker()
            rows = phases._phase_rows(self.job, self.plan, self.config, "checked")
            hashes = {r["audio"]: w.sha256_file(r["audio"]) for r in rows}
            self.assertEqual(len(rows), 2)
            self.events.clear()
            reviewer.return_value.__enter__.return_value.review.side_effect = (
                lambda expected, heard: receipt(expected, heard, "uncertain"))
            with self.assertRaises(w.narration_review.ListeningRequired):
                self.run_worker()
            self.assertEqual(self.events, [])
            for row in rows:
                target = w.narration_review.CANDIDATES_DIR if row["unit"]["index"] == 0 else w.UNITS_DIR
                self.assertEqual(w.sha256_file(self.job / w.SEGMENTS_DIR / target / Path(row["audio"]).name), hashes[row["audio"]])

    def test_checker_failure_resumes_saved_audio_without_generation(self):
        def interrupted(job, config, phase):
            if phase == "check":
                raise RuntimeError("checker interrupted")
            self.phase(job, config, phase)
        with mock.patch.object(phases, "_run_phase", side_effect=interrupted), self.assertRaisesRegex(RuntimeError, "interrupted"):
            phases.run_generate(self.job)
        paths = list((self.job / w.SEGMENTS_DIR / phases.PENDING_DIR).glob("*.wav"))
        hashes = {p.name: w.sha256_file(p) for p in paths}
        self.events.clear()
        self.run_worker()
        self.assertEqual(self.events, [("check", [0, 10000])])
        for name, checksum in hashes.items():
            self.assertEqual(w.sha256_file(self.job / w.SEGMENTS_DIR / w.UNITS_DIR / name), checksum)

    def test_exhausted_clip_goes_to_review_while_other_parent_finishes(self):
        self.bad.add(0)
        self.always_bad = True
        with self.assertRaises(w.narration_review.ListeningRequired):
            self.run_worker()
        self.assertEqual(len(self.events), 6)
        self.assertTrue(w._valid_segment(self.job / w.SEGMENTS_DIR, self.plan["passages"][1]))
        self.assertFalse(w._valid_segment(self.job / w.SEGMENTS_DIR, self.plan["passages"][0]))
        self.assertEqual(w.narration_review.detail(self.job)["unresolved_count"], 1)
        self.events.clear()
        with self.assertRaises(w.narration_review.ListeningRequired):
            self.run_worker()
        self.assertEqual(self.events, [])

    def test_parent_gate_schedules_a_later_repair_round(self):
        original = w.parent_quality
        def aggregate(parent, reports, units=None):
            result = original(parent, reports, units=units)
            if parent["index"] == 0 and len(self.events) < 4:
                result["ok"] = False
            return result
        with mock.patch.object(w, "parent_quality", side_effect=aggregate), \
             mock.patch.object(w, "choose_repair_unit", side_effect=lambda units, reports, exclude: units[0]):
            self.run_worker()
        self.assertEqual(self.events[-2:], [("render", [0]), ("check", [0])])

    def test_cached_approved_clip_is_not_replaced_when_peer_is_regenerated(self):
        self.run_worker()
        folder = self.job / w.SEGMENTS_DIR / w.UNITS_DIR
        peer = w._units_for_parent(self.plan["passages"][1], self.config)[0]
        receipt_path = w._receipt_path(folder, peer["index"])
        receipt = phases._read(receipt_path)
        receipt["listening_approval"] = w.narration_review.fingerprint(receipt)
        w._write_json(receipt_path, receipt)
        before = (w.sha256_file(receipt_path), w.sha256_file(w._wav_path(folder, peer["index"])))
        for location in [folder, self.job / w.SEGMENTS_DIR]:
            path = w._receipt_path(location, 0)
            payload = phases._read(path)
            payload["force_regenerate"] = True
            w._write_json(path, payload)
        self.events.clear()
        self.run_worker()
        self.assertEqual(self.events, [("render", [0]), ("check", [0])])
        self.assertEqual(before, (w.sha256_file(receipt_path), w.sha256_file(w._wav_path(folder, peer["index"]))))

    def test_changed_pending_audio_stops_before_checking(self):
        def interrupt(job, config, phase):
            if phase == "render":
                self.phase(job, config, phase)
                first = next((job / w.SEGMENTS_DIR / phases.PENDING_DIR).glob("*.wav"))
                first.write_bytes(b"changed")
            else:
                self.phase(job, config, phase)
        with mock.patch.object(phases, "_run_phase", side_effect=interrupt), self.assertRaisesRegex(RuntimeError, "changed"):
            phases.run_generate(self.job)

    def test_retry_runs_while_another_clip_in_same_passage_is_undecided(self):
        parent = self.plan["passages"][0]
        parent["text"] = " ".join([parent["text"]] * 20)
        parent["text_sha256"] = hashlib.sha256(parent["text"].encode()).hexdigest()
        w._write_json(self.job / "vibevoice_plan.json", self.plan)
        units = w._units_for_parent(parent, self.config)
        self.assertGreaterEqual(len(units), 2)
        selected, peer = units[:2]
        self.bad.update([selected["index"], peer["index"]])
        self.always_bad = True
        with self.assertRaises(w.narration_review.ListeningRequired):
            self.run_worker()
        detail = w.narration_review.detail(self.job)
        selected_item = next(item for item in detail["items"] if item["index"] == selected["index"])
        peer_path = w.narration_review.audio_path(self.job, peer["index"])
        peer_hash = w.sha256_file(peer_path)
        w.narration_review.decide(self.job, selected["index"], selected_item["fingerprint"], "retry")
        self.bad.clear()
        self.events.clear()
        with self.assertRaises(w.narration_review.ListeningRequired):
            self.run_worker()
        self.assertEqual(self.events, [("render", [selected["index"]]), ("check", [selected["index"]])])
        detail = w.narration_review.detail(self.job)
        self.assertEqual([item["index"] for item in detail["items"]], [peer["index"]])
        self.assertEqual(w.sha256_file(peer_path), peer_hash)
        self.assertTrue(w._valid_unit(self.job / w.SEGMENTS_DIR / w.UNITS_DIR, selected))

    def test_cancel_terminates_and_waits_for_owned_gpu_phase(self):
        process = mock.Mock()
        process.poll.return_value = None
        with mock.patch.object(phases.subprocess, "Popen", return_value=process), \
             mock.patch.object(w, "_prepare_voice"), \
             mock.patch.object(phases, "_cancel", side_effect=[None, None, SystemExit(2)]), self.assertRaises(SystemExit):
            phases._run_phase(self.job, {}, "render")
        process.terminate.assert_called_once()
        process.wait.assert_called_once()

    def test_two_worker_assignments_do_not_shift_when_a_peer_finishes(self):
        for folder in [self.job / w.SEGMENTS_DIR, self.job / w.SEGMENTS_DIR / w.UNITS_DIR,
                       self.job / w.SEGMENTS_DIR / phases.PENDING_DIR, self.job / w.REJECTED_DIR]:
            folder.mkdir(exist_ok=True)
        rows = phases._schedule(self.job, self.plan, self.config)
        first = phases._phase_rows(self.job, self.plan, self.config, "render", 0, 2)
        second = phases._phase_rows(self.job, self.plan, self.config, "render", 1, 2)
        self.assertEqual([r["unit"]["index"] for r in first], [0])
        self.assertEqual([r["unit"]["index"] for r in second], [10000])
        rows[0]["status"] = "retry"
        phases._save(self.job, rows[0])
        second_after = phases._phase_rows(self.job, self.plan, self.config, "render", 1, 2)
        self.assertEqual(second_after, second)
        self.assertEqual(phases._phase_rows(self.job, self.plan, self.config, "render", 0, 2), [])

    def test_cancel_terminates_both_render_workers(self):
        processes = [mock.Mock(), mock.Mock()]
        for process in processes:
            process.poll.return_value = None
        with mock.patch.object(phases.subprocess, "Popen", side_effect=processes) as spawn, \
             mock.patch.object(w, "_prepare_voice"), \
             mock.patch.object(phases, "_cancel", side_effect=[None, None, None, SystemExit(2)]), self.assertRaises(SystemExit):
            phases._run_phase(self.job, {"render_workers": 2}, "render")
        self.assertEqual(spawn.call_args_list[0].args[0][-4:], ["--worker", "0", "--workers", "2"])
        self.assertEqual(spawn.call_args_list[1].args[0][-4:], ["--worker", "1", "--workers", "2"])
        for process in processes:
            process.terminate.assert_called_once()
            process.wait.assert_called_once()

    def test_failure_stops_peer_and_prevents_check_phase(self):
        failed, peer = mock.Mock(), mock.Mock()
        failed.poll.return_value = 1
        peer.poll.return_value = None
        with mock.patch.object(phases.subprocess, "Popen", side_effect=[failed, peer]), \
             mock.patch.object(w, "_prepare_voice"), self.assertRaisesRegex(RuntimeError, "render phase failed"):
            phases._run_phase(self.job, {"render_workers": 2}, "render")
        peer.terminate.assert_called_once()
        failed.wait.assert_called_once()
        peer.wait.assert_called_once()


if __name__ == "__main__":
    unittest.main()
