"""
Batched A/B run (chatterbox env): generate the selected chunks with the
batched engine (production sdpa kernel, length-bucketed), save WAVs + timing
+ raw audio, for comparison against the v1 baseline.

Usage: python ab_batched.py <ab_chunks.json> <ref_wav> <out_dir> [bucket_size]
"""
import json
import sys
import time
from pathlib import Path

import numpy as np
import soundfile as sf

import perth


class _NoWatermark:
    def apply_watermark(self, wav, sample_rate=None):
        return wav


perth.PerthImplicitWatermarker = _NoWatermark

import torch
from chatterbox.tts import ChatterboxTTS
import batched_narrate as B

FADE_MS = 30


def apply_fade(wav, sr, fade_ms):
    fs = int(sr * (fade_ms / 1000.0))
    fs = min(fs, len(wav) // 3)
    if fs <= 0:
        return wav
    wav = wav.copy()
    wav[:fs] *= np.linspace(0.0, 1.0, fs, dtype=np.float32)
    wav[-fs:] *= np.linspace(1.0, 0.0, fs, dtype=np.float32)
    return wav


def main():
    chunks_json = Path(sys.argv[1])
    ref_wav = sys.argv[2]
    out_dir = Path(sys.argv[3])
    bucket_size = int(sys.argv[4]) if len(sys.argv) > 4 else 8
    out_dir.mkdir(parents=True, exist_ok=True)

    data = json.loads(chunks_json.read_text(encoding="utf-8"))
    chunks = data["chunks"]

    print("loading model (sdpa, fp32) ...", flush=True)
    model = ChatterboxTTS.from_pretrained(device="cuda")
    sr = model.sr
    model.prepare_conditionals(ref_wav)
    conds = model.conds

    # tokenize all up front, sort by token length, bucket
    toks = [(c["index"], c["char_len"], B.tokenize_chunk(model, c["text"])) for c in chunks]
    toks.sort(key=lambda x: x[2].numel())
    buckets = [toks[i:i + bucket_size] for i in range(0, len(toks), bucket_size)]

    # warmup (excluded from timing)
    print("warmup ...", flush=True)
    _ = B.batched_generate(model, [toks[0][2], toks[-1][2]], conds)
    torch.cuda.synchronize()

    results = {}
    t3_total = 0.0
    s3_total = 0.0
    for bi, bucket in enumerate(buckets):
        idxs = [b[0] for b in bucket]
        tok_list = [b[2] for b in bucket]
        tmax = max(t.numel() for t in tok_list)
        torch.cuda.synchronize()
        t = time.time()
        seqs = B.batched_generate(model, tok_list, conds, cfg_weight=0.5, temperature=0.8,
                                  repetition_penalty=1.2, min_p=0.05, top_p=1.0)
        torch.cuda.synchronize()
        t3_dt = time.time() - t
        # Release the batched T3 KV-cache before vocoding: at large batch/long
        # sequences the reserved pool can approach the card limit and push
        # S3Gen's allocations onto PyTorch's slow cudaFree-and-retry path.
        torch.cuda.empty_cache()
        t = time.time()
        wavs = B.seqs_to_wavs(model, conds, seqs)
        torch.cuda.synchronize()
        s3_dt = time.time() - t
        t3_total += t3_dt
        s3_total += s3_dt
        for (idx, clen, tok), st, wav in zip(bucket, seqs, wavs):
            if wav is None:
                wav = np.zeros(int(sr * 0.2), dtype=np.float32)
            wav = apply_fade(wav.astype(np.float32), sr, FADE_MS)
            sf.write(str(out_dir / f"seg_{idx:04d}.wav"), wav, sr, subtype="PCM_16")
            np.save(str(out_dir / f"seg_{idx:04d}.npy"), wav)
            results[idx] = {"index": idx, "char_len": clen, "n_tok": len(st),
                            "audio_sec": round(len(wav) / sr, 3)}
        resv = torch.cuda.memory_reserved() / 1e9
        print(f"  bucket {bi}: N={len(bucket)} Tmax={tmax} t3={t3_dt:.2f}s s3gen={s3_dt:.2f}s "
              f"reserved={resv:.1f}GB idxs={idxs}", flush=True)

    n = len(results)
    total = t3_total + s3_total
    summary = {
        "engine": "batched", "sr": sr, "bucket_size": bucket_size, "num_chunks": n,
        "t3_sec": round(t3_total, 2), "s3gen_sec": round(s3_total, 2),
        "total_gen_sec": round(total, 2),
        "chunks_per_min": round(n / (total / 60.0), 2) if total > 0 else None,
        "total_audio_sec": round(sum(r["audio_sec"] for r in results.values()), 2),
        "results": [results[k] for k in sorted(results)],
    }
    (out_dir / "metrics.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps({k: summary[k] for k in
                      ("num_chunks", "t3_sec", "s3gen_sec", "total_gen_sec", "chunks_per_min", "total_audio_sec")},
                     indent=2))
    print(f"wrote {n} wavs + metrics -> {out_dir}")


if __name__ == "__main__":
    main()
