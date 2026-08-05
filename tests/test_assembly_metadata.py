import sys
import unittest
from pathlib import Path


APP_DIR = Path(__file__).resolve().parents[1] / "app"
sys.path.insert(0, str(APP_DIR))

from assembly_metadata import is_outline_chapter_title, outline_chapter_marks


class AssemblyMetadataTests(unittest.TestCase):
    def test_chapter_title_filter_excludes_decimal_sections(self):
        self.assertTrue(is_outline_chapter_title("PART ONE: Prefatory Matters"))
        self.assertTrue(is_outline_chapter_title("58 - Epilogue/Summer"))
        self.assertTrue(is_outline_chapter_title("Chapter Six"))
        self.assertFalse(is_outline_chapter_title("1.2 Installation"))
        self.assertFalse(is_outline_chapter_title("Character Creation"))

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
