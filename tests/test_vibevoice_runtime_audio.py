import json
import io
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
try:
    import numpy as np
    import soundfile as sf
    import vibevoice_worker as worker
except ModuleNotFoundError:
    np = sf = worker = None

TEST_ROOT = Path(__file__).resolve().parents[1] / ".test-tmp"
TEST_ROOT.mkdir(exist_ok=True)


class _Cuda:
    def empty_cache(self): pass


class _Torch:
    cuda = _Cuda()


def unit(parent, number):
    text = f"Synthetic unit {number}."
    return {"index": parent * 10000 + number, "parent_index": parent, "unit_index": number,
            "identity": f"unit-{number}", "text": text, "speaker_text": "Speaker 0: " + text,
            "text_sha256": f"text-{number}"}


@unittest.skipUnless(np is not None, "requires the isolated VibeVoice runtime")
class VibeVoiceRuntimeAudioTests(unittest.TestCase):
    def test_quality_helper_timeout_cancel_and_bounded_stderr(self):
        class Process:
            def __init__(self, output='{"ready": true}\n'):
                self.stdin, self.stdout, self.stderr = io.StringIO(), io.StringIO(output), io.StringIO()
                self.returncode, self.killed = None, False
            def poll(self): return self.returncode
            def kill(self): self.killed, self.returncode = True, -9
            def wait(self, timeout=None): return self.returncode
        with tempfile.TemporaryDirectory(dir=TEST_ROOT) as temp:
            job, process = Path(temp), Process()
            config = {"quality_python": "python", "quality_model": "model", "quality_timeout_seconds": 1}
            with mock.patch.object(worker.subprocess, "Popen", return_value=process):
                checker = worker._QualityChecker(job, config)
                with mock.patch.object(worker.time, "monotonic", side_effect=[0, 2]), self.assertRaisesRegex(RuntimeError, "timed out"):
                    checker.check(job / "a.wav", {"index": 0, "text": "Synthetic"}, "a")
            self.assertTrue(process.killed)
            checker = object.__new__(worker._QualityChecker)
            checker.stderr, checker.stderr_lock = worker.deque(maxlen=100), worker.Lock()
            worker._QualityChecker._read(io.StringIO("x" * 10000 + "\n"), checker.stderr, checker.stderr_lock)
            self.assertLessEqual(len(checker._detail()), 2048)

    def test_concurrent_helper_close_kills_once(self):
        process = mock.Mock(); process.poll.return_value = None
        checker = object.__new__(worker._QualityChecker)
        checker.process, checker.process_lock, checker.drain_threads = process, worker.Lock(), []
        threads = [threading.Thread(target=checker.close) for _ in range(2)]
        for thread in threads: thread.start()
        for thread in threads: thread.join(5)
        process.kill.assert_called_once()

    def test_reference_wav_conversion_needs_no_ffmpeg(self):
        stereo = np.array([[0.0, 1.0], [1.0, 0.0], [0.5, 0.5]], dtype=np.float32)
        converted = worker.mono_24k(stereo, 24000)
        np.testing.assert_allclose(converted, [0.5, 0.5, 0.5])


    def test_valid_cached_segment_resumes_without_model_load(self):
        test_root = Path(__file__).resolve().parents[1] / ".test-tmp"
        test_root.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=test_root) as temp:
            job = Path(temp)
            seg_dir = job / worker.SEGMENTS_DIR
            seg_dir.mkdir()
            audio = np.full(2401, 0.02, dtype=np.float32)
            wav = seg_dir / "seg_000000.wav"
            sf.write(wav, audio, 24000, subtype="PCM_16")
            passage = {"index": 0, "identity": "identity", "text_sha256": "text"}
            receipt = {"identity": "identity", "wav_sha256": worker.sha256_file(wav)}
            (seg_dir / "seg_000000.json").write_text(json.dumps(receipt), encoding="utf-8")
            plan = {"passages": [passage], "voice_sha256": "voice"}
            config = {}
            with mock.patch.object(worker, "load_plan", return_value=(plan, config)), \
                 mock.patch.object(worker, "_load_model", side_effect=AssertionError("must not load")), \
                 mock.patch.object(worker, "_QualityChecker", side_effect=AssertionError("must not load ASR")):
                worker.run_generate(job)
            progress = json.loads((job / worker.PROGRESS_FILE).read_text(encoding="utf-8"))
            self.assertEqual(progress, {"done": 1, "total": 1, "shard": 0, "status": "complete"})

    def test_seeded_numbered_parent_cache_binds_manifest_before_skip(self):
        with tempfile.TemporaryDirectory(dir=TEST_ROOT) as temp:
            job = Path(temp)
            seg_dir = job / worker.SEGMENTS_DIR
            seg_dir.mkdir()
            audio = np.full(2401, 0.02, dtype=np.float32)
            wav = worker._wav_path(seg_dir, 0)
            sf.write(wav, audio, 24000, subtype="PCM_16")
            passage = {"index": 0, "identity": "identity", "text_sha256": "text",
                       "text": "03: ARRIVAL", "heading": "03: ARRIVAL"}
            seed = {"render_seed_profile": worker.NUMBERED_OUTLINE_HEADING_SEED_PROFILE,
                    "render_seed": 102, "render_attempt": 2}
            receipt = {"identity": "identity", "wav_sha256": worker.sha256_file(wav),
                       "unit_reports": [{"transcript": "Three Arrival"}],
                       "unit_manifest": [{"index": 0, "identity": "unit", "wav_sha256": "unit-audio", **seed}]}
            worker._write_json(worker._receipt_path(seg_dir, 0), receipt)
            unit_dir = seg_dir / worker.UNITS_DIR
            unit_dir.mkdir()
            worker._write_json(worker._receipt_path(unit_dir, 0), {"render_profile": worker.NUMBERED_OUTLINE_HEADING_PROFILE,
                                                                    "attempt": 2, **seed})
            with mock.patch.object(worker, "load_plan", return_value=({"passages": [passage]}, {})), \
                 mock.patch.object(worker, "_load_model", side_effect=AssertionError("must not load")), \
                 mock.patch.object(worker, "_QualityChecker", side_effect=AssertionError("must not load ASR")):
                worker.run_generate(job)
            unit_receipt = worker._receipt_path(unit_dir, 0)
            unit_payload = json.loads(unit_receipt.read_text(encoding="utf-8"))
            unit_payload["attempt"] = 1
            worker._write_json(unit_receipt, unit_payload)
            self.assertFalse(worker._valid_segment(seg_dir, passage))
            unit_payload["attempt"] = 2
            worker._write_json(unit_receipt, unit_payload)
            receipt["unit_manifest"][0]["render_seed"] = 101
            worker._write_json(worker._receipt_path(seg_dir, 0), receipt)
            self.assertFalse(worker._valid_segment(seg_dir, passage))
            receipt["unit_manifest"][0].update(seed)
            for key in seed:
                receipt["unit_manifest"][0].pop(key)
            worker._write_json(worker._receipt_path(seg_dir, 0), receipt)
            self.assertFalse(worker._valid_segment(seg_dir, passage))


    def test_parent_join_preserves_timing_and_interior_audio(self):
        with tempfile.TemporaryDirectory(dir=TEST_ROOT) as temp:
            directory = Path(temp)
            unit_dir, seg_dir = directory / "units", directory / "segments"
            unit_dir.mkdir()
            seg_dir.mkdir()
            parent = {"index": 0, "identity": "parent", "text_sha256": "text"}
            units = [unit(0, index) for index in range(2)]
            for row, level in zip(units, [.25, -.25]):
                sf.write(worker._wav_path(unit_dir, row["index"]), np.full(3000, level), 24000, subtype="PCM_16")
            with mock.patch.object(worker, "_unit_report", return_value={}):
                worker._assemble_parent_from_units(parent, units, unit_dir, seg_dir, {"ok": True})
            joined, sr = sf.read(worker._wav_path(seg_dir, 0), dtype="int16")
            self.assertEqual((len(joined), sr), (6000, 24000))
            self.assertEqual((joined[2999], joined[3000]), (0, 0))
            np.testing.assert_array_equal(joined[:2880], np.full(2880, 8192))
            np.testing.assert_array_equal(joined[3120:], np.full(2880, -8192))
            for row, level in zip(units, [8192, -8192]):
                original, _ = sf.read(worker._wav_path(unit_dir, row["index"]), dtype="int16")
                np.testing.assert_array_equal(original, np.full(3000, level))

    def test_unit_cache_binds_report_identity_and_audio_hash(self):
        with tempfile.TemporaryDirectory(dir=TEST_ROOT) as temp:
            directory, row = Path(temp), unit(3, 0)
            wav = worker._wav_path(directory, row["index"])
            sf.write(wav, np.full(2401, .02, dtype=np.float32), 24000, subtype="PCM_16")
            report = directory / "report.json"
            report.write_text(json.dumps({"transcript": row["text"], "unit_identity": row["identity"],
                "unit_text_sha256": row["text_sha256"], "audio_sha256": worker.sha256_file(wav)}), encoding="utf-8")
            receipt = {"identity": row["identity"], "text_sha256": row["text_sha256"], "wav_sha256": worker.sha256_file(wav),
                "quality_report": str(report), "report_sha256": worker.sha256_file(report), "parent_index": 3, "unit_index": 0,
                "report_identity": row["identity"], "report_wav_sha256": worker.sha256_file(wav)}
            worker._write_json(worker._receipt_path(directory, row["index"]), receipt)
            self.assertTrue(worker._valid_unit(directory, row))
            receipt["report_wav_sha256"] = "stale"
            worker._write_json(worker._receipt_path(directory, row["index"]), receipt)
            self.assertFalse(worker._valid_unit(directory, row))

    def test_oom_bisection_keeps_batch_row_order(self):
        calls, rows = [], [unit(1, 0), unit(1, 1)]
        def render(_t, _p, _m, _v, items, _c, _d):
            calls.append([item[0]["unit_index"] for item in items])
            if len(items) == 2: raise RuntimeError("CUDA out of memory")
            item, attempt = items[0]
            return [(item, attempt, Path("tmp.wav"), None)]
        with mock.patch.object(worker, "_render_batch", side_effect=render):
            result = worker._render_items(_Torch(), None, None, None, [(rows[0], 1), (rows[1], 1)], {}, Path("."))
        self.assertEqual(calls, [[0, 1], [0], [1]])
        self.assertEqual([entry[0]["unit_index"] for entry in result], [0, 1])

    def test_peer_publishes_before_failed_row_retry(self):
        parent, rows = {"index": 4, "identity": "parent", "text_sha256": "parent", "text": "Synthetic."}, [unit(4, 0), unit(4, 1)]
        reports, published = {}, []
        with tempfile.TemporaryDirectory(dir=TEST_ROOT) as temp:
            job = Path(temp)
            def render(_t, _p, _m, _v, items, _c, directory):
                result = []
                for row, attempt in items:
                    path = directory / f"{row['unit_index']}-{attempt}.tmp.wav"; path.write_bytes(b"audio")
                    error = RuntimeError("generated audio was empty, nonfinite, or silent") if row["unit_index"] == 0 and attempt == 1 else None
                    result.append((row, attempt, path, error))
                return result
            def publish(directory, row, _p, _r, attempt):
                published.append((row["unit_index"], attempt)); reports[row["unit_index"]] = {"unit_index": row["unit_index"], "transcript": row["text"]}
                worker._write_json(worker._receipt_path(directory, row["index"]), {"attempt": attempt})
            def quality(_checker, _wav, row, _label):
                report = job / "report.json"
                worker._write_json(report, {"transcript": row["text"]})
                return True, report
            patches = [mock.patch.object(worker, "load_plan", return_value=({"passages": [parent], "voice_sha256": "v"}, {"quality_max_retries": 1})),
                mock.patch.object(worker, "_valid_segment", return_value=False), mock.patch.object(worker, "_valid_unit", return_value=False),
                mock.patch.object(worker, "repair_units", return_value=rows), mock.patch.object(worker, "_assert_no_ocr"), mock.patch.object(worker, "_prepare_voice", return_value=None),
                mock.patch.object(worker, "_load_model", return_value=(_Torch(), None, None)), mock.patch.object(worker, "_batch_size", return_value=2),
                mock.patch.object(worker, "_QualityChecker"), mock.patch.object(worker, "_render_items", side_effect=render),
                mock.patch.object(worker, "_quality_check", side_effect=quality), mock.patch.object(worker, "_publish_unit", side_effect=publish),
                mock.patch.object(worker, "_unit_report", side_effect=lambda _d, row: reports[row["unit_index"]]),
                mock.patch.object(worker, "parent_quality", return_value={"ok": True}), mock.patch.object(worker, "_assemble_parent_from_units")]
            with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], patches[7], patches[8], patches[9], patches[10], patches[11], patches[12], patches[13], patches[14]:
                worker.run_generate(job)
        self.assertEqual(published, [(1, 1), (0, 2)])

    def test_aggregate_failure_repairs_before_parent_publish(self):
        parent, rows = {"index": 5, "identity": "parent", "text_sha256": "parent", "text": "Synthetic."}, [unit(5, 0), unit(5, 1)]
        reports, published, assembled = {}, [], []
        with tempfile.TemporaryDirectory(dir=TEST_ROOT) as temp:
            job = Path(temp)
            def render(_t, _p, _m, _v, items, _c, directory):
                return [(row, attempt, (directory / f"{row['unit_index']}-{attempt}.tmp.wav"), None) for row, attempt in items]
            def publish(directory, row, _p, _r, attempt):
                published.append((row["unit_index"], attempt)); reports[row["unit_index"]] = {"unit_index": row["unit_index"], "transcript": row["text"]}
                worker._write_json(worker._receipt_path(directory, row["index"]), {"attempt": attempt})
            def quality(_checker, _wav, row, _label):
                report = job / "report.json"
                worker._write_json(report, {"transcript": row["text"]})
                return True, report
            with mock.patch.object(worker, "load_plan", return_value=({"passages": [parent], "voice_sha256": "v"}, {"quality_max_retries": 1})), mock.patch.object(worker, "_valid_segment", return_value=False), mock.patch.object(worker, "_valid_unit", return_value=False), mock.patch.object(worker, "repair_units", return_value=rows), mock.patch.object(worker, "_assert_no_ocr"), mock.patch.object(worker, "_prepare_voice", return_value=None), mock.patch.object(worker, "_load_model", return_value=(_Torch(), None, None)), mock.patch.object(worker, "_batch_size", return_value=2), mock.patch.object(worker, "_QualityChecker"), mock.patch.object(worker, "_render_items", side_effect=render), mock.patch.object(worker, "_quality_check", side_effect=quality), mock.patch.object(worker, "_publish_unit", side_effect=publish), mock.patch.object(worker, "_unit_report", side_effect=lambda _d, row: reports[row["unit_index"]]), mock.patch.object(worker, "parent_quality", side_effect=[{"ok": False}, {"ok": True}]), mock.patch.object(worker, "choose_repair_unit", return_value=rows[0]), mock.patch.object(worker, "_assemble_parent_from_units", side_effect=lambda *args: assembled.append(args)):
                worker.run_generate(job)
        self.assertEqual(published, [(0, 1), (1, 1), (0, 2)])
        self.assertEqual(len(assembled), 1)
