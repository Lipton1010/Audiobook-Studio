import importlib.util,unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('portable_config',ROOT/'app/config.py');module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
class PrivacyTests(unittest.TestCase):
    def test_missing_legacy_environment_falls_back_to_current_user(self):
        with patch.object(module.os.path,'expanduser',return_value='C:/Users/TestPerson'),patch.object(module.Path,'exists',return_value=False):
            path=module._find_chatterbox_python(ROOT)
        self.assertEqual(Path(path),Path('C:/Users/TestPerson/miniconda3/envs/chatterbox/python.exe'))
    def test_installer_excludes_internal_handoff_documents(self):
        script=(ROOT/'install/AudiobookStudio.iss').read_text(encoding='utf-8-sig')
        for name in ['\\CLAUDE.md','\\AGENTS.md','\\handoff.md','\\PROJECT_STATE.md']:
            self.assertIn(name,script)
