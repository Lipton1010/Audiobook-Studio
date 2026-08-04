"""Step 1 of the throughput benchmark: dump the OLD and NEW production chunk
plans for one book. Runs in the BASE env (needs fitz; the chatterbox env has no
PyMuPDF). Writes only to the gitignored Output tree.

Step 2 is app/bench_throughput.py, which runs in the chatterbox env and does
the GPU timing.

CLAUDE.md's benchmarking rule is the whole point of this file: three earlier
benchmarks gave wrong answers because they tokenized raw blocks.json text
instead of the production chunk plan. Raw blocks reach 792 tokens while real
chunks cap near 271, which is a completely different batching regime. So the
chunk list here comes from the real narrate_worker.build_plan and nothing else.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
APP = REPO / "app"


class _Stub:
    def __getattr__(self, n):
        return _Stub()

    def __call__(self, *a, **k):
        return _Stub()


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    sys.modules[name] = m
    spec.loader.exec_module(m)
    return m


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdf", default=str(
        REPO / "source_pdfs" / "The Power of the Dog - Don Winslow.pdf"))
    ap.add_argument("--page-from", type=int, default=5)
    ap.add_argument("--page-to", type=int, default=818)
    ap.add_argument("--profile", default="A", choices=["A", "B"])
    ap.add_argument("--verify-against-rev", default="016c29a",
                    help="commit holding the PRE-FIX pipeline_text.py; the "
                         "derived OLD arm is checked byte-for-byte against it. "
                         "Empty string skips the check.")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    out = Path(args.out).resolve()
    if out.exists():
        raise FileExistsError(out)
    pdf = Path(args.pdf).resolve()
    if not pdf.is_file():
        raise FileNotFoundError(pdf)

    sys.path.insert(0, str(APP))
    for n in ("numpy", "soundfile", "perth", "chatterbox", "chatterbox.tts"):
        sys.modules.setdefault(n, _Stub())
    nw = _load(APP / "narrate_worker.py", "nw_bench")
    new_pt = _load(APP / "pipeline_text.py", "pt_bench_new")

    # The OLD arm cannot come from HEAD any more: the adaptive rule is committed,
    # so HEAD is the new behaviour. Derive it instead by disabling the vertical
    # rule, which is the pre-fix behaviour BY CONSTRUCTION (a leading of 0.0
    # makes gap_threshold falsy, leaving only the x-indent rule). That claim is
    # then PROVEN below against the real pre-fix commit rather than asserted.
    def _extract_old():
        original = new_pt.detect_paragraph_style
        new_pt.detect_paragraph_style = lambda *a, **k: ("indent", 0.0)
        try:
            return new_pt.extract_path_a(str(pdf), args.page_from, args.page_to)
        finally:
            new_pt.detect_paragraph_style = original

    old_blocks, old_mode = _extract_old()
    new_blocks, new_mode = new_pt.extract_path_a(
        str(pdf), args.page_from, args.page_to)

    verified_against = None
    if args.verify_against_rev:
        try:
            src = subprocess.check_output(
                ["git", "-C", str(REPO), "show",
                 f"{args.verify_against_rev}:app/pipeline_text.py"],
                stderr=subprocess.DEVNULL)
        except subprocess.CalledProcessError:
            print(f"  WARNING: rev {args.verify_against_rev} not resolvable; "
                  f"the OLD arm is unverified against real pre-fix code")
        else:
            fd, hp = tempfile.mkstemp(suffix="_prefix_pt.py")
            with os.fdopen(fd, "wb") as fh:
                fh.write(src)
            try:
                hist = _load(Path(hp), "pt_bench_prefix")
                hb, hm = hist.extract_path_a(str(pdf), args.page_from, args.page_to)
            finally:
                os.unlink(hp)
            if hb != old_blocks or hm != old_mode:
                raise ValueError(
                    f"the derived OLD arm does not match rev "
                    f"{args.verify_against_rev}: {len(old_blocks)} blocks vs "
                    f"{len(hb)}. The gap-rule-disabled path is NOT the pre-fix "
                    f"behaviour, so this benchmark would compare the wrong thing."
                )
            verified_against = args.verify_against_rev
            print(f"  OLD arm verified byte-for-byte against rev "
                  f"{args.verify_against_rev} ({len(hb):,} blocks)")

    try:
        arms = {}
        for label, (blocks, mode) in (("old", (old_blocks, old_mode)),
                                      ("new", (new_blocks, new_mode))):
            plan = nw.build_plan(blocks, nw.PAUSE_PROFILES[args.profile])
            texts = [p["text"] for p in plan]
            lens = sorted(len(t) for t in texts)
            arms[label] = {
                "text_mode": mode,
                "blocks": len(blocks),
                "body_blocks": sum(1 for b in blocks if b["type"] == "body"),
                "chunks": len(texts),
                "chars": sum(lens),
                "median_chunk_chars": lens[len(lens) // 2],
                "mean_chunk_chars": sum(lens) // len(lens),
                "max_chunk_chars": lens[-1],
                "chunks_over_400": sum(1 for x in lens if x > 400),
                "chunks_under_30": sum(1 for x in lens if x < 30),
                "texts": texts,
            }
    finally:
        pass

    if arms["new"]["chunks"] == arms["old"]["chunks"]:
        raise ValueError(
            "old and new plans have the same chunk count, so this book has no "
            "boundary difference to benchmark. Pick a gap-style book."
        )

    payload = {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "scope": "private_gitignored_benchmark_input",
        "pdf_name": pdf.name,
        "page_from": args.page_from,
        "page_to": args.page_to,
        "pause_profile": args.profile,
        "old_arm_derivation": "detect_paragraph_style forced to (indent, 0.0)",
        "old_arm_verified_against_rev": verified_against,
        "working_pipeline_text_sha256": hashlib.sha256(
            (APP / "pipeline_text.py").read_bytes()).hexdigest(),
        "arms": arms,
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("x", encoding="utf-8", newline="\n") as fh:
        json.dump(payload, fh, ensure_ascii=False)
        fh.write("\n")

    print(f"wrote plan dump: {out}  ({out.stat().st_size:,} bytes)")
    for label in ("old", "new"):
        a = arms[label]
        print(f"  {label}: {a['chunks']:,} chunks  median {a['median_chunk_chars']} "
              f"mean {a['mean_chunk_chars']} max {a['max_chunk_chars']}  "
              f"under30 {a['chunks_under_30']:,}  over400 {a['chunks_over_400']}")
    print(f"  ratio new/old chunks: "
          f"{arms['new']['chunks'] / arms['old']['chunks']:.2f}x")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
