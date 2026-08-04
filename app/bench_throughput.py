"""Step 2 of the throughput benchmark: does the recovered-paragraph chunk
profile cost more or less wall clock than today's? Runs in the CHATTERBOX env
and uses the GPU.

METHOD, and the design choices matter more than the code:

  * The chunk lists come from the real narrate_worker.build_plan via
    bench_plan_dump.py. CLAUDE.md's rule: three earlier benchmarks were wrong
    because they tokenized raw blocks.json text, a completely different
    batching regime.
  * The hot loop is production's, not a reimplementation: tokenize_chunk ->
    .cpu() -> sort by token length -> narrate_worker._make_buckets with the
    REAL constants -> batched_generate -> seqs_to_wavs_batched. Nothing is
    handed an unbudgeted batch, which CLAUDE.md records as having filled the
    24 GB card once.
  * BUCKETS ARE SAMPLED, NOT CHUNKS. Buckets are formed from the FULL sorted
    chunk list, so a sampled bucket is byte-for-byte the work production would
    do. Sampling chunks instead would change bucket composition and silently
    measure a different machine.
  * Sampling is systematic across the ordered bucket list. Buckets are sorted
    short to long, so an even stride covers the whole length range, which is
    exactly the axis CLAUDE.md says the T3/S3Gen split swings on.
  * The two arms are INTERLEAVED bucket by bucket so any allocator or thermal
    drift hits both equally instead of whichever ran second.
  * Allocator stalls are real (CLAUDE.md: ~0.2% of buckets run 10-20x long,
    3.3% of the Odyssey's runtime, undiagnosed). With a few dozen samples one
    stall would wreck a mean, so both a mean-based and a median-based estimate
    are reported and outliers are named.

SANITY CHECK BUILT IN: the OLD arm is a book that has actually been narrated,
recorded at roughly 3.1 hours of batched-engine compute. If this method's old
estimate is nowhere near that, the extrapolation is wrong and the new estimate
should not be believed either.

Nothing is written to any job directory. Segment writes go to a temp dir that
is deleted.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import shutil
import statistics
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
APP = REPO / "app"
sys.path.insert(0, str(APP))

import numpy as np  # noqa: E402
import torch  # noqa: E402

# narrate_worker stubs the watermarker itself; import it the same way the
# worker process does so the constants and helpers are the real ones.
import perth  # noqa: E402


class _NoWatermark:
    def apply_watermark(self, wav, sample_rate=None):
        return wav


perth.PerthImplicitWatermarker = _NoWatermark

import batched_narrate as bn  # noqa: E402
import narrate_worker as nw  # noqa: E402
from chatterbox.tts import ChatterboxTTS  # noqa: E402


def _sample_indices(n: int, k: int) -> list[int]:
    """Systematic sample of k positions spread evenly over 0..n-1."""
    if k >= n:
        return list(range(n))
    return sorted({min(n - 1, int(round(i * n / float(k)))) for i in range(k)})


def _stratified_total(times: list[float], positions: list[int], n_buckets: int,
                      strata: int = 4) -> float:
    """Estimate the total over all buckets by averaging within position strata,
    which tolerates the strong length trend better than one global mean."""
    if not times:
        return 0.0
    total = 0.0
    edges = [int(round(s * n_buckets / float(strata))) for s in range(strata + 1)]
    for s in range(strata):
        lo, hi = edges[s], edges[s + 1]
        vals = [t for t, p in zip(times, positions) if lo <= p < hi]
        if not vals:
            vals = times
        total += statistics.fmean(vals) * (hi - lo)
    return total


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dump", required=True, help="output of bench_plan_dump.py")
    ap.add_argument("--reference", default=str(
        REPO / "samples" / "Voice_Sample" / "male_ref.wav"))
    ap.add_argument("--out", required=True, help="where to write the JSON report")
    ap.add_argument("--sample-buckets", type=int, default=40)
    ap.add_argument("--warmup-buckets", type=int, default=2)
    ap.add_argument("--batch-size", type=int, default=nw.BATCH_SIZE)
    ap.add_argument("--token-budget", type=int, default=nw.BATCH_TOKEN_BUDGET)
    ap.add_argument("--no-batch-s3gen", action="store_true",
                    help="use the row-by-row vocoder path instead of the default")
    ap.add_argument("--known-old-hours", type=float, default=3.1,
                    help="recorded batched-engine time for the OLD arm, for the "
                         "sanity check; pass 0 to skip")
    args = ap.parse_args()

    out = Path(args.out).resolve()
    if out.exists():
        raise FileExistsError(out)
    ref = Path(args.reference).resolve()
    if not ref.is_file():
        raise FileNotFoundError(ref)
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is not available in this environment")

    dump = json.loads(Path(args.dump).resolve().read_text(encoding="utf-8"))
    arm_names = ["old", "new"]

    print("loading Chatterbox...", flush=True)
    model = ChatterboxTTS.from_pretrained(device="cuda")
    model.prepare_conditionals(str(ref))
    conds = model.conds
    vocode = bn.seqs_to_wavs if args.no_batch_s3gen else bn.seqs_to_wavs_batched
    print(f"vocoder path: {'row-by-row' if args.no_batch_s3gen else 'batched'}",
          flush=True)

    # ---- tokenize and bucket exactly as the worker does ---------------------
    state = {}
    for arm in arm_names:
        texts = dump["arms"][arm]["texts"]
        t0 = time.time()
        toks = [(i, bn.tokenize_chunk(model, t).cpu()) for i, t in enumerate(texts)]
        tok_s = time.time() - t0
        toks.sort(key=lambda it: it[1].numel())
        buckets = nw._make_buckets(toks, args.batch_size, args.token_budget)
        tok_lens = sorted(int(t.numel()) for _, t in toks)
        state[arm] = {
            "chunks": len(texts),
            "tokenize_seconds": round(tok_s, 3),
            "buckets": buckets,
            "n_buckets": len(buckets),
            "median_tokens": tok_lens[len(tok_lens) // 2],
            "max_tokens": tok_lens[-1],
            "rows_hist": {},
        }
        for b in buckets:
            state[arm]["rows_hist"][len(b)] = state[arm]["rows_hist"].get(len(b), 0) + 1
        print(f"{arm}: {len(texts):,} chunks -> {len(buckets):,} buckets  "
              f"median {tok_lens[len(tok_lens)//2]} tok, max {tok_lens[-1]} tok  "
              f"tokenize {tok_s:.1f}s", flush=True)
        print(f"      rows per bucket: "
              f"{dict(sorted(state[arm]['rows_hist'].items()))}", flush=True)

    # ---- warmup, discarded --------------------------------------------------
    print(f"\nwarmup: {args.warmup_buckets} buckets per arm (discarded)", flush=True)
    for arm in arm_names:
        for b in state[arm]["buckets"][:args.warmup_buckets]:
            seqs = bn.batched_generate(model, [t for _, t in b], conds)
            vocode(model, conds, seqs)
    torch.cuda.synchronize()

    # ---- interleaved timed sampling ----------------------------------------
    for arm in arm_names:
        state[arm]["sample_pos"] = _sample_indices(
            state[arm]["n_buckets"], args.sample_buckets)
        state[arm]["rows"] = []
    depth = max(len(state[a]["sample_pos"]) for a in arm_names)
    seg_tmp = Path(tempfile.mkdtemp(prefix="bench_seg_"))
    print(f"\ntiming {depth} sampled buckets per arm, interleaved\n", flush=True)
    try:
        for k in range(depth):
            for arm in arm_names:
                pos_list = state[arm]["sample_pos"]
                if k >= len(pos_list):
                    continue
                pos = pos_list[k]
                bucket = state[arm]["buckets"][pos]
                tmax = max(int(t.numel()) for _, t in bucket)
                torch.cuda.synchronize()
                t0 = time.time()
                seqs = bn.batched_generate(model, [t for _, t in bucket], conds)
                torch.cuda.synchronize()
                t3_s = time.time() - t0
                t0 = time.time()
                wavs = vocode(model, conds, seqs)
                torch.cuda.synchronize()
                s3_s = time.time() - t0
                t0 = time.time()
                for (i, _), wav in zip(bucket, wavs):
                    if wav is not None:
                        nw._write_segment(seg_tmp, i, wav, model.sr, 0)
                write_s = time.time() - t0
                for p in seg_tmp.glob("*.wav"):
                    p.unlink()
                state[arm]["rows"].append({
                    "bucket_pos": pos,
                    "n": len(bucket),
                    "tmax": tmax,
                    "t3_s": round(t3_s, 4),
                    "s3gen_s": round(s3_s, 4),
                    "write_s": round(write_s, 4),
                    "total_s": round(t3_s + s3_s + write_s, 4),
                    "reserved_gb": round(torch.cuda.memory_reserved() / 1e9, 2),
                })
                print(f"  {arm:<4} bucket {pos:>5}/{state[arm]['n_buckets']:<5} "
                      f"N={len(bucket):<3} Tmax={tmax:<4} "
                      f"t3={t3_s:6.2f}s s3gen={s3_s:6.2f}s write={write_s:5.2f}s "
                      f"total={t3_s + s3_s + write_s:6.2f}s "
                      f"reserved={torch.cuda.memory_reserved()/1e9:.1f}GB",
                      flush=True)
    finally:
        shutil.rmtree(seg_tmp, ignore_errors=True)

    # ---- estimate -----------------------------------------------------------
    report = {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "dump": str(Path(args.dump).resolve()),
        "pdf_name": dump.get("pdf_name"),
        "gpu": torch.cuda.get_device_name(0),
        "torch": torch.__version__,
        "cuda": torch.version.cuda,
        "batch_size": args.batch_size,
        "token_budget": args.token_budget,
        "batch_s3gen": not args.no_batch_s3gen,
        "sample_buckets_requested": args.sample_buckets,
        "warmup_buckets": args.warmup_buckets,
        "arms": {},
    }
    print("\n" + "=" * 78)
    print("PER-ARM ESTIMATE")
    print("=" * 78)
    for arm in arm_names:
        rows = state[arm]["rows"]
        totals = [r["total_s"] for r in rows]
        pos = [r["bucket_pos"] for r in rows]
        n_b = state[arm]["n_buckets"]
        med = statistics.median(totals)
        outliers = [r for r in rows if r["total_s"] > 5 * med]
        clean = [t for t in totals if t <= 5 * med]
        clean_pos = [p for t, p in zip(totals, pos) if t <= 5 * med]
        est_mean = statistics.fmean(totals) * n_b
        est_strat = _stratified_total(totals, pos, n_b)
        est_clean = _stratified_total(clean, clean_pos, n_b)
        gen_only = (statistics.fmean([r["t3_s"] + r["s3gen_s"] for r in rows]) * n_b)
        t3_share = sum(r["t3_s"] for r in rows) / max(
            1e-9, sum(r["t3_s"] + r["s3gen_s"] for r in rows))
        a = {
            "chunks": state[arm]["chunks"],
            "n_buckets": n_b,
            "median_tokens": state[arm]["median_tokens"],
            "max_tokens": state[arm]["max_tokens"],
            "rows_hist": dict(sorted(state[arm]["rows_hist"].items())),
            "tokenize_seconds": state[arm]["tokenize_seconds"],
            "sampled_buckets": len(rows),
            "sampled_median_bucket_s": round(med, 4),
            "outlier_buckets": len(outliers),
            "t3_share_of_generation": round(t3_share, 4),
            "est_total_hours_mean": round((est_mean + state[arm]["tokenize_seconds"]) / 3600.0, 3),
            "est_total_hours_stratified": round((est_strat + state[arm]["tokenize_seconds"]) / 3600.0, 3),
            "est_total_hours_stratified_no_outliers": round((est_clean + state[arm]["tokenize_seconds"]) / 3600.0, 3),
            "est_generation_only_hours": round(gen_only / 3600.0, 3),
            "samples": rows,
        }
        report["arms"][arm] = a
        print(f"\n  {arm.upper()}  {a['chunks']:,} chunks in {n_b:,} buckets  "
              f"(median {a['median_tokens']} tok)")
        print(f"    sampled {a['sampled_buckets']} buckets, median bucket "
              f"{a['sampled_median_bucket_s']:.2f}s, outliers >5x median: "
              f"{a['outlier_buckets']}")
        print(f"    T3 share of generation: {t3_share:.1%}  "
              f"(S3Gen {1 - t3_share:.1%})")
        print(f"    tokenize {a['tokenize_seconds']:.0f}s")
        print(f"    ESTIMATED TOTAL: {a['est_total_hours_stratified']:.2f} h "
              f"(stratified)  |  {a['est_total_hours_mean']:.2f} h (flat mean)  |  "
              f"{a['est_total_hours_stratified_no_outliers']:.2f} h (outliers dropped)")

    o = report["arms"]["old"]
    n = report["arms"]["new"]
    print("\n" + "=" * 78)
    print("VERDICT")
    print("=" * 78)
    for key, label in (("est_total_hours_stratified", "stratified"),
                       ("est_total_hours_mean", "flat mean"),
                       ("est_total_hours_stratified_no_outliers", "outliers dropped")):
        ratio = n[key] / o[key] if o[key] else float("nan")
        print(f"  {label:<18} old {o[key]:.2f} h -> new {n[key]:.2f} h  "
              f"= {ratio:.2f}x  ({'SLOWER' if ratio > 1.02 else 'FASTER' if ratio < 0.98 else 'NEUTRAL'})")
    report["ratio_new_over_old_stratified"] = round(
        n["est_total_hours_stratified"] / o["est_total_hours_stratified"], 4)
    print(f"\n  chunk count {o['chunks']:,} -> {n['chunks']:,} "
          f"({n['chunks']/o['chunks']:.2f}x)   "
          f"buckets {o['n_buckets']:,} -> {n['n_buckets']:,} "
          f"({n['n_buckets']/o['n_buckets']:.2f}x)")

    if args.known_old_hours > 0:
        err = abs(o["est_total_hours_stratified"] - args.known_old_hours) / args.known_old_hours
        report["sanity_check"] = {
            "known_old_hours": args.known_old_hours,
            "estimated_old_hours": o["est_total_hours_stratified"],
            "relative_error": round(err, 4),
            "method_trustworthy": err <= 0.25,
        }
        print(f"\n  SANITY CHECK: old arm estimated {o['est_total_hours_stratified']:.2f} h "
              f"against {args.known_old_hours:.2f} h recorded, "
              f"error {err:.1%} -> "
              f"{'method looks sound' if err <= 0.25 else 'METHOD SUSPECT, do not trust the new estimate'}")

    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("x", encoding="utf-8", newline="\n") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    print(f"\nwrote report: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
