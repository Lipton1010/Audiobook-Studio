import importlib.util,os,tempfile,types,unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('core_setup_checked',ROOT/'setup.py');setup=importlib.util.module_from_spec(spec);spec.loader.exec_module(setup)
class CoreRuntimeTests(unittest.TestCase):
 @unittest.skipUnless(os.name=='nt','Windows private runtime PATH')
 def test_pip_uses_only_private_runtime_and_windows_path(self):
  with tempfile.TemporaryDirectory() as folder:
   base=Path(folder)/'private';conda=base/'Scripts/conda.exe'
   with patch.dict(os.environ,{'PATH':'Z:\\unrelated-user-tool'}),patch.object(setup,'run',return_value=types.SimpleNamespace(returncode=0)) as run:
    self.assertTrue(setup.setup_base_env(str(conda)))
    self.assertNotIn('unrelated-user-tool',run.call_args.kwargs['env']['PATH'])
    self.assertIn(str(base),run.call_args.kwargs['env']['PATH'])
    self.assertEqual(os.environ['PATH'],'Z:\\unrelated-user-tool')
 def test_miniforge_pin_matches_inno_and_preserves_old_folder(self):
  bootstrap=(ROOT/'install/bootstrap_conda.py').read_text(encoding='utf-8')
  inno=(ROOT/'install/AudiobookStudio.iss').read_text(encoding='utf-8-sig')
  for value in ('26.9.4-2','9d83983669bc5d3b5dd4c631454bf953c3caf4ac78b9c9ada9971e5b021d83c3','/NoRegistry=1','/NoShortcuts=1'):
   self.assertIn(value,bootstrap);self.assertIn(value,inno)
  self.assertIn(r'{app}\runtime\miniconda3\python.exe',inno)
if __name__=='__main__':unittest.main()
