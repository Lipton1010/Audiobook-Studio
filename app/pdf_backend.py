"""PDF backend using pinned PDFium, pdfplumber and Pillow; no MuPDF fallback.

All PDFium lifetime and API calls are serialized process-wide. No PDFium handle
escapes this module. Pillow results own copies before native resources close.
This is concurrency control, not an OS security sandbox for hostile PDFs.
"""
import io
import math
import re
import threading
from functools import wraps
from dataclasses import dataclass
from pathlib import Path

_LOCK = threading.RLock()

def join_inline_scripts(lines):
    """Attach adjacent small superscripts/subscripts before numeric filtering.

    Keep stream order and original text. Geometric overlap and a bounded
    horizontal gap distinguish inline scripts from separate numeric rows.
    """
    result = []
    tail_script = False
    for line in lines:
        if result:
            prev = result[-1]
            vertical = (prev['chars'] and line['chars']
                        and all(not c.get('upright', True) for c in prev['chars']+line['chars']))
            if vertical and abs(prev['x0']-line['x0']) < .5:
                em = max(c['x1']-c['x0'] for c in prev['chars']+line['chars'])
                upwards = prev['chars'][0].get('matrix', (0,1))[1] > 0
                gap = prev['top']-line['bottom'] if upwards else line['top']-prev['bottom']
                if -em*.1 <= gap <= em*.6:
                    result[-1] = {'text':prev['text']+(' ' if gap > em*.15 else '')+line['text'],
                        'chars':prev['chars']+line['chars'],
                        'x0':min(prev['x0'],line['x0']),'x1':max(prev['x1'],line['x1']),
                        'top':min(prev['top'],line['top']),'bottom':max(prev['bottom'],line['bottom'])}
                    tail_script = False
                    continue
            size = max(c['size'] for c in prev['chars'])
            new_size = max(c['size'] for c in line['chars'])
            overlap = min(prev['bottom'],line['bottom'])-max(prev['top'],line['top'])
            gap = line['x0']-prev['x1']
            inline = (overlap > .3*min(prev['bottom']-prev['top'],line['bottom']-line['top'])
                      and -1 <= gap < size*(.8 if tail_script else .6))
            small = len(line['text']) <= 3 and new_size < size*.9
            # Embedded symbol fonts can report a displaced box for a dash
            # although it belongs to the adjacent numeric range on one row.
            inline_symbol = line['text'] in ('-', '\u2013', '\u2014', '\u2212') and new_size <= size*1.1
            same_row = (abs(line['bottom']-prev['bottom']) < max(size,new_size)*.25
                        and overlap > .6*min(prev['bottom']-prev['top'],line['bottom']-line['top']))
            initial = prev['text'].lstrip('"\'`\u2018\u2019\u201c\u201d')
            drop_cap = len(initial) == 1 and initial.isupper() and size >= new_size*1.4
            if inline and not drop_cap and (small or inline_symbol or tail_script or same_row):
                separator = ' ' if gap > min(size,new_size)*.15 else ''
                result[-1] = {'text':prev['text']+separator+line['text'],
                    'chars':prev['chars']+line['chars'],'x0':prev['x0'],'x1':line['x1'],
                    'top':min(prev['top'],line['top']),'bottom':max(prev['bottom'],line['bottom'])}
                tail_script = small or inline_symbol
                continue
        result.append(line)
        tail_script = False
    return result

