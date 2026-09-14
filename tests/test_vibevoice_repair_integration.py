import json
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
        test_root = Path(__file__).resolve().parents[1] / ".test-tmp"
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
             mock.patch.object(worker, "_valid_unit", side_effect=lambda _directory, unit: unit["index"] in self.valid), \
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

    def test_cancel_with_provisional_peer_keeps_accepted_unit_for_resume(self):
        calls = 0

        def quality(_checker, _wav, _unit, _label):
            nonlocal calls
            calls += 1
            if calls == 1:
                (self.job / worker.CANCEL_FILE).write_text("cancel", encoding="utf-8")
            return True, self.job / "quality.json"

        with self.assertRaises(SystemExit):
            self._run(quality=quality)

        self.assertIn(self.units[0]["index"], self.valid)
        self.assertNotIn(self.units[1]["index"], self.valid)
        self.assertFalse(list((self.job / worker.SEGMENTS_DIR / worker.UNITS_DIR).glob("*.tmp*.wav")))
        self.assertFalse((self.job / worker.SEGMENTS_DIR / "seg_000004.json").exists())

        (self.job / worker.CANCEL_FILE).unlink()
        self.render_attempts.clear()
        self._run()
        self.assertEqual(self.render_attempts, [(1, 1)])


if __name__ == "__main__":
    unittest.main()
