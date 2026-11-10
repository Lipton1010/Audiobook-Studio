"""Synthetic fixtures only; no books, model inference, or PyMuPDF required."""
import concurrent.futures
import hashlib
import importlib.util
import io
import sys
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))
import pdf_backend as backend
READY=all(importlib.util.find_spec(x) for x in ('pypdfium2','pdfplumber','PIL'))

def fixture(path, rotation=0, width=612, height=792, crop="", stream=None, widget=None, dingbats=False):
    if stream is None:
        stream=b'BT /F1 12 Tf 72 720 Td (First line.) Tj 0 -18 Td (Second line.) Tj ET\n10 10 20 20 re S\n'
    objects=[b'<< /Type /Catalog /Pages 2 0 R >>',b'<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
      f'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {width} {height}] /Rotate {rotation} {crop} /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>'.encode(),
      b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>',b'<< /Length '+str(len(stream)).encode()+b' >>\nstream\n'+stream+b'endstream']
    if widget is not None:
        objects[0] = b'<< /Type /Catalog /Pages 2 0 R /AcroForm << /Fields [6 0 R] >> >>'
        objects[2] = objects[2][:-2] + b' /Annots [6 0 R] >>'
        objects.append(widget)
    if dingbats:
        font_id=len(objects)+1
        objects[2]=objects[2].replace(b'/F1 4 0 R', f'/F1 4 0 R /F2 {font_id} 0 R'.encode())
        objects.append(b'<< /Type /Font /Subtype /Type1 /BaseFont /ZapfDingbats >>')
    data=bytearray(b'%PDF-1.4\n');offsets=[0]
    for i,obj in enumerate(objects,1):offsets.append(len(data));data.extend(f'{i} 0 obj\n'.encode()+obj+b'\nendobj\n')
    offset=len(data);data.extend(f'xref\n0 {len(objects)+1}\n0000000000 65535 f \n'.encode())
    for pos in offsets[1:]:data.extend(f'{pos:010d} 00000 n \n'.encode())
    data.extend(f'trailer\n<< /Size {len(objects)+1} /Root 1 0 R >>\nstartxref\n{offset}\n%%EOF\n'.encode());path.write_bytes(data)

@unittest.skipUnless(READY,'requires isolated or installed PDF candidate dependencies')
class PdfBackendTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.pdf=self.root/'fixture.pdf';fixture(self.pdf)
    def tearDown(self):self.temp.cleanup()
    def test_text_and_page_count(self):
        with backend.open(self.pdf) as doc:
            self.assertEqual(doc.page_count,1);self.assertFalse(doc.needs_pass)
            self.assertEqual(doc.load_page(0).get_text(),'First line.\nSecond line.')
    def test_visible_widget_value_and_private_field_exclusion(self):
        for flags, field_flags, expected in ((4,0,True),(2,0,False),(32,0,False),(4,8192,False)):
            fixture(self.pdf, widget=(f'<< /Type /Annot /Subtype /Widget /Rect [72 600 200 620] '
                f'/FT /Tx /F {flags} /Ff {field_flags} /V (Visible form value) >>').encode())
            with backend.open(self.pdf) as doc:
                self.assertIsNotNone(doc._native.formenv)
                self.assertEqual(doc.load_page(0).get_pixmap().image.size, (612,792))
                self.assertEqual('Visible form value' in doc.load_page(0).get_text(), expected)
    def test_rotated_artist_credit_retains_words(self):
        for transform in (b'0 1 -1 0 500 100', b'0 -1 1 0 500 700'):
            fixture(self.pdf, stream=b'BT /F1 8 Tf '+transform+b' Tm (JOY ANG) Tj ET')
            with backend.open(self.pdf) as doc:
                self.assertEqual(doc.load_page(0).get_text(), 'JOY ANG')
    def test_checkbox_dingbat_is_not_narrated_as_letter(self):
        fixture(self.pdf, dingbats=True,
                widget=b'<< /Type /Annot /Subtype /Widget /Rect [70 600 90 625] /FT /Btn /F 4 >>',
                stream=b'BT /F2 12 Tf 72 610 Td (l) Tj ET BT /F1 12 Tf 100 610 Td (label) Tj ET')
        with backend.open(self.pdf) as doc:
            self.assertEqual(doc.load_page(0).get_text(), 'label')
    def test_checkbox_form_uses_visible_row_order(self):
        fixture(self.pdf, widget=b'<< /Type /Annot /Subtype /Widget /Rect [70 600 90 625] /FT /Btn /F 4 >>',
                stream=b'BT /F1 12 Tf 100 610 Td (Lower row) Tj ET BT /F1 12 Tf 100 720 Td (Form title) Tj ET')
        with backend.open(self.pdf) as doc:
            self.assertEqual(doc.load_page(0).get_text(), 'Form title\nLower row')
    def test_rotated_kerning_overlap_does_not_split_word(self):
        lines=[]
        for text,top,bottom in (('CON',40,80),('F',30,40.15),('LICT',0,30.2)):
            lines.append(dict(text=text,x0=100,x1=120,top=top,bottom=bottom,
                chars=[dict(text=text,x0=100,x1=120,top=top,bottom=bottom,
                            size=12,upright=False,matrix=(0,20,-20,0,0,0))]))
        self.assertEqual([x['text'] for x in backend.join_inline_scripts(lines)], ['CONFLICT'])
    def test_rotation_changes_preview_not_reading_order(self):
        fixture(self.pdf,rotation=90)
        with backend.open(self.pdf) as doc:
            page=doc.load_page(0);self.assertEqual((page.rect.width,page.rect.height),(792,612))
            self.assertEqual(page.get_text(),'First line.\nSecond line.')
            self.assertEqual(page.get_pixmap().image.size,(792,612))
    def test_crop_hides_text_outside_visible_page(self):
        fixture(self.pdf,crop='/CropBox [0 0 612 710]')
        with backend.open(self.pdf) as doc:
            self.assertEqual(doc.load_page(0).get_text(),'Second line.')
            self.assertEqual(doc.load_page(0).rect.height,710)

    def test_margin_number_is_separate_from_spoken_line(self):
        fixture(self.pdf,stream=b'BT /F1 12 Tf 72 720 Td (A simple verse line.) Tj 400 0 Td (600) Tj ET')
        with backend.open(self.pdf) as doc:
            lines=doc.load_page(0).get_text('dict')['blocks'][0]['lines']
            self.assertEqual([l['spans'][0]['text'] for l in lines],['A simple verse line.','600'])

    def test_inline_subscript_is_not_a_discardable_numeric_line(self):
        fixture(self.pdf,stream=b'BT /F1 12 Tf 72 720 Td (CO) Tj /F1 8 Tf 17.34 -4 Td (2) Tj ET')
        with backend.open(self.pdf) as doc:
            self.assertEqual(doc.load_page(0).get_text(),'CO2')
    def test_prose_continues_after_spaced_subscript(self):
        fixture(self.pdf, stream=b'BT /F1 12 Tf 72 720 Td (CO) Tj /F1 8 Tf 17.34 -4 Td (2) Tj /F1 12 Tf 12 4 Td (used by) Tj ET')
        with backend.open(self.pdf) as doc:
            self.assertEqual(doc.load_page(0).get_text(), 'CO2 used by')
    def test_displaced_dash_stays_in_numeric_range_across_columns(self):
        fixture(self.pdf, stream=b'BT /F1 10 Tf 72 720 Td (01) Tj 11.12 -4 Td (-) Tj 3.33 4 Td (54) Tj 80 0 Td (Common) Tj ET')
        with backend.open(self.pdf) as doc:
            self.assertEqual(doc.load_page(0).get_text(), '01-54\nCommon')

    def test_small_font_positioned_words_keep_spaces(self):
        # PDF text can encode word spacing as positioning, without space glyphs.
        fixture(self.pdf,stream=b'BT /F1 10 Tf 72 720 Td (A) Tj 9 0 Td (test) Tj ET')
        with backend.open(self.pdf) as doc:
            self.assertEqual(doc.load_page(0).get_text(),'A test')

    def test_inline_script_preserves_an_explicit_space(self):
        fixture(self.pdf,stream=b'BT /F1 12 Tf 72 720 Td (CO) Tj /F1 8 Tf 17.34 -4 Td ( 2) Tj ET')
        with backend.open(self.pdf) as doc:
            self.assertEqual(doc.load_page(0).get_text(),'CO 2')

    def test_smaller_inline_font_does_not_create_a_heading_line(self):
        fixture(self.pdf,stream=b'BT /F1 12 Tf 72 720 Td (First) Tj /F1 8.4 Tf 26 0 Td (foreign) Tj ET')
        with backend.open(self.pdf) as doc:
            self.assertEqual(doc.load_page(0).get_text(),'First foreign')

    def test_drop_cap_remains_separate_for_existing_paragraph_joiner(self):
        fixture(self.pdf,stream=b'BT /F1 32 Tf 72 720 Td (W) Tj /F1 12 Tf 34 0 Td (hat follows.) Tj ET')
        with backend.open(self.pdf) as doc:
            self.assertEqual(doc.load_page(0).get_text(),'W\nhat follows.')

    def test_quoted_drop_cap_is_not_split_into_two_spoken_words(self):
        fixture(self.pdf,stream=b'BT /F1 32 Tf 72 720 Td ("W) Tj /F1 12 Tf 45 0 Td (hat follows.) Tj ET')
        with backend.open(self.pdf) as doc:
            self.assertEqual(doc.load_page(0).get_text(),'"W\nhat follows.')

    def test_native_rendering_is_serialized_across_threads(self):
        def render(_):
            with backend.open(self.pdf) as doc:return hashlib.sha256(doc.load_page(0).get_pixmap().tobytes('png')).hexdigest()
        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:self.assertEqual(len(set(pool.map(render,range(24)))),1)
    def test_closed_document_and_bounds_rejected(self):
        doc=backend.open(self.pdf);page=doc.load_page(0)
        with self.assertRaises(ValueError):doc.load_page(1)
        doc.close();doc.close()
        with self.assertRaises(ValueError):page.get_text()
    def test_pixel_budget_and_nonfinite_scale(self):
        with backend.open(self.pdf) as doc:
            for scale in [100,0,-1,float('nan')]:
                with self.assertRaises(ValueError):doc.load_page(0).get_pixmap(matrix=backend.Matrix(scale,scale))
    def test_malformed_document_does_not_poison_next_open(self):
        broken=self.root/'bad.pdf';broken.write_bytes(b'%PDF-1.4 not a real document')
        with self.assertRaises(Exception):backend.open(broken)
        with backend.open(self.pdf) as doc:self.assertEqual(doc.page_count,1)
    def test_cover_decoding_and_limits(self):
        from PIL import Image
        raw=io.BytesIO();Image.new('RGB',(16,16),'red').save(raw,format='PNG')
        result=backend.cover_png(raw.getvalue());self.assertEqual(Image.open(io.BytesIO(result)).size,(16,16))
        with self.assertRaises(ValueError):backend.cover_png(raw.getvalue(),max_pixels=10)
        with self.assertRaises(ValueError):backend.cover_png(raw.getvalue(),max_bytes=10)
    def test_source_bytes_unchanged(self):
        before=self.pdf.read_bytes()
        with backend.open(self.pdf) as doc:doc.load_page(0).get_text();doc.load_page(0).get_pixmap()
        self.assertEqual(self.pdf.read_bytes(),before)

if __name__=='__main__':unittest.main()
