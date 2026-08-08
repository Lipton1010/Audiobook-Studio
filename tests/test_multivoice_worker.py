import json
import sys
import tempfile
import types
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP_DIR = ROOT / "app"
TEST_DIR = ROOT / "tests"
sys.path[:0] = [str(APP_DIR), str(TEST_DIR)]

# narrate_worker normally imports these only inside the isolated Chatterbox
# environment.  Plan loading itself is stdlib-only, so stub the model import
# and watermarker while exercising the real worker branch in the base tests.
sys.modules.setdefault("numpy", types.ModuleType("numpy"))
sys.modules.setdefault("soundfile", types.ModuleType("soundfile"))
perth = types.ModuleType("perth")
perth.PerthImplicitWatermarker = object
sys.modules.setdefault("perth", perth)
chatterbox = types.ModuleType("chatterbox")
chatterbox_tts = types.ModuleType("chatterbox.tts")
chatterbox_tts.ChatterboxTTS = object
sys.modules.setdefault("chatterbox", chatterbox)
sys.modules.setdefault("chatterbox.tts", chatterbox_tts)

import narrate_worker
from test_multivoice_plan import make_plan


class MultiVoiceWorkerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.job_dir = Path(self.temp.name)
        self.blocks = [{
            "type": "body",
            "text": "“Go,” Mara said. “Wait,” Jon replied.",
            "source_page": 2,
        }]
        self.cast = make_plan(self.blocks, ["Mara", "Jon"])
        self.voice_paths = {}
        for name in ("Narrator Voice", "Mara Voice", "Jon Voice"):
            path = self.job_dir / f"{name}.wav"
            path.write_bytes(b"synthetic-reference")
            self.voice_paths[name] = str(path)
        (self.job_dir / "blocks.json").write_text(
            json.dumps({"blocks": self.blocks}), encoding="utf-8"
        )
        (self.job_dir / "cast_plan.json").write_text(
            json.dumps(self.cast), encoding="utf-8"
        )
        (self.job_dir / "config.json").write_text(json.dumps({
            "path": "A",
            "workflow": "cast_narration",
            "reference_wav": self.voice_paths["Narrator Voice"],
            "voice_paths": self.voice_paths,
        }), encoding="utf-8")

    def tearDown(self):
        self.temp.cleanup()

    def test_worker_loads_one_source_anchored_plan_with_voice_paths(self):
        plan, config, profile = narrate_worker.load_plan(self.job_dir)

        self.assertEqual(config["workflow"], "cast_narration")
        self.assertEqual(profile, narrate_worker.PAUSE_PROFILES["A"])
        self.assertEqual(
            {item["voice_name"] for item in plan},
            {"Narrator Voice", "Mara Voice", "Jon Voice"},
        )
        self.assertTrue(all(Path(item["voice_path"]).exists() for item in plan))

    def test_worker_rejects_deleted_assigned_voice_before_model_load(self):
        Path(self.voice_paths["Mara Voice"]).unlink()

        with self.assertRaisesRegex(RuntimeError, "Mara Voice.*missing"):
            narrate_worker.load_plan(self.job_dir)

    def test_single_voice_worker_plan_remains_unchanged(self):
        (self.job_dir / "config.json").write_text(json.dumps({
            "path": "A",
            "reference_wav": self.voice_paths["Narrator Voice"],
        }), encoding="utf-8")

        plan, _, profile = narrate_worker.load_plan(self.job_dir)

        self.assertEqual(
            plan,
            narrate_worker.build_plan(self.blocks, profile),
        )
        self.assertTrue(all("voice_path" not in item for item in plan))


if __name__ == "__main__":
    unittest.main()
