"""
A/B prep (base env, stdlib only): extract the exact chunk plan the pipeline
would narrate from a job's blocks.json, then select a representative sample
for batched-vs-v1 comparison. Chunking logic is copied VERBATIM from
narrate_worker.py so the A/B inputs are identical to production.

Usage: python ab_extract_chunks.py <job_dir> <out_json> [profile A|B]
Writes out_json = {"chunks": [{"index","text","is_heading","char_len"}...]}
"""
import json
import re
import sys
from pathlib import Path

# ---- verbatim from narrate_worker.py ----
CHAR_CEILING = 400
SENTENCE_SPLIT_RE = re.compile(r'(?<=[.!?])\s+(?=[A-Z"\'‘“])')
PAUSE_PROFILES = {
    "B": {"gap_ms": 50, "block_gap_ms": 100, "heading_before_ms": 200, "heading_after_ms": 150},
    "A": {"gap_ms": 150, "block_gap_ms": 400, "heading_before_ms": 200, "heading_after_ms": 150},
}


def split_sentences(paragraph):
    paragraph = paragraph.strip()
    if not paragraph:
        return []
    parts = SENTENCE_SPLIT_RE.split(paragraph)
    return [p.strip() for p in parts if p.strip()]


def pack_text(text, ceiling=CHAR_CEILING):
    sentences = split_sentences(text)
    if not sentences:
        return []
    chunks = []
    current = ""
    for sent in sentences:
        candidate = (current + " " + sent).strip() if current else sent
        if len(candidate) <= ceiling:
            current = candidate
        else:
            if current:
                chunks.append(current)
            if len(sent) > ceiling:
                sub_parts = re.split(r"(?<=[,;])\s+", sent)
                buf = ""
                for sp in sub_parts:
                    cand2 = (buf + " " + sp).strip() if buf else sp
                    if len(cand2) <= ceiling:
                        buf = cand2
                    else:
                        if buf:
                            chunks.append(buf)
                        buf = sp
                current = buf
            else:
                current = sent
    if current:
        chunks.append(current)
    return chunks


def normalize_quoted_ellipsis(text):
    quote_pairs = [('"', '"'), ("“", "”"), ("'", "'"), ("‘", "’")]
    result = text
    for open_q, close_q in quote_pairs:
        pattern = re.escape(open_q) + r"([^" + re.escape(open_q) + re.escape(close_q) + r"]*?)" + re.escape(close_q)

        def replacer(m):
            inner = re.sub(r"\.{2,}", "", m.group(1)).rstrip()
            return open_q + inner + close_q

        result = re.sub(pattern, replacer, result)
    return result


def build_plan(blocks, profile):
    plan = []
    n = len(blocks)
    for i, b in enumerate(blocks):
        text = normalize_quoted_ellipsis(b["text"].strip())
        if not text:
            continue
        last_block = i == n - 1
        if b["type"] == "heading":
            plan.append({"text": text, "heading": True})
        else:
            subs = pack_text(text)
            for sc in subs:
                plan.append({"text": sc, "heading": False})
    return plan
# ---- end verbatim ----


def main():
    job_dir = Path(sys.argv[1])
    out_json = Path(sys.argv[2])
    profile = PAUSE_PROFILES[sys.argv[3] if len(sys.argv) > 3 else "A"]
    blocks = json.loads((job_dir / "blocks.json").read_text(encoding="utf-8"))["blocks"]
    plan = build_plan(blocks, profile)

    body = [(i, p) for i, p in enumerate(plan) if not p["heading"]]
    headings = [(i, p) for i, p in enumerate(plan) if p["heading"]]
    lens = sorted(body, key=lambda ip: len(ip[1]["text"]))

    # Representative spread: shortest, longest, some mid, some with dialogue quotes,
    # plus a couple of headings. Keep 12-14 chunks total for a fast but telling A/B.
    picks = []
    seen = set()

    def add(idx_plan, text, is_heading):
        if idx_plan in seen:
            return
        seen.add(idx_plan)
        picks.append({"index": idx_plan, "text": text, "is_heading": is_heading, "char_len": len(text)})

    if lens:
        add(*[lens[0][0], lens[0][1]["text"], False])          # shortest
        add(*[lens[-1][0], lens[-1][1]["text"], False])         # longest
        for frac in (0.25, 0.5, 0.75):
            i, p = lens[int(len(lens) * frac)]
            add(i, p["text"], False)
    # dialogue-bearing chunks (quotes) stress prosody
    dlg = [(i, p) for i, p in body if '"' in p["text"] or "“" in p["text"]]
    for i, p in dlg[:4]:
        add(i, p["text"], False)
    # a few consecutive mid-book body chunks (continuity / no cross-talk check)
    mid = len(body) // 2
    for i, p in body[mid:mid + 3]:
        add(i, p["text"], False)
    if headings:
        add(headings[0][0], headings[0][1]["text"], True)

    picks.sort(key=lambda c: c["index"])
    out = {
        "job_dir": str(job_dir),
        "total_plan_chunks": len(plan),
        "n_body": len(body),
        "chunks": picks,
    }
    out_json.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"plan has {len(plan)} chunks ({len(body)} body, {len(headings)} heading)")
    print(f"selected {len(picks)} chunks -> {out_json}")
    for c in picks:
        print(f"  [{c['index']:4d}] len={c['char_len']:3d} hd={int(c['is_heading'])} {c['text'][:70]!r}")


if __name__ == "__main__":
    main()
