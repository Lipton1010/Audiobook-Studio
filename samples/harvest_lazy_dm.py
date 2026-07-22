import sys
import os
import re
import json
import base64
import glob
import requests
import fitz  # PyMuPDF

MODEL = "glm-ocr-doc"
OCR_PROMPT = "Transcribe this document page as clean Markdown, preserving reading order and tables."
DPI = 200


# ---------- stage_two.py tagging logic, copied verbatim to avoid a second dependency ----------

def is_table_row(ln):
    s = ln.strip()
    return s.startswith("|") and s.endswith("|") and s.count("|") >= 2

def is_heading(ln):
    s = ln.strip().strip("*").strip()
    if len(s) < 2 or len(s) > 60:
        return False
    if s[-1] in ".?!:,;":
        return False
    letters = [c for c in s if c.isalpha()]
    if not letters:
        return False
    return all(c.isupper() for c in letters)

def is_dialogue(ln):
    s = ln.strip().strip("*").strip()
    m = re.match(r"^([A-Z][a-zA-Z]+)(\s[A-Z][a-zA-Z]+)?:\s+\S", s)
    return bool(m)

def is_number_heavy_list(ln):
    s = ln.strip()
    if not (s.startswith("-") or s.startswith("\u2022")):
        return False
    s = s.lstrip("-\u2022").strip()
    s = re.sub(r"^[A-Za-z][A-Za-z0-9 ]{0,15}:\s*", "", s)
    tokens = s.split()
    if not tokens:
        return False
    numeric = sum(1 for t in tokens if re.fullmatch(r"\d+|dead", t.strip(".,;")))
    return numeric >= max(1, len(tokens) // 2)

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
            blocks.append({"type": "heading", "text": ln.strip().strip("*").strip()})
            i += 1
            continue
        if is_dialogue(ln):
            blocks.append({"type": "dialogue", "text": ln.strip().strip("*").strip()})
            i += 1
            continue
        blocks.append({"type": "body", "text": ln.strip()})
        i += 1
    return blocks


# ---------- pipeline steps ----------

def pdf_to_image(pdf_path, out_dir):
    doc = fitz.open(pdf_path)
    if doc.page_count < 1:
        doc.close()
        raise ValueError(f"{pdf_path} has no pages")
    page = doc.load_page(0)
    zoom = DPI / 72.0
    mat = fitz.Matrix(zoom, zoom)
    pix = page.get_pixmap(matrix=mat)
    base = os.path.splitext(os.path.basename(pdf_path))[0]
    safe_base = "".join(c if c.isalnum() else "_" for c in base).strip("_")
    while "__" in safe_base:
        safe_base = safe_base.replace("__", "_")
    out_path = os.path.join(out_dir, safe_base + ".jpg")
    pix.save(out_path)
    doc.close()
    return out_path, safe_base


def call_glm_ocr(image_path):
    with open(image_path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("utf-8")
    payload = {
        "model": MODEL,
        "prompt": OCR_PROMPT,
        "images": [b64],
        "stream": False,
        "options": {"temperature": 0, "num_ctx": 16384},
    }
    r = requests.post("http://localhost:11434/api/generate", json=payload, timeout=900)
    r.raise_for_status()
    return r.json()["response"]


def main():
    if len(sys.argv) < 2:
        print("Usage: python harvest_lazy_dm.py <folder_of_single_page_pdfs>")
        sys.exit(1)

    src_dir = sys.argv[1]
    image_dir = os.path.join(r"D:\Audiobook_Pipeline\samples", "image_samples")
    out_dir = os.path.join(r"D:\Audiobook_Pipeline\samples", "harvest_output")
    os.makedirs(image_dir, exist_ok=True)
    os.makedirs(out_dir, exist_ok=True)

    pdf_paths = sorted(glob.glob(os.path.join(src_dir, "*.pdf")))
    if not pdf_paths:
        print(f"No PDFs found in {src_dir}")
        sys.exit(1)

    print(f"Found {len(pdf_paths)} PDF(s) in {src_dir}")
    print()

    results = []
    for idx, pdf_path in enumerate(pdf_paths, start=1):
        name = os.path.basename(pdf_path)
        print(f"[{idx}/{len(pdf_paths)}] {name}")
        try:
            image_path, safe_base = pdf_to_image(pdf_path, image_dir)
            print(f"    image saved: {image_path}")

            md_text = call_glm_ocr(image_path)
            md_path = os.path.join(out_dir, safe_base + ".md")
            with open(md_path, "w", encoding="utf-8") as f:
                f.write(md_text)
            print(f"    OCR saved:   {md_path}")

            blocks = tag_blocks(md_text)
            tagged_path = os.path.join(out_dir, safe_base + ".tagged.json")
            with open(tagged_path, "w", encoding="utf-8") as f:
                json.dump({"blocks": blocks}, f, ensure_ascii=False, indent=2)
            print(f"    tagged saved:{tagged_path}")

            type_counts = {}
            for b in blocks:
                type_counts[b["type"]] = type_counts.get(b["type"], 0) + 1
            print(f"    block types: {type_counts}")

            results.append({"pdf": name, "status": "ok", "tagged_path": tagged_path, "type_counts": type_counts})
        except Exception as e:
            print(f"    FAILED: {e}")
            results.append({"pdf": name, "status": "failed", "error": str(e)})
        print()

    print("===== SUMMARY =====")
    ok = [r for r in results if r["status"] == "ok"]
    failed = [r for r in results if r["status"] == "failed"]
    print(f"{len(ok)} succeeded, {len(failed)} failed, out of {len(results)} total")
    if failed:
        print("Failed files:")
        for r in failed:
            print(f"  {r['pdf']}: {r['error']}")
    print(f"Output folder: {out_dir}")


if __name__ == "__main__":
    main()
