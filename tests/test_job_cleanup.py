import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest import mock
import wave

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))
import job_cleanup as cleanup


class JobCleanupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=os.environ.get('AUDIOBOOK_TEST_TMP'))
        self.addCleanup(self.temp.cleanup)
        self.job = Path(self.temp.name) / 'job'; self.job.mkdir()
        (self.job / 'output').mkdir()
        (self.job / 'output/book.m4b').write_bytes(b'finished')
        self.state = {'id': 'fixture', 'status': 'done'}
        self.validator = mock.patch.object(cleanup, 'validate_audio', return_value=1.0)
        self.validator.start(); self.addCleanup(self.validator.stop)
        self.audio = self.file('vibevoice_segments/units/unit_1.wav', b'pcm')

    def file(self, name, value=b'keep'):
        path = self.job / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(value)
        return path

    def preview(self):
        return cleanup.preview(self.job, self.state, 'fixture-ffmpeg')

    def remove(self, plan):
        return cleanup.remove_preview(self.job, self.state, plan['token'], 'fixture-ffmpeg', confirmed=True)

    def test_preview_never_deletes_and_retains_sources_models_voices_receipts_and_finals(self):
        keep = [self.file(n) for n in ('source.pdf', 'blocks.json', 'vibevoice_segments/units/unit_1.json',
                'model.gguf', 'drama3_reference.wav', 'log.txt', 'drama3_runs/one/run.json')]
        log = self.file('drama3_runs/one/native.log', b'log')
        plan = self.preview()
        self.assertEqual(plan['files_count'], 2)
        self.assertTrue(self.audio.exists() and log.exists())
        self.assertFalse(plan['automatic_deletion'])
        self.assertEqual(self.remove(plan), 6)
        self.assertTrue(all(p.exists() for p in keep))
        self.assertTrue((self.job / 'output/book.m4b').exists())
        self.assertFalse(self.audio.exists() or log.exists())
        ledger = cleanup.read(next((self.job / 'cleanup_history').glob('*.json')))
        self.assertTrue(ledger['complete'])
        self.assertEqual(len(ledger['approved_files']), 2)

    def test_failed_in_progress_or_unresolved_jobs_retain_everything(self):
        for status in ('failed', 'narrating', 'queued', 'canceled', 'assembling'):
            self.state['status'] = status
            with self.assertRaisesRegex(ValueError, 'completed jobs'): self.preview()
        self.state['status'] = 'done'
        self.file('narration_review.json', b'{"passages": [{}]}')
        with self.assertRaisesRegex(ValueError, 'review'): self.preview()
        self.assertTrue(self.audio.exists())

    def test_missing_or_invalid_finished_audio_blocks_cleanup(self):
        with mock.patch.object(cleanup, 'validate_audio', side_effect=ValueError('decode failed')):
            with self.assertRaisesRegex(ValueError, 'decode failed'): self.preview()
        (self.job / 'output/book.m4b').unlink()
        with self.assertRaisesRegex(ValueError, 'No finished'): self.preview()
        self.assertTrue(self.audio.exists())

    def test_publication_must_match_owner_and_content(self):
        library = Path(self.temp.name) / 'library'; library.mkdir()
        self.state['audiobook_dir'] = str(library)
        (library / '.storybird-job.json').write_text('{"job_id":"fixture"}')
        (library / 'book.m4b').write_bytes(b'wrong')
        with self.assertRaisesRegex(ValueError, 'differs'): self.preview()
        (library / 'book.m4b').write_bytes(b'finished')
        self.assertTrue(self.preview()['token'])
        (library / '.storybird-job.json').write_text('{"job_id":"other"}')
        with self.assertRaisesRegex(ValueError, 'ownership'): self.preview()

    def test_stale_preview_and_changed_final_refuse_before_first_unlink(self):
        plan = self.preview(); self.audio.write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'changed'): self.remove(plan)
        self.assertTrue(self.audio.exists())
        plan = self.preview(); (self.job / 'output/book.m4b').write_bytes(b'revised-final')
        with self.assertRaisesRegex(ValueError, 'changed'): self.remove(plan)
        self.assertTrue(self.audio.exists())

    def test_explicit_confirmation_required_before_any_scan(self):
        with mock.patch.object(cleanup, 'preview', side_effect=AssertionError('scan too early')):
            with self.assertRaisesRegex(ValueError, 'explicitly confirm'):
                cleanup.remove_preview(self.job, self.state, 'token', 'fixture')

    def test_reference_hardlink_is_preserved_even_with_generated_filename(self):
        source = self.file('chosen.wav')
        linked = self.job / 'vibevoice_segments/units/unit_2.wav'
        os.link(source, linked)
        self.file('vibevoice_config.json', json.dumps({'source_reference_wav': str(source)}).encode())
        self.remove(self.preview())
        self.assertTrue(source.exists() and linked.exists())

    def test_junction_or_symbolic_link_never_traversed(self):
        other = Path(self.temp.name) / 'outside'; other.mkdir(); (other / 'original.wav').write_bytes(b'keep')
        try: (self.job / 'drama3_runs').symlink_to(other, target_is_directory=True)
        except OSError: self.skipTest('symlink creation unavailable without privileges')
        with self.assertRaises(ValueError): self.preview()
        self.assertTrue((other / 'original.wav').exists())

    def test_partial_failure_keeps_exact_approved_scope_and_removed_ledger(self):
        second = self.file('vibevoice_segments/units/unit_2.wav', b'pcm2')
        plan = self.preview(); original = Path.unlink
        def unlink(path, *args, **kwargs):
            if path == second: raise OSError('fixture locked file')
            return original(path, *args, **kwargs)
        with mock.patch.object(Path, 'unlink', unlink):
            with self.assertRaises(OSError): self.remove(plan)
        ledger = cleanup.read(next((self.job / 'cleanup_history').glob('*.json')))
        self.assertFalse(ledger['complete'])
        self.assertEqual(len(ledger['removed']), 1)
        self.assertEqual(len(ledger['approved_files']), 2)
        self.assertTrue(second.exists())


class RealDecodeTests(unittest.TestCase):
    def test_real_pcm_decodes_and_corrupt_audio_fails(self):
        executable = shutil.which('ffmpeg')
        if not executable: self.skipTest('FFmpeg unavailable')
        with tempfile.TemporaryDirectory(dir=os.environ.get('AUDIOBOOK_TEST_TMP')) as folder:
            path = Path(folder) / 'fixture.wav'
            with wave.open(str(path), 'wb') as stream:
                stream.setnchannels(1); stream.setsampwidth(2); stream.setframerate(16000)
                stream.writeframes(b'\0\0' * 1600)
            self.assertGreater(cleanup.validate_audio(path, executable), 0)
            path.write_bytes(b'broken audio')
            with self.assertRaises(ValueError): cleanup.validate_audio(path, executable)


if __name__ == '__main__': unittest.main(verbosity=2)
