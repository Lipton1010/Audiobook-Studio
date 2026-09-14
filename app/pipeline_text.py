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
ITERATION_NUMBER_RE = (
    r"(?:\d+|[IVXLCDM]+|first|second|third|fourth|fifth|sixth|seventh|"
    r"eighth|ninth|tenth|eleventh|twelfth|thirteenth|fourteenth|fifteenth|"
    r"sixteenth|seventeenth|eighteenth|nineteenth|twentieth|one|two|three|"
    r"four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|"
    r"fifteen|sixteen|seventeen|eighteen|nineteen|twenty)"
)
ITERATION_HEADING_RE = re.compile(
    r"^(?:" + ITERATION_NUMBER_RE + r"\s+iteration|iteration\s+" +
    ITERATION_NUMBER_RE + r")$", re.IGNORECASE,
)


def strip_markdown(text):
    """Remove markdown emphasis markers and stray heading hashes, keep content."""
    prev = None
    while prev != text:
        prev = text
        text = MD_EMPHASIS_RE.sub(lambda m: m.group(1) or m.group(2), text)
    text = re.sub(r"^#{1,6}\s*", "", text.strip())
    # Safety net for stray inline HTML from OCR. Whole HTML tables are retained
    # as visual blocks; this stops a lone <br> or <em> from being spoken.
    # Requires a letter or slash after "<" so ordinary prose
    # comparisons are untouched.
    text = HTML_TAG_RE.sub(" ", text)
    text = re.sub(r"\s+", " ", text)  # collapse stray double spaces from PDF extraction
    return text.strip()


def is_table_row(ln):
    s = ln.strip()
    return s.startswith("|") and s.endswith("|") and s.count("|") >= 2


def is_heading(ln):
    s = strip_markdown(ln)
    if ITERATION_HEADING_RE.match(s):
        return True
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
CODE_LINE_RE = re.compile(r"^\s*\[-?[A-Z]{2,}[A-Z0-9-]*\]\s*$")
LOOSE_LOG_ROW_RE = re.compile(r"^\s*\d{2}:\d{2}:\d{2}\s{2,}\S")
PARTIAL_PIPE_ROW_RE = re.compile(r"^\s*\|[^|]+\|[^|]+")
VISUAL_INDICATOR_RE = re.compile(
    r"^\s*(?:!\[[^]]*\]\([^)]*\)|\[(?:image|figure|diagram|chart|map)\b[^]]*\]|"
    r"(?:figure|fig\.?|diagram|chart|image|illustration|map)\s*(?:\d+\s*[.:]|:))",
    re.I,
)


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


def _visual_block(text, visual_kind):
    """Keep extracted visual source for review without turning it into speech."""
    return {"type": "visual", "text": text, "visual_kind": visual_kind}


def _visual_line_kind(line):
    if HTML_TABLE_RE.search(line):
        return "HTML table"
    if is_table_row(line):
        return "Markdown table"
    if PARTIAL_PIPE_ROW_RE.match(line):
        return "partial Markdown table"
    if CODE_LINE_RE.fullmatch(line):
        return "standalone code"
    if LOOSE_LOG_ROW_RE.match(line):
        return "structured log row"
    if VISUAL_INDICATOR_RE.match(line):
        return "image or diagram indication"
    return None


def _is_numeric_column_row(line):
    words = line.strip().split()
    if not 2 <= len(words) <= 6 or line.rstrip().endswith((".", "?", "!")):
        return False
    return sum(word.replace(",", "").isdigit() for word in words) >= 2


def _is_table_header(line):
    words = line.strip().split()
    return (2 <= len(words) <= 5 and line.rstrip()[-1:] not in TERMINAL_PUNCT
            and all(word.replace("-", "").isalpha() for word in words))


