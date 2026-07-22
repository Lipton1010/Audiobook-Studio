import fitz, re, os

PDF = r"D:\Audiobook_Pipeline\samples\Novel sample\PHM.pdf"
OUT = r"D:\Audiobook_Pipeline\extracted\path_a"
START_PAGE = 8
os.makedirs(OUT, exist_ok=True)

LIGATURES = {
    "\ufb00": "ff", "\ufb01": "fi", "\ufb02": "fl",
    "\ufb03": "ffi", "\ufb04": "ffl", "\ufb05": "st",
}

def normalize_ligatures(text):
    for k, v in LIGATURES.items():
        text = text.replace(k, v)
    return text

def page_paragraphs(page):
    """Return list of paragraph strings using x-indent to detect new paragraphs."""
    d = page.get_text("dict")
    # collect (x0, text) for every line in reading order
    lines = []
    for block in d["blocks"]:
        if block.get("type", 0) != 0:  # skip image blocks
            continue
        for line in block["lines"]:
            spans = line.get("spans", [])
            if not spans:
                continue
            text = "".join(s["text"] for s in spans).strip()
            if not text:
                continue
            x0 = line["bbox"][0]
            lines.append((x0, text))
    if not lines:
        return []
    # baseline left margin = the most common (smallest cluster) x0
    xs = sorted(x0 for x0, _ in lines)
    left_margin = xs[0]
    indent_threshold = left_margin + 6  # a few points past the margin = indented

    paras = []
    buf = ""
    for x0, text in lines:
        if x0 > indent_threshold:   # indented line = new paragraph
            if buf:
                paras.append(buf)
            buf = text
        else:
            buf = (buf + " " + text) if buf else text
    if buf:
        paras.append(buf)
    return paras

doc = fitz.open(PDF)

# group pages into chapters by image presence
chapters = []
current = None
for pno in range(START_PAGE - 1, doc.page_count):
    page = doc.load_page(pno)
    if len(page.get_images()) > 0:
        if current is not None:
            chapters.append(current)
        current = []
    if current is None:
        current = []
    current.append(page)
if current:
    chapters.append(current)

print("Chapters detected:", len(chapters))

combined = []
for idx, pages in enumerate(chapters, start=1):
    paras = []
    for page in pages:
        paras.extend(page_paragraphs(page))
    text = "\n\n".join(paras)
    text = normalize_ligatures(text)
    text = re.sub(r'^(\s*[“"]?)([A-Z])\s+([a-z])', r'\1\2\3', text)  # drop-cap, newline or space
    text = re.sub(r'^(\s*[“"]?)([A-Z])\n+([a-z])', r'\1\2\3', text)  # drop-cap across a line break
    fname = os.path.join(OUT, f"chapter_{idx:02d}.txt")
    with open(fname, "w", encoding="utf-8") as f:
        f.write(text)
    combined.append(f"\n\n===== CHAPTER {idx} =====\n\n" + text)
    print(f"  chapter_{idx:02d}.txt  ({len(text)} chars, {len(paras)} paragraphs)")

with open(os.path.join(OUT, "full_book.txt"), "w", encoding="utf-8") as f:
    f.write("".join(combined))

print("Done. Wrote to", OUT)