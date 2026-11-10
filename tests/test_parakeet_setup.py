import importlib.util
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, Mock

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("bootstrap_parakeet", ROOT / "install/bootstrap_parakeet.py")
setup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(setup)


class ParakeetSetupTests(unittest.TestCase):
    def test_locked_conda_prefix_does_not_register_or_change_global_path(self):
        with tempfile.TemporaryDirectory() as folder:
            conda=Path(folder)/'conda.exe';conda.touch()
            target=Path(folder)/'checker'
            with patch.object(setup.sys, 'platform', 'win32'), patch.object(setup.subprocess, 'run') as run:
                result=setup.create_runtime(target, conda=conda)
            self.assertEqual(result,target/'python.exe')
            command=run.call_args.args[0]
            self.assertIn('--file',command)
            self.assertTrue(command[command.index('--file')+1].endswith('parakeet-python-win64.lock.txt'))
            self.assertEqual(run.call_args.kwargs['env']['CONDA_REGISTER_ENVS'],'false')

    def test_existing_runtime_is_never_replaced(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaisesRegex(ValueError,'already exists'):
                setup.create_runtime(Path(folder))

    def test_model_manifest_checks_configuration_and_rejects_tampering(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'config.json';path.write_bytes(b'{}')
            manifest={'files':[{'name':'config.json','bytes':2,'sha256':hashlib.sha256(b'{}').hexdigest()}]}
            setup.verify_model_files(folder,manifest)
            path.write_bytes(b'[]')
            with self.assertRaisesRegex(ValueError,'checksum'):
                setup.verify_model_files(folder,manifest)
            manifest['files'][0]['name']='../config.json'
            with self.assertRaisesRegex(ValueError,'filename'):
                setup.verify_model_files(folder,manifest)
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
