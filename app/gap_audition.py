"""Blind three-way audition of block_gap_ms, assembled from segments already
on disk. No GPU, no re-narration: pauses are inserted at assembly, so this is
pure concatenation.

Why these three values. Measured against the commercial recording of the same
book (timing statistics only):
  * the model itself contributes 380 ms of padding across every join, so the
    nominal block_gap_ms is NOT the audible gap; today's 400 sounds like 780.
  * the commercial narrator's paragraph-band median is 890 ms, which implies
    a nominal 510.
  * 650 is included as the deliberate overshoot, because the commercial p90
    is 1030 ms and our long-pause register is far thinner than theirs.

Runs in the BASE env; only numpy and soundfile-free WAV IO are needed.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import secrets
import sys
import wave
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parent.parent
APP = REPO / "app"
GAPS = (400, 510, 650)


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    sys.modules[name] = m
    spec.loader.exec_module(m)
    return m


def read_wav(p: Path):
    with wave.open(str(p), "rb") as w:
        sr, n = w.getframerate(), w.getnframes()
        x = np.frombuffer(w.readframes(n), dtype=np.int16)
    return x.astype(np.float32) / 32768.0, sr


def write_wav(p: Path, x: np.ndarray, sr: int):
    p.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(p), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(np.clip(x, -1.0, 1.0).astype(np.float32).__mul__(32767)
                      .astype(np.int16).tobytes())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--job", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--target-seconds", type=float, default=240.0)
    ap.add_argument("--start-chunk", type=int, default=None)
    ap.add_argument("--num-chunks", type=int, default=None,
                    help="exact chunk count, to reproduce a prior excerpt")
    ap.add_argument("--gaps", default=",".join(str(g) for g in GAPS),
                    help="comma-separated block_gap_ms values, exactly three")
    args = ap.parse_args()
    gaps = tuple(int(g) for g in args.gaps.split(","))
    if len(gaps) != 3 or len(set(gaps)) != 3:
        raise ValueError("need exactly three distinct gap values")

    job = Path(args.job).resolve()
    out = Path(args.out).resolve()
    if out.exists():
        raise FileExistsError(out)
    seg_dir = job / "segments"

    sys.path.insert(0, str(APP))
    # narrate_worker imports perth at module level and resemble-perth 1.0.1 is
    # missing perth_implicit on this stack, so patch the watermarker first, the
    # same way the audition harness does. Nothing here touches CUDA.
    import perth

    class _NoWatermark:
        def apply_watermark(self, wav, sample_rate=None):
            return wav

    perth.PerthImplicitWatermarker = _NoWatermark
    nw = _load(APP / "narrate_worker.py", "nw_gap")

    blocks = json.loads((job / "blocks.json").read_text(encoding="utf-8"))
    if isinstance(blocks, dict):
        blocks = blocks["blocks"]

    def plan_for(gap_ms: int):
        prof = dict(nw.PAUSE_PROFILES["A"])
        prof["block_gap_ms"] = gap_ms
        return nw.build_plan(blocks, prof)

    base = plan_for(400)
    print(f"plan: {len(base):,} chunks")

    # segment durations, header only
    durs = np.zeros(len(base), dtype=np.float64)
    missing = []
    for i in range(len(base)):
        p = seg_dir / f"seg_{i:06d}.wav"
        if not p.is_file():
            missing.append(i)
            continue
        with wave.open(str(p), "rb") as w:
            durs[i] = w.getnframes() / w.getframerate()
    if missing:
        print(f"  WARNING: {len(missing)} segments missing "
              f"(first few: {missing[:5]})")

    # pick a contiguous run that is dialogue dense, i.e. many paragraph joins
    # per minute, so the dial under test is heard often.
    is_block_end = np.array([p["after_ms"] >= 400 for p in base])
    best = None
    for start in range(0, len(base) - 5):
        if any(m >= start for m in missing[:1]) and start in missing:
            continue
        total, end = 0.0, start
        while end < len(base) and total < args.target_seconds:
            total += durs[end] + base[end]["after_ms"] / 1000.0 \
                + base[end]["before_ms"] / 1000.0
            end += 1
        if total < args.target_seconds * 0.9:
            break
        if any(i in missing for i in range(start, end)):
            continue
        joins = int(is_block_end[start:end].sum())
        short = int((durs[start:end] < 2.0).sum())
        score = joins * 2 + short
        if best is None or score > best[0]:
            best = (score, start, end, total, joins)
    if args.start_chunk is not None:
        start = args.start_chunk
        if args.num_chunks:
            end = start + args.num_chunks
            total = sum(durs[i] + (base[i]["after_ms"] + base[i]["before_ms"]) / 1000.0
                        for i in range(start, end))
        else:
            total, end = 0.0, start
            while end < len(base) and total < args.target_seconds:
                total += durs[end] + base[end]["after_ms"] / 1000.0
                end += 1
        best = (0, start, end, total, int(is_block_end[start:end].sum()))
    _, start, end, approx, joins = best
    n_chunks = end - start
    print(f"excerpt: chunks [{start}..{end-1}] ({n_chunks} chunks), "
          f"{joins} paragraph joins, ~{approx:.0f}s at gap 400")
    print(f"  paragraph joins per minute: {joins/(approx/60):.1f}")

    with wave.open(str(seg_dir / f"seg_{start:06d}.wav"), "rb") as w:
        sr = w.getframerate()
    audio = {}
    for g in gaps:
        plan = plan_for(g)
        parts = []
        for i in range(start, end):
            e = plan[i]
            if e["before_ms"]:
                parts.append(np.zeros(int(sr * e["before_ms"] / 1000.0),
                                      dtype=np.float32))
            x, s = read_wav(seg_dir / f"seg_{i:06d}.wav")
            sr = s
            parts.append(x)
            if e["after_ms"]:
                parts.append(np.zeros(int(s * e["after_ms"] / 1000.0),
                                      dtype=np.float32))
        y = np.concatenate(parts)
        audio[g] = y
        print(f"  gap {g:>3} ms -> {len(y)/sr:7.2f} s "
              f"(audible paragraph pause about {g + 380} ms)")

    out.mkdir(parents=True, exist_ok=False)
    for g in gaps:
        write_wav(out / f"arm_gap{g}.wav", audio[g], sr)

    order = list(gaps)
    secrets.SystemRandom().shuffle(order)
    blind = out / "blind"
    blind.mkdir()
    entries = []
    for idx, g in enumerate(order, start=1):
        name = f"Gap_Blind_{idx:02d}.wav"
        write_wav(blind / name, audio[g], sr)
        h = hashlib.sha256((blind / name).read_bytes()).hexdigest()
        entries.append({"blind_file": name, "block_gap_ms": g,
                        "audible_paragraph_gap_ms": g + 380, "sha256": h})
    (out / "blind_mapping_private.json").write_text(json.dumps({
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "confidential_until_owner_listens": True,
        "job": str(job),
        "excerpt_chunks": [start, end - 1],
        "paragraph_joins": joins,
        "model_padding_ms": 380,
        "entries": entries,
    }, indent=2), encoding="utf-8")
    print(f"\nwrote {out}")
    print(f"  blind set: {', '.join(e['blind_file'] for e in entries)}")
    print("  mapping withheld until you rank them")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
