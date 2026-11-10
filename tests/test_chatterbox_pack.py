import hashlib
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch

from app import chatterbox_pack as pack
from install import bootstrap_chatterbox as setup


class ChatterboxPackTests(unittest.TestCase):
    def test_manifest_has_pinned_artifacts(self):
        manifest = pack.manifest()
        self.assertEqual(len(manifest['revision']), 40)
        self.assertEqual(manifest['repo'], 'ResembleAI/chatterbox')
        for item in manifest['files']:
            self.assertEqual(Path(item['name']).name, item['name'])
            self.assertEqual(len(item['sha256']), 64)
            self.assertGreater(item['bytes'], 0)

    def test_verified_local_loading_and_corruption_refusal(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); (root / 'weights').write_bytes(b'ok')
            manifest = {'files': [{'name': 'weights', 'bytes': 2, 'sha256': hashlib.sha256(b'ok').hexdigest()}]}
            model = Mock()
            with patch.object(pack, 'manifest', return_value=manifest):
                pack.load_local(model, root)
                model.from_local.assert_called_once_with(root, device='cuda')
                (root / 'weights').write_bytes(b'no')
                with self.assertRaisesRegex(ValueError, 'checksum mismatch'):
                    pack.load_local(model, root)
                self.assertEqual(model.from_local.call_count, 1)

    def test_legacy_loading_never_downloads(self):
        download = Mock(side_effect=lambda **kw: '/cache/snapshot/' + kw['filename'])
        hub = types.SimpleNamespace(hf_hub_download=download)
        with patch.dict(sys.modules, {'huggingface_hub': hub}):
            model = Mock(); pack.load_local(model)
        self.assertEqual(download.call_count, 5)
        self.assertTrue(all(c.kwargs['local_files_only'] for c in download.call_args_list))
        model.from_pretrained.assert_not_called()

    def test_missing_legacy_cache_does_not_load(self):
        hub = types.SimpleNamespace(hf_hub_download=Mock(side_effect=OSError('missing')))
        with patch.dict(sys.modules, {'huggingface_hub': hub}):
            model = Mock()
            with self.assertRaisesRegex(RuntimeError, 'no model was downloaded'):
                pack.load_local(model)
            model.from_local.assert_not_called()

    def test_register_preserves_narrator_and_rejects_existing_runtime(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / 'app/config.json'; p.parent.mkdir()
            p.write_text(json.dumps({'narrator_backend': 'vibevoice', 'custom': 7}))
            setup.register(p, Path(tmp) / 'python.exe', Path(tmp) / 'model')
            data = json.loads(p.read_text())
            self.assertEqual(data['narrator_backend'], 'vibevoice')
            self.assertEqual(data['custom'], 7)
            before = p.read_bytes()
            with self.assertRaisesRegex(ValueError, 'not replaced'):
                setup.register(p, Path(tmp) / 'other.exe', Path(tmp) / 'other')
            self.assertEqual(p.read_bytes(), before)

    def test_legacy_jobs_block_implicit_runtime_change(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); job = root / 'jobs/old'; job.mkdir(parents=True)
            (job / 'config.json').write_text('{"reference_wav":"retained"}')
            target = root / 'app/config.json'
            with self.assertRaisesRegex(ValueError, 'legacy narration jobs'):
                setup.register(target, root / 'new.exe', root / 'model')
            self.assertFalse(target.exists())
            self.assertEqual((job / 'config.json').read_text(), '{"reference_wav":"retained"}')

    def test_windows_lock_and_patch_include_optional_assets(self):
        root = Path(__file__).resolve().parents[1]
        lock = (root / "install/requirements-chatterbox-win311.lock.txt").read_text()
        soundfile = next(line for line in lock.splitlines() if line.startswith("soundfile @"))
        self.assertIn("win_amd64.whl", soundfile)
        self.assertIn("--hash=sha256:", soundfile)
        patch = (root / "install/AudiobookStudio_Patch.iss").read_text()
        for name in ("chatterbox_pack.py", "bootstrap_chatterbox.py", "chatterbox-pack.json", "requirements-chatterbox-win311.lock.txt", "CHATTERBOX_DEPENDENCIES.md"):
            self.assertIn(name, patch)

    def test_no_consent_no_install(self):
        with patch.object(sys, 'argv', ['setup', '--install']), patch.object(setup, 'create_runtime') as create:
            with self.assertRaises(SystemExit): setup.main()
            create.assert_not_called()


if __name__ == '__main__': unittest.main()
