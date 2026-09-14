import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from install import bootstrap_vibevoice as bootstrap


class VibeVoiceSetupTests(unittest.TestCase):
    def test_register_preserves_unrelated_configuration(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'config.json'
            path.write_text(json.dumps({'port': 8768, 'chatterbox_python': 'existing.exe'}))
            bootstrap.register(path, {'vibevoice_python': Path(directory) / 'new.exe'})
            saved = json.loads(path.read_text())
            self.assertEqual(saved['port'], 8768)
            self.assertEqual(saved['chatterbox_python'], 'existing.exe')
            self.assertEqual(saved['vibevoice_python'], str(Path(directory) / 'new.exe'))

    def test_invalid_existing_config_is_not_replaced(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'config.json'
            path.write_text('not json')
            with self.assertRaises(ValueError):
                bootstrap.register(path, {'vibevoice_python': 'new.exe'})
            self.assertEqual(path.read_text(), 'not json')

    def test_unowned_environment_is_never_modified(self):
        with tempfile.TemporaryDirectory() as directory:
            prefix = Path(directory)
            python = prefix / ('python.exe' if bootstrap.os.name == 'nt' else 'bin/python')
            python.parent.mkdir(exist_ok=True)
            python.write_text('existing interpreter')
            with patch.object(bootstrap, 'run') as run:
                with self.assertRaisesRegex(ValueError, 'unowned'):
                    bootstrap.create_environment('conda', prefix, 'vibevoice')
                run.assert_not_called()
            self.assertEqual(python.read_text(), 'existing interpreter')

    def test_interrupted_owned_environment_is_repaired_without_claiming_others(self):
        with tempfile.TemporaryDirectory() as directory:
            prefix = Path(directory) / 'runtime' / 'vibevoice'
            prefix.mkdir(parents=True)
            (prefix / 'partial.txt').write_text('interrupted conda create')
            staging = prefix.with_name(prefix.name + '.storybird-provisioning.json')
            staging.write_text(json.dumps({
                'kind': 'vibevoice', 'python': '3.11', 'prefix': str(prefix.resolve())}))
            python = prefix / ('python.exe' if bootstrap.os.name == 'nt' else 'bin/python')
            python.parent.mkdir(parents=True, exist_ok=True)
            python.write_text('partial interpreter')

            def finish_create(command, **kwargs):
                python.parent.mkdir(parents=True, exist_ok=True)
                python.write_text('owned interpreter')

            with patch.object(bootstrap, 'run', side_effect=finish_create) as run:
                self.assertEqual(bootstrap.create_environment('conda', prefix, 'vibevoice'), python)
                run.assert_called_once()
            self.assertTrue((prefix / '.storybird-runtime.json').is_file())
            self.assertFalse(staging.exists())

    def test_unowned_partial_environment_is_not_removed(self):
        with tempfile.TemporaryDirectory() as directory:
            prefix = Path(directory) / 'vibevoice'
            prefix.mkdir()
            partial = prefix / 'partial.txt'
            partial.write_text('do not delete')
            with self.assertRaisesRegex(ValueError, 'unowned'):
                bootstrap.create_environment('conda', prefix, 'vibevoice')
            self.assertEqual(partial.read_text(), 'do not delete')

    def test_install_configures_managed_cache_before_creating_environments(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / 'runtime'
            created = [root / 'vibevoice/python.exe', root / 'quality/python.exe']
            with patch.object(sys, 'argv', ['bootstrap_vibevoice.py', '--install', '--conda', 'conda',
                                            '--runtime-root', str(root), '--config', str(Path(directory) / 'config.json')]), \
                 patch.object(bootstrap, 'configure_managed_runtime') as configure, \
                 patch.object(bootstrap, 'create_environment', side_effect=created), \
                 patch.object(bootstrap, 'run'), \
                 patch.object(bootstrap, 'verify'), \
                 patch.object(bootstrap, 'register'):
                bootstrap.main()
            configure.assert_called_once_with(root.resolve(), create_dirs=True)

    def test_existing_runtime_checks_do_not_create_managed_cache(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / 'runtime'
            with patch.object(sys, 'argv', ['bootstrap_vibevoice.py', '--check-only',
                                            '--runtime-root', str(root), '--python', 'voice-python',
                                            '--quality-python', 'quality-python']), \
                 patch.object(bootstrap, 'configure_managed_runtime') as configure, \
                 patch.object(bootstrap, 'verify'):
                bootstrap.main()
            configure.assert_not_called()

    def test_incomplete_or_wrong_model_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'model.safetensors.index.json').write_text(json.dumps({'weight_map': {'weight': 'part.safetensors'}}))
            (root / 'config.json').write_text(json.dumps({'decoder_config': {'hidden_size': 1536}}))
            (root / 'preprocessor_config.json').write_text('{}')
            with self.assertRaisesRegex(ValueError, 'part.safetensors'):
                bootstrap.validate_models(root, root)
            (root / 'part.safetensors').write_bytes(b'test')
            for filename in ['model.bin', 'tokenizer.json']:
                (root / filename).write_bytes(b'test')
            bootstrap.validate_models(root, root)
            (root / 'config.json').write_text(json.dumps({'decoder_config': {'hidden_size': 4096}}))
            with self.assertRaisesRegex(ValueError, '1.5B'):
                bootstrap.validate_models(root, root)

    def test_revisions_are_immutable_commit_ids(self):
        for revision in [bootstrap.SOURCE_REVISION, bootstrap.MODEL_REVISION,
                         bootstrap.TOKENIZER_REVISION, bootstrap.QUALITY_REVISION]:
            self.assertRegex(revision, r'^[0-9a-f]{40}$')


if __name__ == '__main__':
    unittest.main()
