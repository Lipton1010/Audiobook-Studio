import sys
import types
import unittest
from pathlib import Path


APP_DIR = Path(__file__).resolve().parents[1] / "app"
sys.path.insert(0, str(APP_DIR))
sys.modules.setdefault("fitz", types.ModuleType("fitz"))

import pipeline_text


class PipelineProvenanceTests(unittest.TestCase):
    def test_path_a_blocks_record_source_page(self):
        blocks = pipeline_text.paragraphs_to_blocks(
            ["Chapter One", "Opening body."], source_page=7
        )
        self.assertEqual([block["source_page"] for block in blocks], [7, 7])

    def test_cross_page_stitch_records_source_span(self):
        merged = pipeline_text.stitch_pages([
            [{"type": "body", "text": "A sentence that", "source_page": 7}],
            [{"type": "body", "text": "continues here.", "source_page": 8}],
        ])
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["source_page"], 7)
        self.assertEqual(merged[0]["source_page_end"], 8)
        self.assertEqual(merged[0]["text"], "A sentence that continues here.")


if __name__ == "__main__":
    unittest.main()