def split_wide_gaps(lines):
    """Keep separated columns/marginal line numbers out of narrated lines.

    Content-stream ordering is retained. Ordinary word spacing is untouched;
    only gaps exceeding 1.5 em on both sides form a separate layout segment.
    """
    from pdfplumber.utils import extract_text
    result = []
    for line in lines:
        groups = [[]]
        seen = set()
        for char in line['chars']:
            # TextMap repeats the same glyph object when expanding a ligature.
            if id(char) in seen:
                continue
            seen.add(id(char))
            if groups[-1]:
                prev = groups[-1][-1]
                if char['x0']-prev['x1'] >= 1.5*max(char['size'],prev['size'])-.01:
                    groups.append([])
            groups[-1].append(char)
        if len(groups)==1:
            result.append(line)
            continue
        for chars in groups:
            text = extract_text(chars,use_text_flow=True,x_tolerance_ratio=.15,
                                y_tolerance=max(c['size'] for c in chars)*.5).strip()
            if text:
                result.append({'text':text,'chars':chars,
                    'x0':min(c['x0'] for c in chars),'x1':max(c['x1'] for c in chars),
                    'top':min(c['top'] for c in chars),'bottom':max(c['bottom'] for c in chars)})
    return result

def serialized(fn):
    @wraps(fn)
    def call(*args, _lock=_LOCK, **kwargs):
        with _lock:
            return fn(*args, **kwargs)
    return call

@dataclass(frozen=True)
class Rect:
    x0: float
    y0: float
    x1: float
    y1: float
    @property
    def width(self): return self.x1-self.x0
    @property
    def height(self): return self.y1-self.y0

@dataclass(frozen=True)
class Matrix:
    x: float
    y: float

class Pixmap:
    def __init__(self, image): self.image = image
    def save(self, path): self.image.save(path)
    def tobytes(self, fmt):
        result = io.BytesIO()
        self.image.save(result, format=fmt.upper())
        return result.getvalue()

class Page:
    def __init__(self, document, index):
        self.document, self.index = document, index
    @property
    @serialized
    def rect(self):
        self.document._check()
        page = self.document._native[self.index]
        try:
            width, height = page.get_size()
            return Rect(0, 0, width, height)
        finally: page.close()

    @serialized
    def get_text(self, kind='text'):
        self.document._check()
        data = self.document._page_data(self.index)
        if kind == 'text': return data['text']
        if kind != 'dict': raise ValueError('Unsupported text representation')
        return {'blocks': [{'type': 0, 'lines': data['lines']}]}

    @serialized
    def get_pixmap(self, matrix=None, dpi=72, alpha=False):
        self.document._check()
        scale = matrix.x if matrix else dpi / 72
        if matrix and matrix.x != matrix.y: raise ValueError('Only uniform rendering is supported')
        rect = self.rect
        if not math.isfinite(scale) or scale <= 0 or math.ceil(rect.width*scale)*math.ceil(rect.height*scale)>24_000_000:
            raise ValueError('PDF render exceeds the 24 megapixel safety limit')
        page = self.document._native[self.index]
        try:
            bitmap = page.render(scale=scale)
            try: image = bitmap.to_pil().convert('RGB').copy()
            finally:
                # The returned image owns its copy; no native buffer escapes.
                bitmap.warn_on_close = False
                bitmap.close()
        finally: page.close()
        return Pixmap(image)

    @serialized
    def get_images(self, full=True):
        self.document._check()
        return [((self.index, i),) for i, _ in enumerate(self.document._page_data(self.index)['images'])]

    @serialized
    def get_image_rects(self, key):
        self.document._check()
        return [self.document._page_data(self.index)['images'][key[1]]]

    @serialized
    def get_drawings(self):
        self.document._check()
        return self.document._page_data(self.index)['drawings']

