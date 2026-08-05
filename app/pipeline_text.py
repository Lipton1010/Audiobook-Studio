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
    # Safety net for stray inline HTML from OCR. Whole HTML tables are caught
    # earlier and replaced with a marker; this stops a lone <br> or <em> from
    # ever being spoken. Requires a letter or slash after "<" so ordinary prose
    # comparisons are untouched.
    text = HTML_TAG_RE.sub(" ", text)
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


# A random table in a D&D book always opens with dice notation naming its
# column ("1d20 Claim to Fame", "1d12 Calamity", "d100 Trinket"), then rows that
# start with a roll or a roll range. GLM-OCR renders these as plain indented
# text, NOT as markdown pipe tables, so is_table_row never sees them and
# is_number_heavy_list rejects them for lacking a bullet. Without this the DMG
# narrates every row: "1 Delicious food. 2 Rude people. 3 Friendly folk."
DICE_HEADER_RE = re.compile(r"^\d*d\d+\b", re.I)
TABLE_ROW_RE = re.compile(r"^\d+\s*(?:[-–—]\s*\d+)?\s+\S")
ROLL_PREFIX_RE = re.compile(r"^\d+\s*(?:[-–—]\s*\d+)?\s+")
# "CHAPTER 6 | COSMOLOGY" / "APPENDIX B | MAPS": the pipe form is only ever the
# repeating running header. A general fix would be cross-page repetition
# detection in stitch_pages, which sees every page; this targeted form is what
# the 2024 DMG needs and cannot touch a real chapter opener.
RUNNING_HEADER_RE = re.compile(r"^(CHAPTER|APPENDIX|PART)\b[^|]{0,24}\|", re.I)
# GLM-OCR usually returns plain text or markdown, but on a few pages it emits a
# full HTML table on one line. The markup-only guard cannot catch it because the
# cells contain real words, so the tags reach narration and get read aloud:
# "table class table bordered thead tr th Name and Epithet". Measured on 3 of
# 208 DMG pages, ~8700 characters of markup.
HTML_TABLE_RE = re.compile(r"<\s*(table|tr|td|th|thead|tbody)\b", re.I)
HTML_TAG_RE = re.compile(r"<[a-zA-Z/][^>]*>")


def is_dice_table_header(ln):
    return bool(DICE_HEADER_RE.match(strip_markdown(ln)))


