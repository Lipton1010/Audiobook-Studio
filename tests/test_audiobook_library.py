import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))
import audiobook_library as library


class FinishedLibraryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.job = self.root / 'jobs' / 'one'
        self.output = self.job / 'output'
        self.output.mkdir(parents=True)
        self.books = self.root / 'books'
        self.books.mkdir()
        self.state = {'id':'one', 'title':'Same title'}
        (self.output / 'book.m4b').write_bytes(b'new audio')

    def test_same_title_publication_and_republication_preserve_all_versions(self):
        first = library.publish_finished_output(self.output, self.books, self.state)
        (self.output / 'book.m4b').write_bytes(b'second audio')
        other = library.publish_finished_output(self.output, self.books, {'id':'two', 'title':'Same title'})
        again = library.publish_finished_output(self.output, self.books, self.state)
        self.assertEqual(len({first, other, again}), 3)
        self.assertEqual((first / 'book.m4b').read_bytes(), b'new audio')
        self.assertEqual((other / 'book.m4b').read_bytes(), b'second audio')
        self.assertEqual(json.loads((again / '.storybird-job.json').read_text())['job_id'], 'one')

    def test_partial_copy_failure_preserves_old_output_and_removes_stage(self):
        def fail(source, target):
            Path(target).write_bytes(b'partial')
            raise OSError('synthetic disk failure')
        with patch.object(library.shutil, 'copy2', side_effect=fail):
            with self.assertRaises(OSError):
                library.publish_finished_output(self.output, self.books, self.state)
        self.assertEqual(list(self.books.iterdir()), [])
        self.assertEqual((self.output / 'book.m4b').read_bytes(), b'new audio')

    def test_delete_preserves_original_pdf_voices_extraction_and_logs(self):
        book_dir = library.publish_finished_output(self.output, self.books, self.state)
        self.state['audiobook_dir'] = str(book_dir)
        segments = self.job / 'vibevoice_segments'
        segments.mkdir()
        (segments / 'seg.wav').write_bytes(b'segment')
        (segments / 'seg.json').write_text('{}')
        keep = [self.job / 'source.pdf', self.output / 'original.pdf', self.job / 'voice.wav',
                self.job / 'source_blocks.json', self.job / 'log.txt']
        for path in keep:
            path.write_bytes(b'preserved')
        freed = library.delete_generated_files(self.job, self.state, self.books, [self.state])
        self.assertGreater(freed, 0)
        self.assertFalse((self.output / 'book.m4b').exists())
        self.assertFalse((book_dir / 'book.m4b').exists())
        self.assertFalse((segments / 'seg.json').exists())
        for path in keep:
            self.assertEqual(path.read_bytes(), b'preserved')

    def test_shared_or_external_directory_refused_before_any_deletion(self):
        book_dir = library.publish_finished_output(self.output, self.books, self.state)
        self.state['audiobook_dir'] = str(book_dir)
        with self.assertRaises(ValueError):
            library.delete_generated_files(self.job, self.state, self.books,
                [self.state, {'id':'two', 'audiobook_dir':str(book_dir)}])
        self.assertTrue((self.output / 'book.m4b').exists())
        self.state['audiobook_dir'] = str(self.root)
        with self.assertRaises(ValueError):
            library.delete_generated_files(self.job, self.state, self.books, [self.state])
        self.assertTrue((self.output / 'book.m4b').exists())

    def test_hidden_artwork_backups_are_not_visible_exports(self):
        hidden = self.output / '.book.artwork.backup.m4b'
        hidden.write_bytes(b'backup')
        self.assertFalse(library.visible_audio(hidden))
        target = library.publish_finished_output(self.output, self.books, self.state)
        self.assertFalse((target / hidden.name).exists())

    def test_markerless_legacy_copy_requires_matching_job_audio_then_claims_it(self):
        legacy = self.books / 'Legacy'
        legacy.mkdir()
        (legacy / 'book.m4b').write_bytes(b'new audio')
        self.state['audiobook_dir'] = str(legacy)
        self.assertEqual(library.owned_library_directory(self.state, self.books, [self.state], self.job), legacy)
        self.assertEqual(json.loads((legacy / '.storybird-job.json').read_text())['job_id'], 'one')

    def test_wrong_or_malformed_marker_preserves_library_audio(self):
        for contents in ('{"job_id":"other"}', 'not json'):
            with self.subTest(contents=contents):
                directory = self.books / str(abs(hash(contents)))
                directory.mkdir()
                audio = directory / 'book.m4b'
                audio.write_bytes(b'new audio')
                (directory / '.storybird-job.json').write_text(contents)
                self.state['audiobook_dir'] = str(directory)
                with self.assertRaises(ValueError):
                    library.delete_generated_files(self.job, self.state, self.books, [self.state])
                self.assertEqual(audio.read_bytes(), b'new audio')

    def test_partial_unlink_failure_reports_progress_and_preserves_remaining_audio(self):
        second = self.output / 'second.mp3'
        second.write_bytes(b'second')
        original_unlink = Path.unlink

        def fail_second(path, *args, **kwargs):
            if Path(path) == second:
                raise PermissionError('synthetic lock')
            return original_unlink(path, *args, **kwargs)

        with patch.object(Path, 'unlink', fail_second):
            with self.assertRaisesRegex(OSError, 'Removed 1 of 2'):
                library.delete_generated_files(self.job, self.state, self.books, [self.state])
        self.assertTrue(second.exists())

    def test_link_or_junction_warning_preserves_generated_files(self):
        with patch.object(library, '_safe_deletion_path', side_effect=ValueError('junction')):
            with self.assertRaises(ValueError):
                library.delete_generated_files(self.job, self.state, self.books, [self.state])
        self.assertTrue((self.output / 'book.m4b').exists())


if __name__ == '__main__':
    unittest.main()