class Document:
    @serialized
    def __init__(self, path):
        import pdfplumber
        import pypdfium2
        self._native = self._layout = None
        self._snapshots = {}
        try:
            self._native = pypdfium2.PdfDocument(str(path))
            # Render ordinary AcroForm appearances, without enabling XFA or
            # supplying JavaScript/external-action callbacks.
            import pypdfium2.raw as raw
            if self._native.get_formtype() == raw.FORMTYPE_ACRO_FORM:
                self._native.init_forms(raw.FPDF_FORMFILLINFO(version=2))
            self._layout = pdfplumber.open(path)
            self.page_count = len(self._native)
            self.needs_pass = False  # Successful open without a password.
            self.metadata = {str(k).lower(): v for k,v in self._layout.metadata.items()}
        except BaseException:
            self.close()
            raise
    def _page_data(self, index):
        if index in self._snapshots:
            return self._snapshots[index]
        page = self._layout_page(index)
        try:
            # A checkbox appearance may encode a circle as ASCII "l" in
            # ZapfDingbats. It is a form graphic, not a spoken letter. Remove
            # only such glyphs inside actual button-widget rectangles.
            from pdfminer.psparser import literal_name
            buttons = [a for a in page.annots
                       if literal_name((a.get('data') or {}).get('FT')) == 'Btn']
            def reading_object(obj):
                if obj.get('object_type') != 'char' or 'ZapfDingbats' not in obj.get('fontname',''):
                    return True
                x = (obj['x0']+obj['x1'])/2
                y = (obj['top']+obj['bottom'])/2
                return not any(a['x0']-1 <= x <= a['x1']+1 and a['top']-1 <= y <= a['bottom']+1 for a in buttons)
            reading_page = page.filter(reading_object) if buttons else page
            lines = split_wide_gaps(join_inline_scripts(
                reading_page.extract_text_lines(return_chars=True, strip=True, use_text_flow=True,
                                        x_tolerance_ratio=.15)))
            # Font-dependent dash boxes must not turn one numeric range into
            # three tokens and accidentally trigger the visual-data heuristic.
            for line in lines:
                line['text'] = re.sub(r'(?<=\d)\s*([\u2013\u2212-])\s*(?=\d)', r'\1', line['text'])
            # Visible text widgets may live only in annotations, not the page
            # content stream. Never include hidden fields or password values.
            from pdfminer.pdftypes import resolve1
            from pdfminer.psparser import literal_name
            from pdfminer.utils import decode_text
            for annotation in page.annots:
                field = dict(annotation.get('data') or {})
                seen = set()
                parent = field.get('Parent')
                while parent is not None and id(parent) not in seen:
                    seen.add(id(parent))
                    inherited = resolve1(parent)
                    if not isinstance(inherited, dict):
                        break
                    for key in ('FT', 'V', 'DV', 'Ff'):
                        if key not in field and key in inherited:
                            field[key] = inherited[key]
                    parent = inherited.get('Parent')
                if (literal_name(field.get('Subtype')) != 'Widget'
                        or literal_name(field.get('FT')) != 'Tx'
                        or int(field.get('F', 0)) & (1 | 2 | 32)
                        or int(field.get('Ff', 0)) & 8192):
                    continue
                value = resolve1(field.get('V', field.get('DV', '')))
                value = decode_text(value) if isinstance(value, bytes) else value
                if not isinstance(value, str) or not value.strip():
                    continue
                # Avoid double narration when an appearance was flattened into
                # the content stream already.
                if any(line['text'].strip() == value.strip()
                       and abs(line['x0']-annotation['x0']) < 10
                       and abs(line['top']-annotation['top']) < 15 for line in lines):
                    continue
                lines.append({'text': value.strip(), 'chars': [],
                              **{k: annotation[k] for k in ('x0', 'x1', 'top', 'bottom')}})
            if buttons:
                # Interactive checklists are spatial forms. Their content
                # streams often paint all labels, then the title last. Keep
                # their visible row order instead of narrating that draw order.
                # Ordinary prose/verse remains in its original stream order.
                lines.sort(key=lambda line: (round(line['top']/2), line['x0']))
            x_origin, y_origin = page.bbox[:2]
            data = {'text': '\n'.join(line['text'] for line in lines),
                    'lines': [{'bbox': (line['x0']-x_origin,line['top']-y_origin,line['x1']-x_origin,line['bottom']-y_origin),
                               'spans':[{'text':line['text'],'size':max((c['size'] for c in line['chars']),default=0)}]}
                              for line in lines],
                    'images':[Rect(x['x0']-x_origin,x['top']-y_origin,x['x1']-x_origin,x['bottom']-y_origin) for x in page.images],
                    'drawings':[{'rect':Rect(x['x0']-x_origin,x['top']-y_origin,x['x1']-x_origin,x['bottom']-y_origin)}
                         for x in page.lines+page.rects+page.curves
                         if not (x.get('tag')=='Artifact' and not x.get('stroke')
                                 and isinstance(x.get('non_stroking_color'),str)
                                 and abs(x['x0']-x_origin)<.1 and abs(x['top']-y_origin)<.1
                                 and abs(x['x1']-x_origin-page.width)<.1 and abs(x['bottom']-y_origin-page.height)<.1)]}
            if len(self._snapshots)>=8: self._snapshots.pop(next(iter(self._snapshots)))
            self._snapshots[index]=data
            return data
        finally: page.close()
    def _layout_page(self, index):
        # PyMuPDF extracts in unrotated PDF coordinates. Keep layout in that
        # coordinate system; only preview/raster rendering uses page rotation.
        from pdfplumber.page import Page as LayoutPage
        source = self._layout.pages[index]
        rotation = source.page_obj.rotate
        try:
            source.page_obj.rotate = 0
            page = LayoutPage(self._layout, source.page_obj, index+1)
            _ = page.layout
            if page.cropbox and page.cropbox != page.mediabox:
                page = page.crop(page.cropbox, strict=False)
            return page
        finally:
            source.page_obj.rotate = rotation
    def _check(self):
        if self._native is None: raise ValueError('PDF is closed')
    @serialized
    def load_page(self, index):
        self._check()
        if not 0 <= index < self.page_count: raise ValueError('Page outside PDF')
        return Page(self, index)
    @serialized
    def get_toc(self, simple=True):
        self._check()
        rows = []
        for item in self._native.get_toc(max_depth=64):
            dest = item.get_dest()
            if dest is not None: rows.append([item.level+1, item.get_title(), dest.get_index()+1])
        return rows
    @serialized
    def extract_image(self, key):
        import pypdfium2.raw as raw
        rect = self.load_page(key[0]).get_image_rects(key)[0]
        page = self._native[key[0]]
        try:
            crop_left, _, _, crop_top = page.get_bbox()
            matches = []
            for obj in page.get_objects(filter=[raw.FPDF_PAGEOBJ_IMAGE]):
                left, bottom, right, top = obj.get_bounds()
                bounds = (left-crop_left, crop_top-top, right-crop_left, crop_top-bottom)
                if all(abs(a-b)<.5 for a,b in zip(bounds,(rect.x0,rect.y0,rect.x1,rect.y1))):
                    matches.append(obj)
            if len(matches) != 1:
                return None  # Ambiguous object mapping: caller uses page cover.
            width, height = matches[0].get_px_size()
            if width*height > 24_000_000:
                return None
            bitmap = matches[0].get_bitmap(render=True)
            try: image = bitmap.to_pil().convert('RGB').copy()
            finally:
                # The returned image owns its copy; no native buffer escapes.
                bitmap.warn_on_close = False
                bitmap.close()
            return {'image':Pixmap(image).tobytes('png'),'ext':'png','width':image.width,'height':image.height}
        finally:
            page.close()
    @serialized
    def close(self):
        self._snapshots.clear()
        if self._layout is not None:
            try: self._layout.close()
            finally: self._layout = None
        if self._native is not None:
            try: self._native.close()
            finally: self._native = None
    def __del__(self):
        if hasattr(self, "_native"):
            self.close()
    def __enter__(self): return self
    def __exit__(self, *args): self.close()


def open(path):
    return Document(path)


def cover_png(raw, max_bytes=20*1024*1024, max_pixels=24_000_000):
    """Bounded raster decoding, independent of PDFium and OCR."""
    from PIL import Image
    if not raw or len(raw)>max_bytes: raise ValueError('Cover byte limit exceeded')
    with Image.open(io.BytesIO(raw)) as image:
        if image.format not in ('PNG','JPEG','WEBP'): raise ValueError('Unsupported cover format')
        if image.width*image.height>max_pixels: raise ValueError('Cover pixel limit exceeded')
        return Pixmap(image.convert('RGB')).tobytes('png')
