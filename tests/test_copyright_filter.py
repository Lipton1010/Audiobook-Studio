import sys
import types
import unittest
from pathlib import Path


APP_DIR = Path(__file__).resolve().parents[1] / "app"
sys.path.insert(0, str(APP_DIR))
sys.modules.setdefault("fitz", types.ModuleType("fitz"))

import pipeline_text as pt


class CopyrightFilterTests(unittest.TestCase):
    def test_all_boilerplate_page_is_omitted(self):
        blocks = pt.paragraphs_to_blocks([
            "Copyright © 2025 Example Press.",
            "All rights reserved.",
            "ISBN 978-1-234-56789-0",
        ], source_page=1)
        self.assertEqual(pt.filter_copyright_blocks(blocks), [])

    def test_mixed_page_keeps_narrative_and_source_page(self):
        blocks = pt.paragraphs_to_blocks([
            "CHAPTER ONE",
            "Copyright © 2025 Example Press.",
            "All rights reserved.",
            "No part of this publication may be reproduced without written permission.",
            "Mara opened the window and listened for the returning birds.",
        ], source_page=4)
        filtered = pt.filter_copyright_blocks(blocks)
        self.assertEqual([b["text"] for b in filtered], [
            "CHAPTER ONE",
            "Mara opened the window and listened for the returning birds.",
        ])
        self.assertTrue(all(block["source_page"] == 4 for block in filtered))

    def test_wrapped_rights_notice_is_removed_in_ocr_blocks(self):
        blocks = pt.tag_blocks("""Copyright © 2025 Example Press.
No part of this book may be reproduced without permission.
The story begins at the harbor.""")
        self.assertEqual([b["text"] for b in pt.filter_copyright_blocks(blocks)], [
            "The story begins at the harbor.",
        ])

    def test_ordinary_discussion_is_not_removed(self):
        blocks = pt.tag_blocks("""The essay explains how copyright law changed after a memoir was published by a university press.
She pointed to the phrase all rights reserved and asked what copyright meant.""")
        self.assertEqual(pt.filter_copyright_blocks(blocks), blocks)

    def test_fused_notice_and_prose_is_preserved_conservatively(self):
        blocks = pt.paragraphs_to_blocks([
            "Copyright © 2025 Example Press. All rights reserved. The rain began before dawn.",
        ], source_page=7)
        self.assertEqual(pt.filter_copyright_blocks(blocks), blocks)

    def test_filter_runs_before_cross_page_stitching(self):
        page_one = pt.filter_copyright_blocks(pt.paragraphs_to_blocks([
            "Copyright © 2025 Example Press.", "All rights reserved.",
        ], source_page=1))
        page_two = pt.filter_copyright_blocks(pt.paragraphs_to_blocks([
            "The lighthouse blinked across the bay.",
        ], source_page=2))
        stitched = pt.stitch_pages([page_one, page_two])
        self.assertEqual(stitched[0]["text"], "The lighthouse blinked across the bay.")
        self.assertEqual(stitched[0]["source_page"], 2)


if __name__ == "__main__":
    unittest.main()
