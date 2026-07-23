"""
Shared text pipeline for the Audiobook Studio app.

Path A: text-layer PDF -> cleaned paragraphs -> blocks
Path B: per-page OCR markdown -> tagged blocks (stage_two logic + fixes)

Unified output: list of {"type": ..., "text": ...} blocks, same schema
narrate_tagged.py validated. Fixes carried here beyond samples/stage_two.py:
  1. bare page-number filter (digits, <=4 chars)  [validated 2026-07-21]
  2. all-caps headings may end in ? or !
  3. markdown emphasis markers stripped from narration text
  4. cross-page partial-sentence stitching
"""

import re

import fitz  # PyMuPDF


# ---------- shared helpers ----------

MD_EMPHASIS_RE = re.compile(r"\*{1,3}([^*]+)\*{1,3}|_{1,3}([^_]+)_{1,3}")
TERMINAL_PUNCT = ".?!:;”’\"'"


def strip_markdown(text):
    """Remove markdown emphasis markers and stray heading hashes, keep content."""
    prev = None
    while prev != text:
        prev = text
        text = MD_EMPHASIS_RE.sub(lambda m: m.group(1) or m.group(2), text)
    text = re.sub(r"^#{1,6}\s*", "", text.strip())
    text = re.sub(r"\s+", " ", text)  # collapse stray double spaces from PDF extraction
    return text.strip()


def is_table_row(ln):
    s = ln.strip()
    return s.startswith("|") and s.endswith("|") and s.count("|") >= 2


def is_heading(ln):
    s = strip_markdown(ln)
    if len(s) < 2 or len(s) > 60:
        return False
    # ? and ! are legal heading enders ("CAN YOU REMEMBER THEIR NAMES?")
    if s[-1] in ".:,;":
        return False
    letters = [c for c in s if c.isalpha()]
    if not letters:
        return False
    return all(c.isupper() for c in letters)


def is_dialogue(ln):
    s = strip_markdown(ln)
    m = re.match(r"^([A-Z][a-zA-Z]+)(\s[A-Z][a-zA-Z]+)?:\s+\S", s)
    return bool(m)


