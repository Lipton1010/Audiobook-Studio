import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("drama_setup", ROOT / "install/bootstrap_drama3.py")
setup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(setup)


class DramaSetupTests(unittest.TestCase):
    def test_legacy_and_portable_assets_keep_their_distinct_bindings(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            for name in ('native.exe','model.gguf','cuda.dll'):
                (root/name).write_bytes(b'synthetic')
            config={'drama3_executable':str(root/'native.exe'),'drama3_model':str(root/'model.gguf'),'drama3_cuda_bin':str(root)}
            for digest in (setup.drama3.EXE_SHA256,setup.drama3.PORTABLE_EXE_SHA256,'0'*64):
                hashes={'native.exe':digest,'model.gguf':setup.drama3.MODEL_SHA256,'cuda.dll':'1'*64}
                with patch.object(setup.drama3,'sha256_file',side_effect=lambda p:hashes[Path(p).name]):
                    if digest=='0'*64:
                        with self.assertRaises(ValueError):setup.drama3.assets(config,verify=True)
                    else:
                        self.assertEqual(setup.drama3.assets(config,verify=True)[0]['sha256'],digest)
    def test_registration_preserves_default_and_unrelated_settings(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "config.json"
            path.write_text(json.dumps({"narration_backend": "vibevoice", "private_setting": "preserve"}))
            setup.register(path, {"drama3_model": "verified-existing.gguf"})
            data = json.loads(path.read_text())
            self.assertEqual(data['narration_backend'], 'vibevoice')
            self.assertEqual(data['private_setting'], 'preserve')
            self.assertEqual(data['drama3_model'], 'verified-existing.gguf')
            self.assertEqual([x.name for x in Path(temporary).iterdir()], ['config.json'])

    def test_pack_uses_verified_published_runtime(self):
        manifest = json.loads((ROOT / "install/drama3-pack.json").read_text())
        self.assertEqual(manifest['runtime']['download_url'], 'https://github.com/Lipton1010/Audiobook-Studio/releases/download/drama-runtime-4e6018f-win64-ada-beta.1/Drama3-runtime-win64-ada-candidate.zip')
        self.assertEqual(manifest['runtime']['archive']['sha256'], '8349aa257199f5f76ac8565e34a2b175cdb07d8f66b73b28da38b75ce8e5a960')
        self.assertEqual(manifest['runtime']['cuda_architectures'], ['8.9'])
        self.assertEqual(manifest['model']['bytes'], 20325196992)
        self.assertEqual(len(manifest['model']['sha256']), 64)
        self.assertTrue(manifest['release_gates'])


if __name__ == '__main__':
    unittest.main()
