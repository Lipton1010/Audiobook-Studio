import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("bootstrap_parakeet", ROOT / "install/bootstrap_parakeet.py")
setup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(setup)


class ParakeetSetupTests(unittest.TestCase):
    def test_registration_keeps_workflow_literal_and_preserves_other_settings(self):
        with tempfile.TemporaryDirectory(dir=ROOT / ".test-tmp") as folder:
            path = Path(folder) / "config.json"
            path.write_text(json.dumps({"port": 8765, "vibevoice_python": "legacy.exe"}), encoding="utf-8")
            setup.register(path, "runtime/parakeet/Scripts/python.exe", "runtime/models/parakeet")
            saved = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(saved["vibevoice_workflow"], "generate_first_parakeet_v1")
            self.assertEqual(saved["port"], 8765)
            self.assertEqual(saved["vibevoice_python"], "legacy.exe")
            self.assertTrue(Path(saved["parakeet_python"]).is_absolute())

    def test_corrupt_config_is_not_overwritten(self):
        with tempfile.TemporaryDirectory(dir=ROOT / ".test-tmp") as folder:
            path = Path(folder) / "config.json"
            path.write_text("corrupt", encoding="utf-8")
            with self.assertRaises(ValueError):
                setup.register(path, "python.exe", "model")
            self.assertEqual(path.read_text(encoding="utf-8"), "corrupt")
