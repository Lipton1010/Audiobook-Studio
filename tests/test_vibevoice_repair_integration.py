import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


APP_DIR = Path(__file__).resolve().parents[1] / "app"
sys.path.insert(0, str(APP_DIR))

try:
    import numpy as np
    import soundfile  # noqa: F401 - worker runtime dependency
    import vibevoice_worker as worker
except ModuleNotFoundError:
    np = None


@unittest.skipUnless(np is not None, "requires the isolated VibeVoice runtime")
class VibeVoiceRepairIntegrationTests(unittest.TestCase):
    def setUp(self):
        test_root = Path(os.environ.get("AUDIOBOOK_TEST_TEMP", Path(__file__).resolve().parents[1] / ".test-tmp"))
        test_root.mkdir(exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(dir=test_root)
        self.job = Path(self.temporary.name)
        self.parent = {
            "index": 4,
            "identity": "parent-identity",
            "text_sha256": "parent-text",
            "text": "First synthetic sentence. Second synthetic sentence.",
            "speaker_text": "Speaker 0: First synthetic sentence. Second synthetic sentence.",
        }
        self.units = [
            {
                "index": 40000 + index,
                "parent_index": 4,
                "unit_index": index,
                "identity": f"unit-{index}",
                "text_sha256": f"text-{index}",
                "text": f"Synthetic unit {index}.",
                "speaker_text": f"Speaker 0: Synthetic unit {index}.",
            }
            for index in range(2)
        ]
        self.reports = {
            unit["index"]: {
                "unit_index": unit["unit_index"],
                "transcript": unit["text"],
                "missing_words": 0,
                "inserted_words": 0,
                "differences": [],
            }
            for unit in self.units
        }
        self.valid = set()
        self.render_attempts = []

    def tearDown(self):
        self.temporary.cleanup()

    def _render(self, _torch, _processor, _model, _voice, items, _config, unit_dir):
        rendered = []
        for unit, attempt in items:
            self.render_attempts.append((unit["unit_index"], attempt))
            path = worker._wav_path(unit_dir, unit["index"]).with_suffix(".test.tmp.wav")
            path.write_bytes(b"synthetic audio")
            rendered.append((unit, attempt, path, None))
        return rendered

    def _publish(self, unit_dir, unit, tmp, _report, attempt):
        tmp.unlink(missing_ok=True)
        self.valid.add(unit["index"])
        worker._write_json(worker._receipt_path(unit_dir, unit["index"]), {
            "attempt": attempt,
            "identity": unit["identity"],
        })

    def _run(self, *, quality=None, aggregate=None, assemble=None, retries=2):
        quality = quality or (lambda *_args: (True, self.job / "quality.json"))
        aggregate = aggregate or (lambda *_args, **_kwargs: {"ok": True})
        assemble = assemble or mock.Mock()

        class ImmediateQuality:
            def __init__(_self, checker, wav, unit, label):
                _self.value = quality(checker, wav, unit, label)
                if _self.value[0] and not _self.value[1].exists():
                    worker._write_json(_self.value[1], {"transcript": unit["text"]})

            def wait(_self, _job, _checker):
                return _self.value

        with mock.patch.object(worker, "load_plan", return_value=({"passages": [self.parent]}, {"quality_max_retries": retries})), \
             mock.patch.object(worker, "_valid_segment", return_value=False), \
             mock.patch.object(worker, "_assert_no_ocr"), \
             mock.patch.object(worker, "_prepare_voice", return_value=object()), \
             mock.patch.object(worker, "_load_model", return_value=(object(), object(), object())), \
             mock.patch.object(worker, "_QualityChecker"), \
             mock.patch.object(worker, "_QualityCheck", ImmediateQuality), \
             mock.patch.object(worker, "_batch_size", return_value=2), \
             mock.patch.object(worker, "repair_units", return_value=self.units), \
             mock.patch.object(worker, "_valid_unit", side_effect=lambda _directory, unit, **_kwargs: unit["index"] in self.valid), \
             mock.patch.object(worker, "_render_items", side_effect=self._render), \
             mock.patch.object(worker, "_quality_check", side_effect=quality), \
             mock.patch.object(worker, "_publish_unit", side_effect=self._publish), \
             mock.patch.object(worker, "_unit_report", side_effect=lambda _directory, unit: self.reports[unit["index"]]), \
             mock.patch.object(worker, "parent_quality", side_effect=aggregate), \
             mock.patch.object(worker, "_assemble_parent_from_units", side_effect=assemble):
            worker.run_generate(self.job)
        return assemble

    def test_stale_invalid_receipt_does_not_consume_new_identity_retry_budget(self):
        unit_dir = self.job / worker.SEGMENTS_DIR / worker.UNITS_DIR
        unit_dir.mkdir(parents=True)
        worker._write_json(worker._receipt_path(unit_dir, self.units[0]["index"]), {
            "attempt": 3,
            "identity": "stale-identity",
            "needs_repair": True,
        })
        worker._write_json(worker._receipt_path(unit_dir, self.units[1]["index"]), {
            "attempt": 1,
            "identity": self.units[1]["identity"],
        })
        self.valid.add(self.units[1]["index"])

        self._run()

        self.assertEqual(self.render_attempts, [(0, 1)])

    def test_parent_repair_uses_remaining_retries_after_one_rejection(self):
        self.reports[self.units[0]["index"]].update(
            missing_words=2, differences=[{"kind": "delete", "expected": ["two", "words"], "heard": []}]
        )
        aggregate_results = iter([{"ok": False}, {"ok": True}])
        quality_calls = {0: 0}

        def quality(_checker, _wav, unit, _label):
            quality_calls[unit["unit_index"]] = quality_calls.get(unit["unit_index"], 0) + 1
            if unit["unit_index"] == 0 and quality_calls[0] == 2:
                return False, self.job / "rejected.json"
            return True, self.job / "accepted.json"

        self._run(quality=quality, aggregate=lambda *_args, **_kwargs: next(aggregate_results))

        self.assertEqual([attempt for index, attempt in self.render_attempts if index == 0], [1, 2, 3])

    def test_failed_parent_gate_never_publishes_parent_receipt(self):
        self.reports[self.units[0]["index"]].update(
            missing_words=2, differences=[{"kind": "delete", "expected": ["two", "words"], "heard": []}]
        )
        assemble = mock.Mock()
        with self.assertRaisesRegex(RuntimeError, "parent quality failed"):
            self._run(aggregate=lambda *_args, **_kwargs: {"ok": False}, assemble=assemble)

        assemble.assert_not_called()
        receipt = self.job / worker.SEGMENTS_DIR / "seg_000004.json"
        self.assertFalse(receipt.exists())

    def test_terminal_first_row_still_preserves_accepted_peer(self):
        def quality(_checker, _wav, unit, _label):
            return unit["unit_index"] != 0, self.job / f"quality-{unit['unit_index']}.json"

        with self.assertRaisesRegex(RuntimeError, "major ASR coverage error"):
            self._run(quality=quality, retries=0)

        self.assertNotIn(self.units[0]["index"], self.valid)
        self.assertIn(self.units[1]["index"], self.valid)
        self.assertFalse((self.job / worker.SEGMENTS_DIR / "seg_000004.json").exists())

    def test_prefetched_batch_is_drained_before_requeued_row(self):
        third = {
            "index": 40002, "parent_index": 4, "unit_index": 2,
            "identity": "unit-2", "text_sha256": "text-2",
            "text": "Synthetic unit 2.", "speaker_text": "Speaker 0: Synthetic unit 2.",
        }
        self.units.append(third)
        self.reports[third["index"]] = {
            "unit_index": 2, "transcript": third["text"], "missing_words": 0,
            "inserted_words": 0, "differences": [],
        }
        seen = {}

        def quality(_checker, _wav, unit, _label):
            seen[unit["unit_index"]] = seen.get(unit["unit_index"], 0) + 1
            ok = not (unit["unit_index"] == 1 and seen[1] == 1)
            return ok, self.job / f"quality-{unit['unit_index']}-{seen[unit['unit_index']]}.json"

        self._run(quality=quality)

        self.assertEqual(self.render_attempts, [(0, 1), (1, 1), (2, 1), (1, 2)])
        self.assertEqual(self.valid, {unit["index"] for unit in self.units})

    def test_cross_parent_prefetch_renders_while_prior_quality_waits(self):
        second_parent = {
            "index": 5, "identity": "parent-2", "text_sha256": "parent-text-2",
            "text": "Second synthetic sentence.", "speaker_text": "Speaker 0: Second synthetic sentence.",
        }
        second_unit = {
            "index": 50000, "parent_index": 5, "unit_index": 0,
            "identity": "unit-2", "text_sha256": "text-2", "text": "Second synthetic unit.",
            "speaker_text": "Speaker 0: Second synthetic unit.",
        }
        first_units = list(self.units)
        events, reports = [], {}

        def render(_torch, _processor, _model, _voice, items, _config, unit_dir):
            rows = []
            for unit, attempt in items:
                events.append(("render", unit["parent_index"], unit["unit_index"]))
                tmp = worker._wav_path(unit_dir, unit["index"]).with_suffix(f".{unit['index']}.tmp.wav")
                tmp.write_bytes(b"synthetic")
                rows.append((unit, attempt, tmp, None))
            return rows

        class BarrierQuality:
            def __init__(_self, _checker, _wav, unit, _label):
                _self.unit = unit
                report = self.job / f"quality-{unit['index']}.json"
                worker._write_json(report, {"transcript": unit["text"]})
                _self.value = (True, report)
                events.append(("quality_start", unit["parent_index"], unit["unit_index"]))

            def wait(_self, _job, _checker):
                events.append(("quality_wait", _self.unit["parent_index"], _self.unit["unit_index"]))
                if _self.unit["parent_index"] == 4 and _self.unit["unit_index"] == 1:
                    self.assertIn(("render", 5, 0), events)
                return _self.value

        units_by_parent = {4: first_units, 5: [second_unit]}

        def publish(unit_dir, unit, tmp, _report, attempt):
            tmp.unlink(missing_ok=True)
            self.valid.add(unit["index"])
            worker._write_json(worker._receipt_path(unit_dir, unit["index"]), {
                "attempt": attempt, "identity": unit["identity"],
            })

        with mock.patch.object(worker, "load_plan", return_value=({"passages": [self.parent, second_parent]}, {
            "quality_max_retries": 1, "cross_parent_render_ahead": True,
        })), \
             mock.patch.object(worker, "_valid_segment", return_value=False), \
             mock.patch.object(worker, "_assert_no_ocr"), \
             mock.patch.object(worker, "_prepare_voice", return_value=object()), \
             mock.patch.object(worker, "_load_model", return_value=(object(), object(), object())), \
             mock.patch.object(worker, "_QualityChecker"), \
             mock.patch.object(worker, "_QualityCheck", BarrierQuality), \
             mock.patch.object(worker, "_batch_size", return_value=2), \
             mock.patch.object(worker, "repair_units", side_effect=lambda parent: units_by_parent[parent["index"]]), \
             mock.patch.object(worker, "_valid_unit", side_effect=lambda _directory, unit, **_kwargs: unit["index"] in self.valid), \
             mock.patch.object(worker, "_render_items", side_effect=render), \
             mock.patch.object(worker, "_prefetch_within_limits", return_value=(True, {"seconds": 1.0, "bytes": 9})), \
             mock.patch.object(worker, "_publish_unit", side_effect=publish), \
             mock.patch.object(worker, "_unit_report", side_effect=lambda _directory, unit: {
                 "unit_index": unit["unit_index"], "transcript": unit["text"], "missing_words": 0,
                 "inserted_words": 0, "differences": [],
             }), \
             mock.patch.object(worker, "parent_quality", return_value={"ok": True}), \
             mock.patch.object(worker, "_assemble_parent_from_units"):
            worker.run_generate(self.job)

        self.assertLess(events.index(("quality_start", 4, 1)), events.index(("render", 5, 0)))
        self.assertLess(events.index(("render", 5, 0)), events.index(("quality_wait", 4, 1)))
        self.assertEqual(self.valid, {unit["index"] for unit in first_units} | {second_unit["index"]})

    def test_overlap_telemetry_is_opt_in_and_best_effort(self):
        path = self.job / worker.OVERLAP_TELEMETRY_FILE
        worker._overlap_telemetry(self.job, {}, "render_start", [4], [40000])
        self.assertFalse(path.exists())
        with mock.patch.object(Path, "open", side_effect=OSError("private telemetry unavailable")):
            worker._overlap_telemetry(self.job, {"performance_telemetry": True}, "render_start", [4], [40000])
        self.assertFalse(path.exists())

    def test_overlimit_prefetch_discards_audio_but_carries_failed_attempt(self):
        unit_dir = self.job / worker.SEGMENTS_DIR / worker.UNITS_DIR
        unit_dir.mkdir(parents=True)
        valid = {"index": 50000, "parent_index": 5, "unit_index": 0, "identity": "v", "text_sha256": "v",
                 "text": "Valid.", "speaker_text": "Speaker 0: Valid."}
        failed = {"index": 50001, "parent_index": 5, "unit_index": 1, "identity": "f", "text_sha256": "f",
                  "text": "Failed.", "speaker_text": "Speaker 0: Failed."}
        tmp = worker._wav_path(unit_dir, valid["index"]).with_suffix(".tmp.wav")
        tmp.write_bytes(b"provisional")
        with mock.patch.object(worker, "repair_units", return_value=[valid, failed]), \
             mock.patch.object(worker, "_valid_unit", return_value=False), \
             mock.patch.object(worker, "_batch_size", return_value=2), \
             mock.patch.object(worker, "_render_items", return_value=[(valid, 1, tmp, None), (failed, 1, tmp, RuntimeError("generation reached cap"))]), \
             mock.patch.object(worker, "_prefetch_within_limits", return_value=(False, "byte_limit")):
            handoff = worker._prefetch_next_parent(self.job, {"index": 5}, {}, unit_dir, object(), object(), object(), object())
        self.assertFalse(tmp.exists())
        self.assertEqual([(unit["index"], attempt) for unit, attempt, _tmp, _error in handoff["rendered"]], [(failed["index"], 1)])

    def test_prefetch_exception_keeps_current_parent_and_defers_next_normally(self):
        next_parent = {**self.parent, "index": 5, "identity": "parent-5"}
        first, second = self.units[0], {**self.units[0], "index": 50000, "parent_index": 5, "identity": "unit-5"}
        valid, rendered, assembled = set(), [], mock.Mock()
        prefetch_failed = False

        def render(_torch, _processor, _model, _voice, items, _config, unit_dir):
            nonlocal prefetch_failed
            if items[0][0]["parent_index"] == 5 and not prefetch_failed:
                prefetch_failed = True
                raise RuntimeError("synthetic")
            rows = []
            for unit, attempt in items:
                rendered.append((unit["parent_index"], attempt))
                tmp = worker._wav_path(unit_dir, unit["index"]).with_suffix(f".{unit['index']}.tmp.wav")
                tmp.write_bytes(b"synthetic")
                rows.append((unit, attempt, tmp, None))
            return rows

        class Quality:
            def __init__(_self, _checker, _wav, unit, _label):
                report = self.job / f"quality-{unit['index']}.json"; worker._write_json(report, {"transcript": unit["text"]}); _self.value = True, report
            def wait(_self, *_args): return _self.value

        def publish(unit_dir, unit, tmp, _report, attempt):
            tmp.unlink(missing_ok=True); valid.add(unit["index"]); worker._write_json(worker._receipt_path(unit_dir, unit["index"]), {"attempt": attempt, "identity": unit["identity"]})

        with mock.patch.object(worker, "load_plan", return_value=({"passages": [self.parent, next_parent]}, {"quality_max_retries": 0, "cross_parent_render_ahead": True})), \
             mock.patch.object(worker, "_valid_segment", return_value=False), mock.patch.object(worker, "_assert_no_ocr"), \
             mock.patch.object(worker, "_prepare_voice", return_value=object()), mock.patch.object(worker, "_load_model", return_value=(object(), object(), object())), \
             mock.patch.object(worker, "_QualityChecker"), mock.patch.object(worker, "_QualityCheck", Quality), mock.patch.object(worker, "_batch_size", return_value=1), \
             mock.patch.object(worker, "repair_units", side_effect=lambda parent: [first] if parent["index"] == 4 else [second]), \
             mock.patch.object(worker, "_valid_unit", side_effect=lambda _dir, unit, **_kw: unit["index"] in valid), \
             mock.patch.object(worker, "_render_items", side_effect=render), \
             mock.patch.object(worker, "_publish_unit", side_effect=publish), mock.patch.object(worker, "_unit_report", side_effect=lambda _dir, unit: {"unit_index": unit["unit_index"], "transcript": unit["text"], "missing_words": 0, "inserted_words": 0, "differences": []}), \
             mock.patch.object(worker, "parent_quality", return_value={"ok": True}), mock.patch.object(worker, "_assemble_parent_from_units", side_effect=assembled):
            worker.run_generate(self.job)
        self.assertEqual(rendered, [(4, 1), (5, 1)])
        self.assertNotIn((5, 2), rendered)
        self.assertEqual(assembled.call_count, 2)

    def test_cancel_after_prefetch_leaves_no_next_parent_receipt_or_tmp(self):
        next_parent = {**self.parent, "index": 5, "identity": "parent-5"}
        first, second = self.units[0], {**self.units[0], "index": 50000, "parent_index": 5, "identity": "unit-5"}
        valid = set()

        def render(_torch, _processor, _model, _voice, items, _config, unit_dir):
            rows = []
            for unit, attempt in items:
                tmp = worker._wav_path(unit_dir, unit["index"]).with_suffix(f".{unit['index']}.tmp.wav")
                tmp.write_bytes(b"synthetic")
                rows.append((unit, attempt, tmp, None))
            return rows

        class CancelQuality:
            def __init__(_self, _checker, _wav, unit, _label):
                _self.unit = unit
                report = self.job / "quality.json"
                worker._write_json(report, {"transcript": unit["text"]})
                _self.value = True, report
            def wait(_self, *_args):
                if _self.unit["parent_index"] == 4: (self.job / worker.CANCEL_FILE).write_text("cancel", encoding="utf-8")
                return _self.value

        with mock.patch.object(worker, "load_plan", return_value=({"passages": [self.parent, next_parent]}, {"quality_max_retries": 1, "cross_parent_render_ahead": True})), \
             mock.patch.object(worker, "_valid_segment", return_value=False), mock.patch.object(worker, "_assert_no_ocr"), mock.patch.object(worker, "_prepare_voice", return_value=object()), \
             mock.patch.object(worker, "_load_model", return_value=(object(), object(), object())), mock.patch.object(worker, "_QualityChecker"), mock.patch.object(worker, "_QualityCheck", CancelQuality), \
             mock.patch.object(worker, "_batch_size", return_value=1), mock.patch.object(worker, "repair_units", side_effect=lambda parent: [first] if parent["index"] == 4 else [second]), \
             mock.patch.object(worker, "_valid_unit", side_effect=lambda _dir, unit, **_kw: unit["index"] in valid), mock.patch.object(worker, "_render_items", side_effect=render), \
             mock.patch.object(worker, "_prefetch_within_limits", return_value=(True, {"seconds": 1, "bytes": 9})):
            with self.assertRaises(SystemExit): worker.run_generate(self.job)
        unit_dir = self.job / worker.SEGMENTS_DIR / worker.UNITS_DIR
        self.assertFalse(worker._receipt_path(unit_dir, second["index"]).exists())
        self.assertFalse(list(unit_dir.glob("*.tmp*.wav")))

    def test_cancel_before_publish_keeps_provisional_units_off_checkpoint(self):
        calls = 0

        def quality(_checker, _wav, _unit, _label):
            nonlocal calls
            calls += 1
            if calls == 1:
                (self.job / worker.CANCEL_FILE).write_text("cancel", encoding="utf-8")
            return True, self.job / "quality.json"

        with self.assertRaises(SystemExit):
            self._run(quality=quality)

        self.assertNotIn(self.units[0]["index"], self.valid)
        self.assertNotIn(self.units[1]["index"], self.valid)
        self.assertFalse(list((self.job / worker.SEGMENTS_DIR / worker.UNITS_DIR).glob("*.tmp*.wav")))
        self.assertFalse((self.job / worker.SEGMENTS_DIR / "seg_000004.json").exists())

        (self.job / worker.CANCEL_FILE).unlink()
        self.render_attempts.clear()
        self._run()
        self.assertEqual(self.render_attempts, [(0, 1), (1, 1)])

    def _numbered_heading_parent(self):
        self.parent.update(text="03: ARRIVAL", heading="03: ARRIVAL", block_types=["heading"], source_pages=[3])
        self.units = [{**self.units[0], "text": "03: ARRIVAL", "speaker_text": "Speaker 0: 03: ARRIVAL"}]
        self.reports = {self.units[0]["index"]: self.reports[self.units[0]["index"]]}
        return self.units[0]

    def _old_numbered_checkpoints(self, unit):
        seg_dir = self.job / worker.SEGMENTS_DIR
        unit_dir = seg_dir / worker.UNITS_DIR
        unit_dir.mkdir(parents=True)
        parent_wav = worker._wav_path(seg_dir, self.parent["index"])
        unit_wav = worker._wav_path(unit_dir, unit["index"])
        parent_receipt = worker._receipt_path(seg_dir, self.parent["index"])
        unit_receipt = worker._receipt_path(unit_dir, unit["index"])
        parent_wav.write_bytes(b"old parent wav")
        unit_wav.write_bytes(b"old unit wav")
        worker._write_json(parent_receipt, {"old": "parent"})
        worker._write_json(unit_receipt, {"old": "unit"})
        return parent_wav, unit_wav, parent_receipt, unit_receipt

    def test_numbered_raw_quality_pass_retries_without_replacing_old_checkpoint(self):
        unit = self._numbered_heading_parent()
        parent_wav, unit_wav, parent_receipt, unit_receipt = self._old_numbered_checkpoints(unit)
        report = self.job / "wrong-numbered-heading.json"
        worker._write_json(report, {"transcript": "Three Departure"})

        with self.assertRaisesRegex(RuntimeError, "major ASR coverage error"):
            self._run(quality=lambda *_args: (True, report), retries=1)

        self.assertEqual(parent_wav.read_bytes(), b"old parent wav")
        self.assertEqual(unit_wav.read_bytes(), b"old unit wav")
        self.assertEqual(json.loads(parent_receipt.read_text(encoding="utf-8")), {"old": "parent"})
        self.assertEqual(json.loads(unit_receipt.read_text(encoding="utf-8")), {"old": "unit"})
        self.assertEqual(self.render_attempts, [(0, 1), (0, 2)])

    def test_numbered_precommit_cancel_keeps_old_checkpoint(self):
        unit = self._numbered_heading_parent()
        parent_wav, unit_wav, parent_receipt, unit_receipt = self._old_numbered_checkpoints(unit)
        report = self.job / "right-numbered-heading.json"
        worker._write_json(report, {"transcript": "Three Arrival"})

        def cancel_after_verdict(*_args):
            (self.job / worker.CANCEL_FILE).write_text("cancel", encoding="utf-8")
            return True, report

        with self.assertRaises(SystemExit):
            self._run(quality=cancel_after_verdict)

        self.assertEqual(parent_wav.read_bytes(), b"old parent wav")
        self.assertEqual(unit_wav.read_bytes(), b"old unit wav")
        self.assertEqual(json.loads(parent_receipt.read_text(encoding="utf-8")), {"old": "parent"})
        self.assertEqual(json.loads(unit_receipt.read_text(encoding="utf-8")), {"old": "unit"})

    def test_numbered_aggregate_repair_rejects_raw_only_candidate_with_finite_budget(self):
        unit = self._numbered_heading_parent()
        self.reports[unit["index"]].update(missing_words=1, differences=[{"kind": "replace", "expected": ["arrival"], "heard": ["departure"]}])
        accepted = self.job / "accepted-numbered-heading.json"
        rejected = self.job / "rejected-numbered-heading.json"
        worker._write_json(accepted, {"transcript": "Three Arrival"})
        worker._write_json(rejected, {"transcript": "Three Departure"})
        verdicts = iter([(True, accepted), (True, rejected)])

        with self.assertRaisesRegex(RuntimeError, "parent quality failed after repairing"):
            self._run(quality=lambda *_args: next(verdicts), aggregate=lambda *_args, **_kwargs: {"ok": False}, retries=1)

        self.assertEqual(self.render_attempts, [(0, 1), (0, 2)])

    def _cached_receipts(self):
        unit_dir = self.job / worker.SEGMENTS_DIR / worker.UNITS_DIR
        unit_dir.mkdir(parents=True)
        for unit in self.units:
            wav = worker._wav_path(unit_dir, unit["index"])
            wav.write_bytes(b"accepted synthetic audio")
            report = unit_dir / f"report_{unit['index']}.json"
            worker._write_json(report, {
                "transcript": unit["text"], "unit_identity": unit["identity"],
                "unit_text_sha256": unit["text_sha256"], "audio_sha256": "audio",
            })
            worker._write_json(worker._receipt_path(unit_dir, unit["index"]), {
                "identity": unit["identity"], "text_sha256": unit["text_sha256"],
                "wav_sha256": "audio", "quality_report": str(report), "report_sha256": "report",
                "parent_index": unit["parent_index"], "unit_index": unit["unit_index"],
                "report_identity": unit["identity"], "report_wav_sha256": "audio", "needs_repair": True,
            })
        return unit_dir

    def test_tampered_checkpoint_hash_is_not_recoverable(self):
        unit_dir = self._cached_receipts()
        unit = self.units[0]
        with mock.patch.object(worker, "_valid_segment", return_value=True), \
             mock.patch.object(worker, "sha256_file", side_effect=lambda path: "audio" if Path(path).suffix == ".wav" else "report"):
            self.assertTrue(worker._valid_unit(unit_dir, unit, allow_needs_repair=True))
            receipt_path = worker._receipt_path(unit_dir, unit["index"])
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            receipt["report_sha256"] = "tampered"
            worker._write_json(receipt_path, receipt)
            self.assertFalse(worker._valid_unit(unit_dir, unit, allow_needs_repair=True))

    def test_unknown_profile_and_malformed_profile_attempts_are_not_valid(self):
        unit_dir = self._cached_receipts()
        unit = self.units[0]
        with mock.patch.object(worker, "_valid_segment", return_value=True), \
             mock.patch.object(worker, "sha256_file", side_effect=lambda path: "audio" if Path(path).suffix == ".wav" else "report"):
            receipt_path = worker._receipt_path(unit_dir, unit["index"])
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            receipt["render_profile"] = "unknown"
            worker._write_json(receipt_path, receipt)
            self.assertFalse(worker._valid_unit(unit_dir, unit, allow_needs_repair=True))
            receipt.pop("render_profile")
            receipt["profile_attempts"] = []
            worker._write_json(receipt_path, receipt)
            self.assertFalse(worker._valid_unit(unit_dir, unit, allow_needs_repair=True))

    def test_checkpoint_recovery_requires_every_unit_and_parent_gate(self):
        unit_dir = self._cached_receipts()
        seg_dir = self.job / worker.SEGMENTS_DIR
        before = {unit["index"]: worker._wav_path(unit_dir, unit["index"]).read_bytes() for unit in self.units}
        reports = [self.reports[unit["index"]] for unit in self.units]
        with mock.patch.object(worker, "_valid_unit", side_effect=[True, False]), \
             mock.patch.object(worker, "_unit_report", side_effect=reports), \
             mock.patch.object(worker, "parent_quality", return_value={"ok": True}), \
             mock.patch.object(worker, "_assemble_parent_from_units") as assemble:
            self.assertFalse(worker._recover_parent_from_units(self.job, self.parent, self.units, unit_dir, seg_dir))
            assemble.assert_not_called()
        with mock.patch.object(worker, "_valid_unit", return_value=True), \
             mock.patch.object(worker, "_unit_report", side_effect=reports), \
             mock.patch.object(worker, "parent_quality", return_value={"ok": False}), \
             mock.patch.object(worker, "_assemble_parent_from_units") as assemble:
            self.assertFalse(worker._recover_parent_from_units(self.job, self.parent, self.units, unit_dir, seg_dir))
            assemble.assert_not_called()
        with mock.patch.object(worker, "_valid_unit", return_value=True), \
             mock.patch.object(worker, "_unit_report", side_effect=reports), \
             mock.patch.object(worker, "parent_quality", return_value={"ok": True}), \
             mock.patch.object(worker, "_assemble_parent_from_units") as assemble:
            self.assertTrue(worker._recover_parent_from_units(self.job, self.parent, self.units, unit_dir, seg_dir))
            assemble.assert_called_once()
        self.assertEqual(before, {unit["index"]: worker._wav_path(unit_dir, unit["index"]).read_bytes() for unit in self.units})
        for unit in self.units:
            saved = json.loads(worker._receipt_path(unit_dir, unit["index"]).read_text(encoding="utf-8"))
            self.assertFalse(saved["needs_repair"])

    def _legacy_profile_receipts(self):
        unit_dir = self.job / worker.SEGMENTS_DIR / worker.UNITS_DIR
        unit_dir.mkdir(parents=True, exist_ok=True)
        self.units[0]["text"] = "Synthetic unit’s zero."
        self.units[0]["speaker_text"] = "Speaker 0: Synthetic unit’s zero."
        for unit in self.units:
            worker._wav_path(unit_dir, unit["index"]).write_bytes(f"legacy-{unit['index']}".encode())
            worker._write_json(worker._receipt_path(unit_dir, unit["index"]), {
                "identity": unit["identity"], "text_sha256": unit["text_sha256"],
                "parent_index": unit["parent_index"], "unit_index": unit["unit_index"], "attempt": 3,
            })
        return unit_dir

    def _profile_render(self, unit_dir):
        def render(_torch, _processor, _model, _voice, items, _config, _directory):
            unit, attempt = items[0]
            path = worker._wav_path(unit_dir, unit["index"]).with_suffix(".profile.tmp.wav")
            path.write_bytes(b"profile audio")
            return [(unit, attempt, path, None)]
        return render

    def _profile_quality(self, report):
        class ImmediateQuality:
            def __init__(_self, _checker, _wav, _unit, _label):
                _self.value = True, report

            def wait(_self, _job, _checker):
                return _self.value
        return ImmediateQuality

    def test_render_profile_changes_only_render_input_and_receipt_binds_it(self):
        unit = {**self.units[0], "text": "A worker’s checkpoint stays original.",
                "text_sha256": "original", "speaker_text": "Speaker 0: A worker’s checkpoint stays original."}
        profiled = worker._profiled_unit(unit, worker.ASCII_APOSTROPHE_PROFILE)
        self.assertEqual(profiled["text"], unit["text"])
        self.assertEqual(profiled["render_text"], "A worker's checkpoint stays original.")
        self.assertEqual(profiled["speaker_text"], "Speaker 0: A worker's checkpoint stays original.")

    def test_outline_case_profile_is_exact_page_prefix_only_and_keeps_source_identity(self):
        parent = {**self.parent, "text": "ACKNOWLEDGMENTS Thanks to everyone.",
                  "source_pages": [99], "identity": "original-parent", "heading": None,
                  "block_types": ["body"]}
        config = {"pdf_outline": [{"page": 99, "title": "Acknowledgments"}]}
        unit = worker._units_for_parent(parent, config)[0]
        rendered = worker._profiled_unit(unit)
        self.assertEqual(unit["text"], parent["text"])
        self.assertEqual(unit["identity"], worker.repair_units(parent)[0]["identity"])
        self.assertEqual(rendered["render_text"], "Acknowledgments Thanks to everyone.")
        self.assertEqual(rendered["render_profile"], worker.OUTLINE_PREFIX_CASE_PROFILE)
        self.assertEqual(rendered["render_heading"], "Acknowledgments")

    def test_outline_case_profile_rejects_wrong_page_boundary_case_and_ambiguity(self):
        parent = {**self.parent, "text": "ACKNOWLEDGMENTS Thanks.", "source_pages": [99], "block_types": ["body"]}
        self.assertIsNone(worker._outline_render_heading(parent, {"pdf_outline": [{"page": 98, "title": "Acknowledgments"}]}))
        self.assertIsNone(worker._outline_render_heading(
            {**parent, "text": "ACKNOWLEDGMENTSPLUS Thanks."},
            {"pdf_outline": [{"page": 99, "title": "Acknowledgments"}]}))
        for connector in ("ACKNOWLEDGMENTS-PLUS", "ACKNOWLEDGMENTS'PLUS", "ACKNOWLEDGMENTS_PLUS"):
            self.assertIsNone(worker._outline_render_heading(
                {**parent, "text": connector}, {"pdf_outline": [{"page": 99, "title": "Acknowledgments"}]}))
        self.assertIsNone(worker._outline_render_heading(
            {**parent, "text": "Acknowledgments Thanks."},
            {"pdf_outline": [{"page": 99, "title": "Acknowledgments"}]}))
        self.assertIsNone(worker._outline_render_heading(parent, {"pdf_outline": [
            {"page": 99, "title": "Acknowledgments"}, {"page": 99, "title": "Acknowledgments"},
        ]}))

    def test_outline_case_profile_preserves_outline_spelling_without_global_prose_casing(self):
        parent = {**self.parent, "text": "MCGILLICUDDY AND NASA Thanks.", "source_pages": [99], "block_types": ["body", "body"]}
        config = {"pdf_outline": [{"page": 99, "title": "McGillicuddy and NASA"}]}
        unit = worker._units_for_parent(parent, config)[0]
        self.assertEqual(worker._profiled_unit(unit)["render_text"], "McGillicuddy and NASA Thanks.")
        ordinary = {**self.units[0], "text": "LOUD PROSE STAYS UPPERCASE.",
                    "speaker_text": "Speaker 0: LOUD PROSE STAYS UPPERCASE."}
        self.assertEqual(worker._profiled_unit(ordinary)["render_text"], ordinary["text"])

    def test_outline_case_profile_rejects_nonbody_parent_and_title_outside_first_unit(self):
        parent = {**self.parent, "text": "ACKNOWLEDGMENTS Thanks.", "source_pages": [99], "block_types": ["heading", "body"]}
        config = {"pdf_outline": [{"page": 99, "title": "Acknowledgments"}]}
        self.assertIsNone(worker._outline_render_heading(parent, config))
        body_parent = {**parent, "block_types": ["body"]}
        short_unit = {**self.units[0], "text": "ACKNOWLEDG", "speaker_text": "Speaker 0: ACKNOWLEDG"}
        with mock.patch.object(worker, "repair_units", return_value=[short_unit]):
            self.assertNotIn("render_profile", worker._units_for_parent(body_parent, config)[0])

    def test_numbered_outline_heading_profile_is_page_bound_and_preserves_source(self):
        parent = {**self.parent, "text": "03: IMMOLATION", "heading": "03: IMMOLATION",
                  "block_types": ["heading"], "source_pages": [9]}
        config = {"pdf_outline": [{"page": 9, "title": "3: Immolation"}]}
        unit = worker._units_for_parent(parent, config)[0]
        rendered = worker._profiled_unit(unit)
        self.assertEqual(unit["text"], parent["text"])
        self.assertEqual(rendered["render_text"], "Three: Immolation")
        self.assertEqual(rendered["render_profile"], worker.NUMBERED_OUTLINE_HEADING_PROFILE)
        self.assertIsNone(worker._numbered_outline_heading(parent, {"pdf_outline": [{"page": 8, "title": "3: Immolation"}]}))
        self.assertIsNone(worker._numbered_outline_heading(parent, {"pdf_outline": [
            {"page": 9, "title": "3: Immolation"}, {"page": 9, "title": "3: Immolation"},
        ]}))

    def test_numbered_heading_seed_schedule_is_bounded_and_restores_rng(self):
        passage = {"render_profile": worker.NUMBERED_OUTLINE_HEADING_PROFILE}
        self.assertEqual([worker._numbered_heading_seed(passage, attempt) for attempt in range(1, 4)], [101, 102, 103])
        self.assertIsNone(worker._numbered_heading_seed(passage, 4))
        self.assertEqual(worker._attempt_limit(passage, 9), 3)
        self.assertEqual(worker._attempt_limit({}, 9), 10)

        state, calls = {"cpu": 7, "cuda": 8}, []
        class Fork:
            def __enter__(_self):
                _self.before = dict(state)
            def __exit__(_self, *_args):
                state.update(_self.before)
        class Random:
            def fork_rng(_self, devices):
                calls.append(("fork", devices))
                return Fork()
        class Cuda:
            def device_count(_self):
                return 2
            def manual_seed_all(_self, seed):
                state["cuda"] = seed
        class Torch:
            random, cuda = Random(), Cuda()
            def manual_seed(_self, seed):
                state["cpu"] = seed
        def render():
            calls.append(("render", dict(state)))
            return "rendered"

        self.assertEqual(worker._render_with_numbered_heading_seed(Torch(), passage, 2, render), "rendered")
        self.assertEqual(calls, [("fork", [0, 1]), ("render", {"cpu": 102, "cuda": 102})])
        self.assertEqual(state, {"cpu": 7, "cuda": 8})

    def test_seeded_numbered_profile_receipt_rejects_missing_or_tampered_seed(self):
        unit_dir = self._cached_receipts()
        unit = {**self.units[0], "text": "03: ARRIVAL", "speaker_text": "Speaker 0: 03: ARRIVAL",
                "render_profile": worker.NUMBERED_OUTLINE_HEADING_PROFILE, "render_heading": "Three: Arrival"}
        wav = worker._wav_path(unit_dir, unit["index"])
        report = unit_dir / f"report_{unit['index']}.json"
        worker._write_json(report, {"transcript": unit["text"], "unit_identity": unit["identity"],
                                    "unit_text_sha256": unit["text_sha256"], "audio_sha256": "audio"})
        receipt_path = worker._receipt_path(unit_dir, unit["index"])
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        receipt.update(attempt=2, render_profile=worker.NUMBERED_OUTLINE_HEADING_PROFILE,
                       render_heading="Three: Arrival", render_text_sha256=worker._render_text_sha256(unit, worker.NUMBERED_OUTLINE_HEADING_PROFILE),
                       render_seed_profile=worker.NUMBERED_OUTLINE_HEADING_SEED_PROFILE,
                       render_seed=102, render_attempt=2)
        worker._write_json(receipt_path, receipt)
        with mock.patch.object(worker, "_valid_segment", return_value=True), \
             mock.patch.object(worker, "sha256_file", side_effect=lambda path: "audio" if Path(path) == wav else "report"):
            self.assertTrue(worker._valid_unit(unit_dir, unit, allow_needs_repair=True))
            receipt.pop("render_seed")
            worker._write_json(receipt_path, receipt)
            self.assertFalse(worker._valid_unit(unit_dir, unit, allow_needs_repair=True))
            receipt["render_seed"] = 101
            worker._write_json(receipt_path, receipt)
            self.assertFalse(worker._valid_unit(unit_dir, unit, allow_needs_repair=True))
            receipt.update(render_seed=102, attempt=1)
            worker._write_json(receipt_path, receipt)
            self.assertFalse(worker._valid_unit(unit_dir, unit, allow_needs_repair=True))
            receipt.update(attempt=True, render_attempt=True, render_seed=101)
            worker._write_json(receipt_path, receipt)
            self.assertFalse(worker._valid_unit(unit_dir, unit, allow_needs_repair=True))

    def test_numbered_heading_reuses_strict_passing_ascii_legacy_receipt(self):
        unit_dir = self._cached_receipts()
        unit = {**self.units[0], "text": "03: ARRIVAL", "speaker_text": "Speaker 0: 03: ARRIVAL",
                "numbered_heading": True, "render_profile": worker.NUMBERED_OUTLINE_HEADING_PROFILE,
                "render_heading": "Three: Arrival"}
        wav = worker._wav_path(unit_dir, unit["index"])
        report = unit_dir / f"report_{unit['index']}.json"
        worker._write_json(report, {"transcript": unit["text"], "unit_identity": unit["identity"],
                                    "unit_text_sha256": unit["text_sha256"], "audio_sha256": "audio"})
        receipt_path = worker._receipt_path(unit_dir, unit["index"])
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        receipt.update(render_profile=worker.ASCII_APOSTROPHE_PROFILE,
                       render_text_sha256=worker._render_text_sha256(unit, worker.ASCII_APOSTROPHE_PROFILE))
        worker._write_json(receipt_path, receipt)
        with mock.patch.object(worker, "_valid_segment", return_value=True), \
             mock.patch.object(worker, "sha256_file", side_effect=lambda path: "audio" if Path(path) == wav else "report"):
            self.assertTrue(worker._valid_unit(unit_dir, unit, allow_needs_repair=True))

    def test_seeded_heading_batch_with_peer_fails_before_generation(self):
        seeded = {**self.units[0], "render_profile": worker.NUMBERED_OUTLINE_HEADING_PROFILE}
        with mock.patch.object(worker, "_assert_no_ocr"):
            with self.assertRaisesRegex(RuntimeError, "one seeded row"):
                worker._render_batch(object(), object(), object(), object(), [(seeded, 1), (self.units[1], 1)], {}, self.job)

    def test_replaced_heading_wav_is_copied_without_touching_active_output(self):
        rejected = self.job / worker.REJECTED_DIR
        rejected.mkdir()
        prior = self.job / "seg_000003.wav"
        prior.write_bytes(b"prior heading audio")
        worker._archive_replaced_heading_wav(prior, rejected)
        archived = list(rejected.glob("seg_000003_replaced_numbered_heading_*.wav"))
        self.assertTrue(prior.exists())
        self.assertEqual(len(archived), 1)
        self.assertEqual(archived[0].read_bytes(), b"prior heading audio")

    def test_numbered_unit_commit_archives_exact_old_bytes_then_replaces(self):
        unit = {**self.units[0], "numbered_heading": True}
        unit_dir = self.job / worker.SEGMENTS_DIR / worker.UNITS_DIR
        unit_dir.mkdir(parents=True)
        final = worker._wav_path(unit_dir, unit["index"])
        final.write_bytes(b"old accepted unit")
        tmp = unit_dir / "candidate.tmp.wav"
        tmp.write_bytes(b"new accepted unit")
        report = self.job / "accepted-heading-report.json"
        worker._write_json(report, {"transcript": "Three Arrival"})

        worker._publish_unit(unit_dir, unit, tmp, report, 2)

        self.assertEqual(final.read_bytes(), b"new accepted unit")
        archived = list((self.job / worker.REJECTED_DIR).glob(f"{final.stem}_replaced_numbered_heading_*.wav"))
        self.assertEqual(len(archived), 1)
        self.assertEqual(archived[0].read_bytes(), b"old accepted unit")

    def test_numbered_unit_cancel_during_archive_keeps_active_checkpoint(self):
        unit = {**self.units[0], "numbered_heading": True}
        unit_dir = self.job / worker.SEGMENTS_DIR / worker.UNITS_DIR
        unit_dir.mkdir(parents=True)
        final = worker._wav_path(unit_dir, unit["index"])
        receipt = worker._receipt_path(unit_dir, unit["index"])
        final.write_bytes(b"old accepted unit")
        worker._write_json(receipt, {"old": "receipt"})
        tmp = unit_dir / "candidate.tmp.wav"
        tmp.write_bytes(b"new accepted unit")
        report = self.job / "accepted-heading-report.json"
        worker._write_json(report, {"transcript": "Three Arrival"})

        def archive_then_cancel(*_args):
            (self.job / worker.CANCEL_FILE).write_text("cancel", encoding="utf-8")

        with mock.patch.object(worker, "_archive_replaced_heading_wav", side_effect=archive_then_cancel):
            with self.assertRaises(SystemExit):
                worker._publish_unit(unit_dir, unit, tmp, report, 2)

        self.assertEqual(final.read_bytes(), b"old accepted unit")
        self.assertEqual(json.loads(receipt.read_text(encoding="utf-8")), {"old": "receipt"})

    def test_legacy_apostrophe_candidate_ignores_new_outline_context(self):
        unit_dir = self._legacy_profile_receipts()
        unit = {**self.units[0], "text": "A unit’s text.", "render_profile": worker.OUTLINE_PREFIX_CASE_PROFILE,
                "render_heading": "A Unit"}
        worker._write_json(worker._receipt_path(unit_dir, unit["index"]), {
            "identity": unit["identity"], "text_sha256": unit["text_sha256"],
            "parent_index": unit["parent_index"], "unit_index": unit["unit_index"], "attempt": 3,
        })
        report = {"differences": [{"expected": ["unit's"]}], "missing_words": 1, "inserted_words": 1}
        self.assertEqual(worker._profile_recovery_candidates(self.parent, [unit], [report], unit_dir, 2), [unit])

    def test_outline_profile_receipt_rejects_heading_or_render_hash_tampering(self):
        unit_dir = self._cached_receipts()
        unit = {**self.units[0], "text": "ACKNOWLEDGMENTS Thanks.", "render_heading": "Acknowledgments",
                "render_profile": worker.OUTLINE_PREFIX_CASE_PROFILE}
        wav = worker._wav_path(unit_dir, unit["index"])
        report = unit_dir / f"report_{unit['index']}.json"
        receipt_path = worker._receipt_path(unit_dir, unit["index"])
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        receipt.update(render_profile=worker.OUTLINE_PREFIX_CASE_PROFILE, render_heading="Acknowledgments",
                       render_text_sha256=worker._render_text_sha256(unit, worker.OUTLINE_PREFIX_CASE_PROFILE))
        worker._write_json(receipt_path, receipt)
        with mock.patch.object(worker, "_valid_segment", return_value=True), \
             mock.patch.object(worker, "sha256_file", side_effect=lambda path: "audio" if Path(path) == wav else "report"):
            self.assertTrue(worker._valid_unit(unit_dir, unit, allow_needs_repair=True))
            receipt["render_heading"] = "Acknowledgement"
            worker._write_json(receipt_path, receipt)
            self.assertFalse(worker._valid_unit(unit_dir, unit, allow_needs_repair=True))
            receipt["render_heading"] = "Acknowledgments"
            receipt["render_text_sha256"] = "tampered"
            worker._write_json(receipt_path, receipt)
            self.assertFalse(worker._valid_unit(unit_dir, unit, allow_needs_repair=True))

    def test_nonimproving_profile_attempt_archives_new_audio_and_keeps_legacy_peer(self):
        unit_dir = self._legacy_profile_receipts()
        rejected = self.job / worker.REJECTED_DIR
        rejected.mkdir()
        report = self.job / "profile.json"
        worker._write_json(report, {"transcript": self.units[0]["text"]})
        old = {unit["index"]: worker._wav_path(unit_dir, unit["index"]).read_bytes() for unit in self.units}
        reports = [{"unit_index": 0, "differences": [{"kind": "replace", "expected": ["unit's"]}], "missing_words": 2, "inserted_words": 2},
                   {"unit_index": 1, "differences": [], "missing_words": 0, "inserted_words": 0}]
        with mock.patch.object(worker, "_render_items", side_effect=self._profile_render(unit_dir)), \
             mock.patch.object(worker, "_QualityCheck", self._profile_quality(report)), \
             mock.patch.object(worker, "parent_quality", side_effect=[{"ok": False, "missing_words": 4, "inserted_words": 0, "differences": [1]},
                                                                         {"ok": False, "missing_words": 4, "inserted_words": 0, "differences": [1]}]):
            self.assertIsNone(worker._recover_with_render_profile(
                self.job, self.parent, self.units, reports, unit_dir, rejected,
                object(), object(), object(), object(), {}, object(), 2))
        self.assertEqual(old, {unit["index"]: worker._wav_path(unit_dir, unit["index"]).read_bytes() for unit in self.units})
        self.assertTrue(list(rejected.glob("unit_*_profile_*.wav")))
        receipt = json.loads(worker._receipt_path(unit_dir, self.units[0]["index"]).read_text(encoding="utf-8"))
        self.assertIn("profile_attempts", receipt)

    def test_profile_attempt_is_spent_before_cancel_and_stays_spent_on_resume(self):
        unit_dir = self._legacy_profile_receipts()
        rejected = self.job / worker.REJECTED_DIR
        rejected.mkdir()
        reports = [{"unit_index": 0, "differences": [{"kind": "replace", "expected": ["unit's"]}], "missing_words": 2, "inserted_words": 2},
                   {"unit_index": 1, "differences": [], "missing_words": 0, "inserted_words": 0}]

        def cancel_after_render(*args):
            (self.job / worker.CANCEL_FILE).write_text("cancel", encoding="utf-8")
            return self._profile_render(unit_dir)(*args)

        with mock.patch.object(worker, "_render_items", side_effect=cancel_after_render), \
             mock.patch.object(worker, "parent_quality", return_value={"ok": False, "missing_words": 4, "inserted_words": 0, "differences": [1]}):
            with self.assertRaises(SystemExit):
                worker._recover_with_render_profile(self.job, self.parent, self.units, reports, unit_dir, rejected,
                                                    object(), object(), object(), object(), {}, object(), 2)
        receipt = json.loads(worker._receipt_path(unit_dir, self.units[0]["index"]).read_text(encoding="utf-8"))
        self.assertIn("profile_attempts", receipt)
        (self.job / worker.CANCEL_FILE).unlink()
        self.assertEqual(worker._profile_recovery_candidates(self.parent, self.units, reports, unit_dir, 2), [])

    def test_improving_profile_repair_replaces_only_affected_unit_and_returns_parent_gate(self):
        unit_dir = self._legacy_profile_receipts()
        rejected = self.job / worker.REJECTED_DIR
        rejected.mkdir()
        report = self.job / "profile.json"
        worker._write_json(report, {"transcript": self.units[0]["text"]})
        peer_before = worker._wav_path(unit_dir, self.units[1]["index"]).read_bytes()
        reports = [{"unit_index": 0, "differences": [{"kind": "replace", "expected": ["unit's"]}], "missing_words": 3, "inserted_words": 2},
                   {"unit_index": 1, "differences": [], "missing_words": 0, "inserted_words": 0}]
        improved = {"ok": True, "missing_words": 0, "inserted_words": 0, "differences": []}
        with mock.patch.object(worker, "_render_items", side_effect=self._profile_render(unit_dir)), \
             mock.patch.object(worker, "_QualityCheck", self._profile_quality(report)), \
             mock.patch.object(worker, "parent_quality", side_effect=[{"ok": False, "missing_words": 5, "inserted_words": 0, "differences": [1]}, improved]):
            recovered = worker._recover_with_render_profile(self.job, self.parent, self.units, reports, unit_dir, rejected,
                                                             object(), object(), object(), object(), {}, object(), 2)
        self.assertEqual(recovered[1], improved)
        self.assertEqual(worker._wav_path(unit_dir, self.units[0]["index"]).read_bytes(), b"profile audio")
        self.assertEqual(worker._wav_path(unit_dir, self.units[1]["index"]).read_bytes(), peer_before)
        receipt = json.loads(worker._receipt_path(unit_dir, self.units[0]["index"]).read_text(encoding="utf-8"))
        self.assertEqual(receipt["render_profile"], worker.ASCII_APOSTROPHE_PROFILE)
        self.assertEqual(receipt["render_text_sha256"], worker._render_text_sha256(self.units[0], worker.ASCII_APOSTROPHE_PROFILE))
        self.assertEqual(receipt["attempt"], 4)

    def test_profile_repair_rejects_tradeoff_that_worsens_one_parent_gate(self):
        baseline = {"ok": False, "missing_words": 5, "inserted_words": 5}
        candidate = {"ok": False, "missing_words": 6, "inserted_words": 0}
        self.assertFalse(worker._strict_parent_improvement(baseline, candidate))


if __name__ == "__main__":
    unittest.main()
