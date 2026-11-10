import importlib.util,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('pack_install',ROOT/'install/install_drama_runtime_pack.py');module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
class DramaPackTests(unittest.TestCase):
    def test_requires_explicit_terms_and_preserves_existing_target(self):
        with tempfile.TemporaryDirectory() as folder:
            target=Path(folder)/'existing';target.mkdir();sentinel=target/'keep';sentinel.write_text('preserved')
            with self.assertRaisesRegex(ValueError,'acknowledge'):module.install_pack('missing',target)
            with self.assertRaisesRegex(ValueError,'exists'):module.install_pack('missing',target,True)
            self.assertEqual(sentinel.read_text(),'preserved')
    def test_rejects_untrusted_archive_before_extracting(self):
        with tempfile.TemporaryDirectory() as folder:
            archive=Path(folder)/'bad.zip';archive.write_bytes(b'not the reviewed archive');target=Path(folder)/'new'
            with self.assertRaisesRegex(ValueError,'checksum'):module.install_pack(archive,target,True)
            self.assertFalse(target.exists())