def _visual_kind_at(lines, index):
    line = lines[index]
    kind = _visual_line_kind(line)
    if kind:
        return kind
    numeric = _is_numeric_column_row(line)
    before = index > 0 and _is_numeric_column_row(lines[index - 1])
    after = index + 1 < len(lines) and _is_numeric_column_row(lines[index + 1])
    if numeric and (before or after):
        return "plain-text table row"
    if (_is_table_header(line) and index + 2 < len(lines)
            and _is_numeric_column_row(lines[index + 1])
            and _is_numeric_column_row(lines[index + 2])):
        return "plain-text table header"
    return None


def _group_visual_kind(kinds):
    if "structured log row" in kinds:
        return "structured log"
    if "Markdown table" in kinds:
        return "Markdown table"
    if "partial Markdown table" in kinds or "plain-text table row" in kinds:
        return "plain-text table"
    return kinds[0]


def _collapse_label_runs(blocks):
    """Collapse only a dense run of diagram labels, never its nearby prose."""
    collapsed = []
    i = 0
    while i < len(blocks):
        run = []
        while i < len(blocks):
            block = blocks[i]
            text = block["text"]
            if (block["type"] != "body" or text.lstrip().startswith(("\"", "“", "'", "‘"))
                    or len(text) >= 30 or text.rstrip()[-1:] in TERMINAL_PUNCT):
                break
            run.append(block)
            i += 1
        if len(run) >= 15 and len({block["text"] for block in run}) == len(run) \
                and sum(len(block["text"]) for block in run) < 900:
            visual = _visual_block("\n".join(block["text"] for block in run), "diagram labels")
            if "source_page" in run[0]:
                visual["source_page"] = run[0]["source_page"]
            collapsed.append(visual)
        else:
            collapsed.extend(run)
        if i < len(blocks):
            collapsed.append(blocks[i])
            i += 1
    return collapsed


def retag_legacy_visual_blocks(blocks):
    """Conservatively expose visual candidates in older block caches."""
    texts = [block.get("text", "") for block in blocks]
    retagged = []
    for index, original in enumerate(blocks):
        block = dict(original)
        if block.get("type") in ("table", "omitted_data"):
            block["type"] = "visual"
            block.setdefault("visual_kind", "legacy omitted visual")
        elif block.get("type") == "body":
            lines = block.get("text", "").splitlines() or [block.get("text", "")]
            kinds = [_visual_kind_at(lines, line_index) for line_index in range(len(lines))]
            if kinds and all(kinds):
                block["type"] = "visual"
                block["visual_kind"] = _group_visual_kind(kinds)
            elif _visual_kind_at(texts, index):
                block["type"] = "visual"
                block["visual_kind"] = _visual_kind_at(texts, index)
        retagged.append(block)
    return _collapse_label_runs(retagged)


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
        if HTML_TABLE_RE.search(stripped):
            blocks.append(_visual_block(ln, "HTML table"))
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
        visual_kind = _visual_kind_at(lines, i)
        if visual_kind:
            visual_lines, kinds = [], []
            while i < n:
                kind = _visual_kind_at(lines, i)
                if kind:
                    visual_lines.append(lines[i])
                    kinds.append(kind)
                    i += 1
                elif not lines[i].strip() and i + 1 < n and _visual_kind_at(lines, i + 1):
                    visual_lines.append(lines[i])
                    i += 1
                else:
                    break
            blocks.append(_visual_block("\n".join(visual_lines), _group_visual_kind(kinds)))
            continue
        if is_dice_table_header(ln):
            # Look ahead and collect the rows. Only act if real numbered rows
            # follow, so a prose line merely mentioning "1d20" is not swallowed.
            j, row_count = i + 1, 0
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
                    row_count += 1
                    j += 1
                    continue
                break
            if row_count >= 3:
                # Random-table rows stay together as a visual record. Their
                # length does not make the layout prose, and retaining the raw
                # lines lets the reviewer decide what belongs in narration.
                blocks.append(_visual_block("\n".join(lines[i:j]), "random table"))
                i = j
                continue
        if is_number_heavy_list(ln):
            data_lines = []
            while i < n and (is_number_heavy_list(lines[i]) or not lines[i].strip()):
                if not lines[i].strip():
                    if i + 1 < n and is_number_heavy_list(lines[i + 1]):
                        data_lines.append(lines[i])
                        i += 1
                        continue
                    else:
                        break
                data_lines.append(lines[i])
                i += 1
            blocks.append(_visual_block("\n".join(data_lines), "number-heavy data list"))
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
            return [_visual_block(raw_text, "uncertain repeated OCR artwork")]
    # A diagram can transcribe as many short, distinct labels. Restrict the
    # collapse to that contiguous body-only run so headings and nearby prose
    # remain in their original order.
    return _collapse_label_runs(blocks)


