import sys
import tempfile
import unittest
from unittest import mock

from pathlib import Path

try:
    import numpy as np
    import soundfile as sf
except ModuleNotFoundError:
    np = sf = None


APP_DIR = Path(__file__).resolve().parents[1] / "app"
sys.path.insert(0, str(APP_DIR))

from assembly_metadata import is_outline_chapter_title, outline_chapter_marks
try:
    import vibevoice_assembly
except ModuleNotFoundError:
    vibevoice_assembly = None


class AssemblyMetadataTests(unittest.TestCase):
    def test_chapter_title_filter_excludes_decimal_sections(self):
        self.assertTrue(is_outline_chapter_title("PART ONE: Prefatory Matters"))
        self.assertTrue(is_outline_chapter_title("58 - Epilogue/Summer"))
        self.assertTrue(is_outline_chapter_title("Chapter Six"))
        self.assertFalse(is_outline_chapter_title("1.2 Installation"))
        self.assertFalse(is_outline_chapter_title("Character Creation"))

    @unittest.skipUnless(vibevoice_assembly is not None and np is not None, "requires the isolated VibeVoice runtime")
    def test_numbered_detected_heading_emits_m4b_chapter_metadata(self):
        with tempfile.TemporaryDirectory() as temp:
            job = Path(temp)
            source = job / "heading.wav"
            sf.write(source, np.full(2401, 0.02, dtype=np.float32), 24000)
            observed = {}

            def encode(_fmt, _chunks, _sr, output, metadata, _log, _cover):
                observed["ffmeta"] = Path(metadata).read_text(encoding="utf-8")
                Path(output).write_bytes(b"synthetic m4b")

            passages = [{"index": 0, "heading": "1: CHAPTER ONE", "before_ms": 0, "after_ms": 0, "source_pages": []}]
            config = {"format": "m4b", "title": "synthetic"}
            with mock.patch.object(vibevoice_assembly, "_encode", side_effect=encode):
                vibevoice_assembly.assemble(job, passages, config, lambda _index: source)
            self.assertIn("[CHAPTER]", observed["ffmeta"])
            self.assertIn("title=1: CHAPTER ONE", observed["ffmeta"])

    def test_outline_maps_to_first_audio_on_or_after_destination_page(self):
        outline = [
            {"level": 1, "title": "PART ONE", "page": 5},
            {"level": 2, "title": "1 - Opening", "page": 7},
            {"level": 2, "title": "2 - Next", "page": 10},
        ]
        page_starts = [(5, 0), (7, 15_000), (11, 45_000)]

        self.assertEqual(
            outline_chapter_marks(outline, page_starts),
            [(0, "PART ONE"), (15_000, "1 - Opening"), (45_000, "2 - Next")],
        )

    def test_deeper_entry_wins_when_two_destinations_share_audio_time(self):
        outline = [
            {"level": 1, "title": "PART ONE", "page": 5},
            {"level": 2, "title": "1 - Opening", "page": 5},
        ]
        self.assertEqual(
            outline_chapter_marks(outline, [(5, 0)]),
            [(0, "1 - Opening")],
        )


if __name__ == "__main__":
    unittest.main()
