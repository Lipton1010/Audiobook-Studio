import sys
import tempfile
import unittest
from pathlib import Path

try:
    import pymupdf as fitz
except ImportError:
    fitz = None


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))


@unittest.skipUnless(fitz, "requires the installed PyMuPDF extraction runtime")
class PathAVisualPdfTests(unittest.TestCase):
    def test_real_pdf_keeps_plain_table_and_image_in_source_order(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as temp:
            pdf_path = Path(temp) / "synthetic.pdf"
            doc = fitz.open()
            page = doc.new_page()
            page.insert_text((72, 72), "before dialogue.")
            page.insert_text((72, 96), "species count weight")
            page.insert_text((72, 108), "pumps 12 17")
            page.insert_text((72, 120), "gates 4 9")
            pixmap = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 2, 2), False)
            pixmap.clear_with(0)
            page.insert_image(fitz.Rect(72, 135, 120, 170), pixmap=pixmap)
            page.insert_text((72, 190), "after dialogue.")
            doc.save(pdf_path)
            doc.close()

            import pipeline_text as pt
            from unittest import mock
            with mock.patch.object(pt, "fitz", fitz):
                blocks, _ = pt.extract_path_a(str(pdf_path), 1, 1)

        self.assertEqual([block["type"] for block in blocks], [
            "body", "visual", "visual", "body",
        ])
        self.assertEqual(blocks[1]["visual_kind"], "plain-text table")
        self.assertEqual(blocks[2]["visual_kind"], "embedded image")
        self.assertEqual([block["text"] for block in blocks if block["type"] == "body"], [
            "before dialogue.", "after dialogue.",
        ])
        self.assertTrue(all(block["source_page"] == 1 for block in blocks))


if __name__ == "__main__":
    unittest.main()
