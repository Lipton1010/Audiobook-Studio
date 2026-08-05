import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock


APP_DIR = Path(__file__).resolve().parents[1] / "app"
sys.path.insert(0, str(APP_DIR))
sys.modules.setdefault("fitz", types.ModuleType("fitz"))

import server


class PlanIdentityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.job_dir = Path(self.temp.name)
        self.voice = self.job_dir / "voice.wav"
        self.voice.write_bytes(b"voice")
        self.state = {"id": "test-job", "path": "A", "voice": "Test"}
        self.voice_patch = mock.patch.object(
            server, "voice_wav_path", return_value=str(self.voice)
        )
        self.voice_patch.start()

    def tearDown(self):
        self.voice_patch.stop()
        self.temp.cleanup()

    def write_blocks(self, blocks):
        (self.job_dir / "blocks.json").write_text(
            json.dumps({"blocks": blocks}, indent=2), encoding="utf-8"
        )

    def test_page_provenance_does_not_invalidate_audio_segments(self):
        self.write_blocks([
            {"type": "body", "text": "Same spoken words.", "source_page": 8}
        ])
        with_provenance = server._plan_hash(self.job_dir, self.state)

        self.write_blocks([{"type": "body", "text": "Same spoken words."}])
        without_provenance = server._plan_hash(self.job_dir, self.state)

        self.assertEqual(with_provenance, without_provenance)

    def test_spoken_text_change_invalidates_audio_segments(self):
        self.write_blocks([{"type": "body", "text": "First text."}])
        first = server._plan_hash(self.job_dir, self.state)
        self.write_blocks([{"type": "body", "text": "Changed text."}])
        second = server._plan_hash(self.job_dir, self.state)
        self.assertNotEqual(first, second)

    def test_matching_legacy_hash_migrates_without_deleting_segments(self):
        self.write_blocks([{"type": "body", "text": "Existing narration."}])
        segment_dir = self.job_dir / "segments"
        segment_dir.mkdir()
        segment = segment_dir / "seg_000000.wav"
        segment.write_bytes(b"validated-segment")
        (self.job_dir / "plan_hash.txt").write_text(
            server._legacy_plan_hash(self.job_dir, self.state), encoding="utf-8"
        )

        with mock.patch.object(server, "log_line"):
            server.ensure_segments_fresh(self.job_dir, self.state)

        self.assertTrue(segment.exists())
        migrated = (self.job_dir / "plan_hash.txt").read_text(encoding="utf-8")
        self.assertTrue(migrated.startswith("v2:"))


if __name__ == "__main__":
    unittest.main()