def is_number_heavy_list(ln):
    s = ln.strip()
    if not (s.startswith("-") or s.startswith("•")):
        return False
    s = s.lstrip("-•").strip()
    s = re.sub(r"^[A-Za-z][A-Za-z0-9 ]{0,15}:\s*", "", s)
    tokens = s.split()
    if not tokens:
        return False
    numeric = sum(1 for t in tokens if re.fullmatch(r"\d+|dead", t.strip(".,;")))
    return numeric >= max(1, len(tokens) // 2)


# ---------- Path B tagging (per OCR page) ----------

def tag_blocks(raw_text):
    lines = [ln.rstrip() for ln in raw_text.splitlines()]
    blocks = []
    i = 0
    n = len(lines)
    while i < n:
        ln = lines[i]
        if not ln.strip():
            i += 1
            continue
        stripped = ln.strip()
        if stripped.isdigit() and len(stripped) <= 4:
            i += 1
            continue
        # GLM-OCR degenerates on full-page artwork, emitting endless
        # code fences, punctuation lines, or empty HTML table markup.
        # A line with no letter/digit outside of markup is not
        # narratable content.
        visible = re.sub(r"<[^>]+>", "", stripped)
        if not any(c.isalnum() for c in visible):
            i += 1
            continue
        if re.fullmatch(r"`{3,}[\w-]*", stripped):
            i += 1
            continue
        if is_table_row(ln):
            while i < n and (is_table_row(lines[i]) or not lines[i].strip()):
                if not lines[i].strip():
                    if i + 1 < n and is_table_row(lines[i + 1]):
                        i += 1
                        continue
                    else:
                        break
                i += 1
            blocks.append({"type": "table", "text": "A reference table is omitted here."})
            continue
        if is_number_heavy_list(ln):
            while i < n and (is_number_heavy_list(lines[i]) or not lines[i].strip()):
                if not lines[i].strip():
                    if i + 1 < n and is_number_heavy_list(lines[i + 1]):
                        i += 1
                        continue
                    else:
                        break
                i += 1
            blocks.append({"type": "omitted_data", "text": "A data list is omitted here."})
            continue
        if is_heading(ln):
            blocks.append({"type": "heading", "text": strip_markdown(ln)})
            i += 1
            continue
        if is_dialogue(ln):
            blocks.append({"type": "dialogue", "text": strip_markdown(ln)})
            i += 1
            continue
        body = {"type": "body", "text": strip_markdown(ln)}
        # OCR degeneracy can repeat a line verbatim; identical
        # consecutive real paragraphs do not occur in books.
        if not (blocks and blocks[-1] == body):
            blocks.append(body)
        i += 1
    # Degenerate-page detector: OCR failure on artwork loops a tiny
    # vocabulary of lines. No real book page repeats itself like that.
    if len(blocks) >= 20:
        unique = len(set(b["text"] for b in blocks))
        if unique / len(blocks) < 0.3:
            return []
    return blocks


def stitch_pages(pages_of_blocks):
    """
    Merge per-page block lists into one list. If a page ends with a body
    block that stops mid-sentence and the next page opens with a body
    block that continues it (lowercase or no sentence-terminal ending),
    join the two texts so narration does not pause mid-sentence at a
    page boundary.
    """
    merged = []
    for page_blocks in pages_of_blocks:
        page_blocks = [b for b in page_blocks if b["text"].strip()]
        if not page_blocks:
            continue
        if merged:
            prev = merged[-1]
            head = page_blocks[0]
            if (
                prev["type"] == "body"
                and head["type"] == "body"
                and prev["text"]
                and prev["text"][-1] not in TERMINAL_PUNCT
            ):
                prev["text"] = prev["text"].rstrip() + " " + head["text"].lstrip()
                page_blocks = page_blocks[1:]
        merged.extend(page_blocks)
    return merged


# ---------- Path A extraction (text-layer PDF) ----------

# Chapter divisions numbered as digits, roman numerals, or spelled-out
# words ("Chapter One", "Chapter Twenty-One"), plus standalone front/back
# matter divisions. Anchored and number-shaped so it does not fire on a
# short body paragraph that merely begins with "Chapter"/"Part".
_NUM_WORD = (
    r"(?:one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|"
    r"thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|twenty|"
    r"thirty|forty|fifty|sixty|seventy|eighty|ninety|hundred)"
    r"(?:[ -](?:one|two|three|four|five|six|seven|eight|nine))?"
)
HEADING_LINE_RE = re.compile(
    r"^(?:(?:BOOK|CHAPTER|PART|CANTO)\s+(?:\d+|[IVXLCDM]+|" + _NUM_WORD + r")"
    r"|PROLOGUE|EPILOGUE|INTRODUCTION|PREFACE|FOREWORD|AFTERWORD)\s*$",
    re.IGNORECASE,
)

LIGATURES = {
    "ﬀ": "ff", "ﬁ": "fi", "ﬂ": "fl",
    "ﬃ": "ffi", "ﬄ": "ffl", "ﬅ": "st",
}


def normalize_ligatures(text):
    for k, v in LIGATURES.items():
        text = text.replace(k, v)
    return text


def _page_lines_with_x(page):
    """[(x0, text)] for every nonempty, non-page-number line, reading order.
    A drop-cap (single letter rendered much larger than body text) is merged
    into the following line with no space."""
    d = page.get_text("dict")
    raw = []
    for block in d["blocks"]:
        if block.get("type", 0) != 0:
            continue
        for line in block["lines"]:
            spans = line.get("spans", [])
            if not spans:
                continue
            text = normalize_ligatures("".join(s["text"] for s in spans)).strip()
            if not text:
                continue
            if text.isdigit() and len(text) <= 4:
                continue  # page numbers and verse line numbers
            size = max(s.get("size", 0) for s in spans)
            raw.append((line["bbox"][0], text, size))
    if not raw:
        return []
    sizes = sorted(s for _, _, s in raw)
    body_size = sizes[len(sizes) // 2]
    out = []
    skip_next_join = False
    for i, (x0, text, size) in enumerate(raw):
        if skip_next_join:
            skip_next_join = False
            prev_x0, prev_text = out.pop()
            out.append((prev_x0, prev_text + text))
            continue
        if (
            re.fullmatch(r"[“”\"'‘’]?[A-Z]", text)
            and body_size > 0
            and size >= body_size * 1.4
            and i + 1 < len(raw)
        ):
            out.append((x0, text))
            skip_next_join = True
            continue
        out.append((x0, text))
    return out


def detect_text_mode(pdf_path, page_from, page_to):
    """
    'verse' if most lines begin uppercase (poems capitalize line starts;
    prose wrap lines rarely do). Measured: The Odyssey 0.61, prose novel
    (PHM) 0.25. Threshold 0.45.
    """
    doc = fitz.open(pdf_path)
    try:
        pages = range(page_from - 1, page_to, max(1, (page_to - page_from) // 6 or 1))
        caps = total = 0
        for pno in pages:
            for _, text in _page_lines_with_x(doc.load_page(pno)):
                total += 1
                if text[0].isupper():
                    caps += 1
        return "verse" if total and caps / total > 0.45 else "prose"
    finally:
        doc.close()


def _prose_page_paragraphs(lines_with_x):
    """path_a.py's validated x-indent rule: indented line = new paragraph.
    A chapter/division heading line is always split into its own paragraph,
    even if its indentation would otherwise merge it."""
    if not lines_with_x:
        return []
    xs = sorted(x0 for x0, _ in lines_with_x)
    left_margin = xs[0]
    indent_threshold = left_margin + 6
    paras = []
    buf = ""
    for x0, text in lines_with_x:
        if HEADING_LINE_RE.match(text.strip()):
            if buf:
                paras.append(buf)
                buf = ""
            paras.append(text.strip())
            continue
        if x0 > indent_threshold:
            if buf:
                paras.append(buf)
            buf = text
        else:
            buf = (buf + " " + text) if buf else text
    if buf:
        paras.append(buf)
    return paras


def _verse_page_paragraphs(lines_with_x):
    """
    Verse mode: indents are continuations, so group lines into sentence
    runs instead. A line ending with sentence-terminal punctuation closes
    the paragraph. Standalone 'Book N' lines become their own paragraph
    so heading detection can find them.
    """
    paras = []
    buf = []
    for _, text in lines_with_x:
        if HEADING_LINE_RE.match(text):
            if buf:
                paras.append(" ".join(buf))
                buf = []
            paras.append(text)
            continue
        buf.append(text)
        if text[-1] in '.?!”"':
            paras.append(" ".join(buf))
            buf = []
    if buf:
        paras.append(" ".join(buf))
    return paras


def paragraphs_to_blocks(paragraphs):
    """Path A blocks: mostly body, with conservative heading detection."""
    blocks = []
    for p in paragraphs:
        if HEADING_LINE_RE.match(p.strip()):
            blocks.append({"type": "heading", "text": strip_markdown(p)})
        elif is_heading(p):
            blocks.append({"type": "heading", "text": strip_markdown(p)})
        else:
            blocks.append({"type": "body", "text": strip_markdown(p)})
    return blocks


def extract_path_a(pdf_path, page_from, page_to, progress_cb=None):
    """
    Path A: whole page range -> stitched blocks.
    page_from/page_to are 1-based inclusive. Mode (prose vs verse) is
    auto-detected once for the range.
    """
    mode = detect_text_mode(pdf_path, page_from, page_to)
    doc = fitz.open(pdf_path)
    try:
        pages = []
        total = page_to - page_from + 1
        for idx, pno in enumerate(range(page_from - 1, page_to)):
            lines = _page_lines_with_x(doc.load_page(pno))
            if mode == "verse":
                paras = _verse_page_paragraphs(lines)
            else:
                paras = _prose_page_paragraphs(lines)
            pages.append(paragraphs_to_blocks(paras))
            if progress_cb:
                progress_cb(idx + 1, total)
        return stitch_pages(pages), mode
    finally:
        doc.close()


# ---------- Path B rasterize ----------

def rasterize_page(pdf_path, page_index, out_path, dpi=200):
    doc = fitz.open(pdf_path)
    try:
        page = doc.load_page(page_index)
        zoom = dpi / 72.0
        pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom))
        pix.save(out_path)
    finally:
        doc.close()