COPYRIGHT_PRIMARY_RE = re.compile(
    r"^\s*(?:copyright\s*(?:©|\(c\))?\s*|©\s*)(?:19|20)\d{2}\b",
    re.IGNORECASE,
)
RIGHTS_LINE_RE = re.compile(
    r"^\s*(?:all rights reserved\.?|isbn(?:-1[03])?\s*[:#]?\s*[\d-]+|"
    r"library of congress(?:\s+cataloging)?.*|no part of (?:this )?(?:book|publication).*|"
    r"(?:reproduction|reproduced).*permission.*|printed in\s+\w+.*)\s*$",
    re.IGNORECASE,
)


def is_copyright_notice(text):
    """Return true only for structured publication-rights boilerplate.

    A bare mention of copyright can be ordinary prose, so it is never enough.
    The cue must be an anchored copyright statement with a publication year.
    """
    normalized = re.sub(r"\s+", " ", text or " ").strip()
    if not COPYRIGHT_PRIMARY_RE.match(normalized) or len(normalized) > 220:
        return False
    sentences = [part.strip() for part in re.split(r"(?<=[.!?])\s+", normalized) if part.strip()]
    # A fused OCR/PDF paragraph can begin with a notice and continue directly
    # into the book. Leave that block intact rather than risking its prose.
    return all(index == 0 or RIGHTS_LINE_RE.match(sentence)
               for index, sentence in enumerate(sentences))


def filter_copyright_blocks(blocks):
    """Drop publication notices while preserving ordinary text and provenance."""
    notices = [is_copyright_notice(block.get("text", "")) for block in blocks]
    rights_lines = [bool(RIGHTS_LINE_RE.match(block.get("text", ""))) for block in blocks]
    # A genuinely boilerplate page often wraps its notice into several blocks.
    # Remove every block only when its primary notice has multiple independent
    # publication markers and every block is itself publication boilerplate.
    only_boilerplate = bool(blocks) and all(
        notice or rights for notice, rights in zip(notices, rights_lines)
    )
    if any(notices) and sum(rights_lines) >= 2 and only_boilerplate:
        return []
    filtered = []
    for index, block in enumerate(blocks):
        adjacent_notice = any(notices[max(0, index - 3):index + 4])
        if notices[index] or (adjacent_notice and rights_lines[index]):
            continue
        filtered.append(block)
    return filtered


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
        page_blocks = [b for b in page_blocks
                       if b["type"] == "visual" or b["text"].strip()]
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
NUMBERED_COLON_HEADING_RE = re.compile(r"^\d+\s*:\s*[A-Z][A-Z '&-]{1,58}$")


def _is_division_heading(text):
    return bool(HEADING_LINE_RE.match(text) or NUMBERED_COLON_HEADING_RE.match(text))

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
        if _is_division_heading(text.strip()):
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
        if _is_division_heading(text):
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
        if _is_division_heading(p.strip()):
            block = {"type": "heading", "text": strip_markdown(p)}
        elif is_heading(p):
            block = {"type": "heading", "text": strip_markdown(p)}
        else:
            block = {"type": "body", "text": strip_markdown(p)}
        if source_page is not None:
            block["source_page"] = int(source_page)
        blocks.append(block)
    return blocks


