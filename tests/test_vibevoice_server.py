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


class VibeVoiceServerTests(unittest.TestCase):
    def setUp(self):
        test_root = APP_DIR.parent / ".test-tmp"
        test_root.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=test_root)
        self.job_dir = Path(self.temp.name)
        self.voice = self.job_dir / "voice.wav"
        self.voice.write_bytes(b"voice")
        self.state = {
            "id": "vibe-test", "title": "Synthetic", "path": "A",
            "voice": "Synthetic", "format": "wav", "backend": "vibevoice",
            "pdf_path": str(self.job_dir / "book.pdf"),
        }

    def tearDown(self):
        self.temp.cleanup()

    def test_legacy_job_without_backend_stays_on_chatterbox(self):
        self.assertEqual(server.narration_backend({"engine": "batched"}), "chatterbox")

    def test_vibevoice_progress_uses_its_own_receipt_directory(self):
        (self.job_dir / "vibevoice_segments").mkdir()
        (self.job_dir / "vibevoice_progress.json").write_text(
            json.dumps({"done": 3, "total": 7, "status": "loading_model"}), encoding="utf-8"
        )
        progress = server._narration_progress(self.job_dir, self.state)
        self.assertEqual((progress["done"], progress["total"]), (3, 7))
        self.assertIn("loading model", progress["message"])

    def test_vibevoice_runs_one_worker_with_fixed_quality_settings(self):
        captured = {}

        def write_plan(job_dir, blocks, config):
            captured["blocks"] = blocks
            captured["config"] = config
            return {"passages": [{"index": 0}]}

        fake_plan = types.SimpleNamespace(write_plan=write_plan)
        worker = mock.Mock()
        worker.wait.return_value = 0
        with mock.patch.dict(sys.modules, {"vibevoice_plan": fake_plan}), \
             mock.patch.object(server, "voice_wav_path", return_value=str(self.voice)), \
             mock.patch.object(server, "extract_book_meta", return_value=({}, None, [])), \
             mock.patch.object(server, "save_state"), \
             mock.patch.object(server, "log_line"), \
             mock.patch.object(server, "_spawn_worker", return_value=worker) as spawn:
            server._run_vibevoice_narration(self.state, self.job_dir, [{"text": "Words."}])

        self.assertEqual(spawn.call_args_list[0].args[2], ["--shard", "0", "--num-shards", "1"])
        self.assertEqual(spawn.call_args_list[0].args[3], "vibevoice")
        self.assertEqual(spawn.call_args_list[1].args[2], ["--assemble"])
        self.assertEqual(captured["config"]["dtype"], "bfloat16")
        self.assertEqual(captured["config"]["cfg_scale"], 2.0)
        self.assertEqual(captured["config"]["ddpm_steps"], 20)
        self.assertEqual(captured["config"]["attention"], "sdpa")

    def test_voice_upload_prefers_vibevoice_runtime(self):
        vibe_python = self.job_dir / "vibevoice.exe"
        vibe_python.write_bytes(b"runtime")
        result = mock.Mock(returncode=0, stdout="ok", stderr="")
        with mock.patch.object(server, "VIBEVOICE_PY", str(vibe_python)), \
             mock.patch.object(server, "CHATTERBOX_PY", "missing-chatterbox.exe"), \
             mock.patch.object(server.subprocess, "run", return_value=result) as run:
            self.assertEqual(server.save_voice("Fresh", b"audio", ".wav"), "Fresh")
        self.assertEqual(run.call_args.args[0][0], str(vibe_python))


if __name__ == "__main__":
    unittest.main()