def is_dice_table_row(ln):
    return bool(TABLE_ROW_RE.match(strip_markdown(ln)))


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
        # Running header, e.g. "CHAPTER 6 | COSMOLOGY" or "APPENDIX B | MAPS",
        # which OCR transcribes on EVERY page. is_heading accepts it (short, all
        # caps), so without this it narrates mid-page and, worse, matches
        # narrate_worker's CHAPTER_RE and plants a bogus m4b chapter mark per
        # page. Real chapter openers are safe: they emit "CHAPTER 6" and
        # "COSMOLOGY" as separate lines with no pipe.
        if RUNNING_HEADER_RE.match(strip_markdown(stripped)):
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
        if HTML_TABLE_RE.search(stripped):
            blocks.append({"type": "table", "text": "A reference table is omitted here."})
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
        if is_dice_table_header(ln):
            # Look ahead and collect the rows. Only act if real numbered rows
            # follow, so a prose line merely mentioning "1d20" is not swallowed.
            j, row_texts = i + 1, []
            while j < n:
                s = lines[j].strip()
                if not s:
                    nxt = lines[j + 1].strip() if j + 1 < n else ""
                    if nxt and (is_dice_table_row(nxt) or is_dice_table_header(nxt)):
                        j += 1
                        continue
                    break
                if is_dice_table_header(s):
                    j += 1              # repeated column label mid-table, skip
                    continue
                if is_dice_table_row(s):
                    row_texts.append(strip_markdown(s))
                    j += 1
                    continue
                break
            if len(row_texts) >= 3:
                lens = sorted(len(t) for t in row_texts)
                median = lens[len(lens) // 2]
                # Short rows are unlistenable data ("1 Delicious food") and get
                # one marker. Long rows are real prose that merely happens to be
                # tabulated (DMG page 180's 1d10 adventure hooks run 100+ chars
                # each), so keep them and only drop the roll numbers and the
                # column label, which are the figure labels the rule excludes.
                if median < 60:
                    blocks.append({"type": "table",
                                   "text": "A random table is omitted here."})
                else:
                    for t in row_texts:
                        t = ROLL_PREFIX_RE.sub("", t)
                        if t:
                            blocks.append({"type": "body", "text": t})
                i = j
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
    # Label-list detector: a diagram transcribes as many SHORT, ALL-DISTINCT
    # lines, which the repetition check above cannot catch. Measured on the 2024
    # DMG's cosmology wheel (page 176): 43 blocks averaging 12 characters, which
    # would narrate as "Plane of Water. Plane of Ice. Feywild." The extraction
    # rule says never read figure labels, so collapse the page to one marker.
    # Real prose pages are nowhere near this: they run ~250 characters a block.
    bodies = [b["text"] for b in blocks if b["type"] in ("body", "heading")]
    if len(bodies) >= 15:
        lens = sorted(len(t) for t in bodies)
        median = lens[len(lens) // 2]
        total = sum(lens)
        # The total-volume ceiling is what makes this safe. Without it this also
        # ate DMG page 95, a page of random tables (2418 chars, "1d20 Claim to
        # Fame") that the number-heavy-list detector above already handles
        # correctly by keeping each table's title and omitting only its rows.
        # A real diagram page carries almost no text: page 176 is 553 chars.
        if median < 30 and total < 900:
            return [{"type": "omitted_data", "text": "A diagram is omitted here."}]
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
                # Preserve the full source span when a sentence crosses a page.
                # Assembly metadata can then map PDF-outline entries to the
                # first real audio on or after their page without changing the
                # narration segment identity.
                head_end = head.get("source_page_end", head.get("source_page"))
                if head_end is not None:
                    prev["source_page_end"] = head_end
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


def _page_lines_with_geom(page):
    """[(x0, y0, text)] for every nonempty, non-page-number line, reading
    order. A drop-cap (single letter rendered much larger than body text) is
    merged into the following line with no space; the merged line keeps the
    drop cap's geometry, as it always has."""
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
            raw.append((line["bbox"][0], line["bbox"][1], text, size))
    if not raw:
        return []
    sizes = sorted(s for _, _, _, s in raw)
    body_size = sizes[len(sizes) // 2]
    out = []
    skip_next_join = False
    for i, (x0, y0, text, size) in enumerate(raw):
        if skip_next_join:
            skip_next_join = False
            prev_x0, prev_y0, prev_text = out.pop()
            out.append((prev_x0, prev_y0, prev_text + text))
            continue
        if (
            re.fullmatch(r"[“”\"'‘’]?[A-Z]", text)
            and body_size > 0
            and size >= body_size * 1.4
            and i + 1 < len(raw)
        ):
            out.append((x0, y0, text))
            skip_next_join = True
            continue
        out.append((x0, y0, text))
    return out


def _page_lines_with_x(page):
    """[(x0, text)], the geometry-free view. Verse mode and mode detection
    read this and are unaffected by the paragraph-gap work below."""
    return [(x0, text) for x0, _, text in _page_lines_with_geom(page)]


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


# ---------- Path A paragraph style ----------
#
# The x-indent rule is primary and stays primary. But some books are typeset
# with no first-line indent at all and separate paragraphs with a blank line
# instead. On those the indent rule finds no boundary anywhere and degenerates
# to exactly one paragraph per page, which is what destroyed the paragraph
# structure of The Power of the Dog (726 blocks for 814 pages).
#
# Measured indent fractions over the narrated page ranges:
#   Power of the Dog 0.005   PHM 0.355   The Odyssey 0.422
# so the two populations are three orders apart and any low-percent threshold
# separates them. The fallback fires only when the indent signal is absent.

PARAGRAPH_INDENT_PT = 6.0          # the validated x-indent tolerance
PARAGRAPH_INDENT_MIN_FRACTION = 0.05
PARAGRAPH_GAP_RATIO = 1.5          # gap wider than this * leading = new para
PARAGRAPH_PROBE_PAGES = 24


def _sample_page_numbers(page_from, page_to, want):
    """Up to `want` 0-based page numbers spread evenly across a 1-based
    inclusive range."""
    total = page_to - page_from + 1
    if total <= want:
        return list(range(page_from - 1, page_to))
    step = total / float(want)
    return [page_from - 1 + int(i * step) for i in range(want)]


def _modal_leading(gaps):
    """Line-to-line spacing of body text, in points, from a list of observed
    top-to-top gaps.

    Not simply the most common gap. A book whose paragraphs are mostly one
    line long has MORE blank-line gaps than single-line gaps, so the raw mode
    would be twice the real leading, the threshold would land above every
    real gap, and no paragraph would ever be found. Instead take the smallest
    gap size that forms a real cluster (>= 20% of the peak bucket), which is
    the leading under either mix, then refine it to the median of the gaps in
    that neighbourhood so the returned value is not quantised to whole points.
    """
    if not gaps:
        return 0.0
    counts = {}
    for g in gaps:
        b = round(g)
        counts[b] = counts.get(b, 0) + 1
    peak = max(counts.values())
    clusters = sorted(b for b, c in counts.items() if c >= peak * 0.2 and b >= 4)
    if not clusters:
        return 0.0
    chosen = clusters[0]
    near = sorted(g for g in gaps if abs(g - chosen) <= 1.5)
    return near[len(near) // 2] if near else float(chosen)


def detect_paragraph_style(pdf_path, page_from, page_to):
    """
    Decide once, for the whole range, how prose paragraphs are marked.

    Returns (style, leading). style is "indent" (the original rule alone) or
    "gap" (indent rule plus a vertical-gap rule). leading is 0.0 for "indent"
    and the measured body leading in points for "gap"; a 0.0 leading disables
    the vertical rule, so an unreadable or ambiguous book falls back to
    exactly the original behaviour.

    The indent fraction is measured with the SAME definition the rule itself
    uses (per page: min x0, plus PARAGRAPH_INDENT_PT), so this cannot decide
    that the indent signal is present when the rule would not actually fire.
    """
    doc = fitz.open(pdf_path)
    try:
        indented = total_lines = 0
        gaps = []
        for pno in _sample_page_numbers(page_from, page_to, PARAGRAPH_PROBE_PAGES):
            lines = _page_lines_with_geom(doc.load_page(pno))
            if not lines:
                continue
            threshold = min(x0 for x0, _, _ in lines) + PARAGRAPH_INDENT_PT
            for x0, _, _ in lines:
                total_lines += 1
                if x0 > threshold:
                    indented += 1
            for i in range(1, len(lines)):
                gap = lines[i][1] - lines[i - 1][1]
                if gap > 0:
                    gaps.append(gap)
    finally:
        doc.close()
    if not total_lines:
        return "indent", 0.0
    if indented / float(total_lines) >= PARAGRAPH_INDENT_MIN_FRACTION:
        return "indent", 0.0
    return "gap", _modal_leading(gaps)


def _prose_page_paragraphs(lines_with_geom, leading=0.0):
    """path_a.py's validated x-indent rule: indented line = new paragraph.
    A chapter/division heading line is always split into its own paragraph,
    even if its indentation would otherwise merge it.

    When `leading` is nonzero the caller has measured this book's body line
    spacing (see detect_paragraph_style) and a vertical gap wider than
    PARAGRAPH_GAP_RATIO times that spacing ALSO starts a paragraph. The
    default leading=0.0 disables the vertical rule, which is the original
    behaviour exactly.
    """
    if not lines_with_geom:
        return []
    xs = sorted(x0 for x0, _, _ in lines_with_geom)
    left_margin = xs[0]
    indent_threshold = left_margin + PARAGRAPH_INDENT_PT
    gap_threshold = leading * PARAGRAPH_GAP_RATIO if leading > 0 else 0.0
    paras = []
    buf = ""
    prev_y0 = None
    for x0, y0, text in lines_with_geom:
        if HEADING_LINE_RE.match(text.strip()):
            if buf:
                paras.append(buf)
                buf = ""
            paras.append(text.strip())
            prev_y0 = y0
            continue
        starts_para = x0 > indent_threshold
        if not starts_para and gap_threshold and prev_y0 is not None:
            gap = y0 - prev_y0
            # A large negative gap is a jump back to the top of a new column,
            # not a continuation. A gap near zero is same-row text and joins.
            if gap > gap_threshold or gap < -gap_threshold:
                starts_para = True
        if starts_para:
            if buf:
                paras.append(buf)
            buf = text
        else:
            buf = (buf + " " + text) if buf else text
        prev_y0 = y0
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


def paragraphs_to_blocks(paragraphs, source_page=None):
    """Path A blocks: mostly body, with conservative heading detection."""
    blocks = []
    for p in paragraphs:
        if HEADING_LINE_RE.match(p.strip()):
            block = {"type": "heading", "text": strip_markdown(p)}
        elif is_heading(p):
            block = {"type": "heading", "text": strip_markdown(p)}
        else:
            block = {"type": "body", "text": strip_markdown(p)}
        if source_page is not None:
            block["source_page"] = int(source_page)
        blocks.append(block)
    return blocks


def extract_path_a(pdf_path, page_from, page_to, progress_cb=None):
    """
    Path A: whole page range -> stitched blocks.
    page_from/page_to are 1-based inclusive. Mode (prose vs verse) is
    auto-detected once for the range.
    """
    mode = detect_text_mode(pdf_path, page_from, page_to)
    # Verse groups by sentence runs and never consults indentation, so the
    # paragraph-style probe is prose-only.
    leading = 0.0
    if mode != "verse":
        _style, leading = detect_paragraph_style(pdf_path, page_from, page_to)
    doc = fitz.open(pdf_path)
    try:
        pages = []
        total = page_to - page_from + 1
        for idx, pno in enumerate(range(page_from - 1, page_to)):
            lines = _page_lines_with_geom(doc.load_page(pno))
            if mode == "verse":
                paras = _verse_page_paragraphs([(x0, t) for x0, _, t in lines])
            else:
                paras = _prose_page_paragraphs(lines, leading)
            pages.append(paragraphs_to_blocks(paras, source_page=pno + 1))
            if progress_cb:
                progress_cb(idx + 1, total)
        return stitch_pages(pages), mode
    finally:
        doc.close()


# ---------- Path B rasterize ----------

MAX_RASTER_MEGAPIXELS = 12.0


def rasterize_page(pdf_path, page_index, out_path, dpi=200,
                   max_megapixels=MAX_RASTER_MEGAPIXELS):
    """Render one page to an image for OCR, with a hard pixel budget.

    Books contain fold-out pages. The 2024 Dungeon Master's Guide page 154 is a
    4934x7000pt map, which at 200 dpi is 266 megapixels and wrote a 107 MB JPEG
    (typical page: 3.7 MP, 1.4 MB). Ollama rejected it with 413 Request Entity
    Too Large and killed the whole extraction 148 pages in. Scaling the dpi down
    to fit the budget keeps a normal page untouched (3.7 MP is far under it)
    while making an oversized page merely lower-resolution instead of fatal.
    """
    doc = fitz.open(pdf_path)
    try:
        page = doc.load_page(page_index)
        zoom = dpi / 72.0
        r = page.rect
        mp = (r.width * zoom) * (r.height * zoom) / 1e6
        if mp > max_megapixels:
            zoom *= (max_megapixels / mp) ** 0.5
        pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom))
        pix.save(out_path)
    finally:
        doc.close()