def _path_a_page_blocks(lines, mode, leading, source_page):
    """Tag visual lines before paragraphing the remaining Path A prose."""
    blocks, prose_lines = [], []
    raw_lines = [line[2] for line in lines]

    def flush_prose():
        if not prose_lines:
            return
        if mode == "verse":
            paragraphs = _verse_page_paragraphs([(x0, text) for x0, _, text in prose_lines])
        else:
            paragraphs = _prose_page_paragraphs(prose_lines, leading)
        blocks.extend(paragraphs_to_blocks(paragraphs, source_page=source_page))
        prose_lines.clear()

    i = 0
    while i < len(lines):
        kinds = []
        if _visual_kind_at(raw_lines, i):
            flush_prose()
            visual_lines = []
            while i < len(lines):
                kind = _visual_kind_at(raw_lines, i)
                if not kind:
                    break
                visual_lines.append(lines[i][2])
                kinds.append(kind)
                i += 1
            visual = _visual_block("\n".join(visual_lines), _group_visual_kind(kinds))
            visual["source_page"] = source_page
            blocks.append(visual)
        else:
            prose_lines.append(lines[i])
            i += 1
    flush_prose()
    return blocks


def _page_graphics(page, source_page):
    """Return page graphics with their vertical position when PDF exposes it."""
    try:
        images = page.get_images(full=True)
        drawings = page.get_drawings()
    except (AttributeError, RuntimeError):
        return []
    graphics = []
    for image in images:
        try:
            rects = page.get_image_rects(image[0])
        except (AttributeError, RuntimeError):
            rects = []
        if rects:
            for rect in rects:
                graphics.append((rect.y0, _visual_block("", "embedded image")))
        else:
            graphics.append((float("inf"), _visual_block("", "embedded image")))
    # One vector path is commonly a decorative rule. Several independent paths
    # are a conservative signal for a chart or diagram without text.
    if len(drawings) >= 3:
        rects = sorted((drawing["rect"] for drawing in drawings if "rect" in drawing),
                       key=lambda rect: rect.y0)
        bands = []
        for rect in rects:
            if bands and rect.y0 <= bands[-1][1] + 6:
                bands[-1][1] = max(bands[-1][1], rect.y1)
            else:
                bands.append([rect.y0, rect.y1])
        for top, _bottom in bands or [(float("inf"), float("inf"))]:
            graphics.append((top, _visual_block("", "vector graphic")))
    for _, block in graphics:
        block["source_page"] = source_page
    return sorted(graphics, key=lambda item: item[0])


def _page_graphic_blocks(page, source_page):
    """Compatibility helper for callers that only need the visual records."""
    return [block for _, block in _page_graphics(page, source_page)]


def _insert_page_graphics(page_blocks, graphics, lines):
    """Insert each graphic at its text-line boundary without splitting headings."""
    for y0, graphic in graphics:
        insert_at = len(page_blocks)
        split_at = None
        search_block, search_offset = 0, 0
        for _, line_y, text in lines:
            needle = strip_markdown(text)
            if not needle:
                continue
            for index in range(search_block, len(page_blocks)):
                block = page_blocks[index]
                if block["type"] not in ("body", "heading"):
                    continue
                offset = block["text"].find(needle, search_offset if index == search_block else 0)
                if offset < 0:
                    continue
                search_block, search_offset = index, offset + len(needle)
                if line_y >= y0:
                    insert_at = index
                    split_at = offset if block["type"] == "body" else None
                break
            if insert_at != len(page_blocks):
                break
        if split_at:
            block = page_blocks[insert_at]
            before = block["text"][:split_at].rstrip()
            after = block["text"][split_at:].lstrip()
            if before and after:
                block["text"] = before
                tail = dict(block)
                tail["text"] = after
                page_blocks[insert_at + 1:insert_at + 1] = [graphic, tail]
                continue
        page_blocks.insert(insert_at, graphic)
    return page_blocks


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
            page = doc.load_page(pno)
            lines = _page_lines_with_geom(page)
            page_blocks = filter_copyright_blocks(
                _path_a_page_blocks(lines, mode, leading, source_page=pno + 1)
            )
            pages.append(_insert_page_graphics(
                page_blocks, _page_graphics(page, pno + 1), lines
            ))
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
