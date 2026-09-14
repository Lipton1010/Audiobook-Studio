import unittest
import json
import tempfile
from pathlib import Path
from unittest import mock
import sys


APP_DIR = Path(__file__).resolve().parents[1] / "app"
sys.path.insert(0, str(APP_DIR))


try:
    import numpy as np
    from vibevoice_audio import mono_24k
    import soundfile as sf
    import vibevoice_worker as worker
except ModuleNotFoundError:
    np = None


@unittest.skipUnless(np is not None, "requires the isolated VibeVoice runtime")
class VibeVoiceRuntimeAudioTests(unittest.TestCase):
    def test_reference_wav_conversion_needs_no_ffmpeg(self):
        stereo = np.array([[0.0, 1.0], [1.0, 0.0], [0.5, 0.5]], dtype=np.float32)
        converted = mono_24k(stereo, 24000)
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
                 mock.patch.object(worker, "_load_model", side_effect=AssertionError("must not load")):
                worker.run_generate(job)
            progress = json.loads((job / worker.PROGRESS_FILE).read_text(encoding="utf-8"))
            self.assertEqual(progress, {"done": 1, "total": 1, "shard": 0, "status": "complete"})
