"""
A/B baseline (chatterbox env): generate the selected chunks with the v1
single-item path EXACTLY as narrate_worker does (model.generate per chunk
with audio_prompt_path=ref each time), saving WAVs + timing + the raw
float32 audio for later objective comparison against the batched path.

Usage: python ab_v1.py <ab_chunks.json> <ref_wav> <out_dir>
"""
import json
import sys
import time
from pathlib import Path

import numpy as np
import soundfile as sf

# Watermarker stub, identical to narrate_worker.py (resemble-perth on this
# stack lacks perth_implicit); must run before importing chatterbox.
import perth


class _NoWatermark:
    def apply_watermark(self, wav, sample_rate=None):
        return wav


perth.PerthImplicitWatermarker = _NoWatermark

import torch
from chatterbox.tts import ChatterboxTTS

FADE_MS = 30  # match narrate_worker


def apply_fade(wav, sr, fade_ms):
    fade_samples = int(sr * (fade_ms / 1000.0))
    fade_samples = min(fade_samples, len(wav) // 3)
    if fade_samples <= 0:
        return wav
    wav = wav.copy()
    wav[:fade_samples] *= np.linspace(0.0, 1.0, fade_samples, dtype=np.float32)
    wav[-fade_samples:] *= np.linspace(1.0, 0.0, fade_samples, dtype=np.float32)
    return wav


def main():
    chunks_json = Path(sys.argv[1])
    ref_wav = sys.argv[2]
    out_dir = Path(sys.argv[3])
    out_dir.mkdir(parents=True, exist_ok=True)

    data = json.loads(chunks_json.read_text(encoding="utf-8"))
    chunks = data["chunks"]

    print(f"Loading ChatterboxTTS on cuda ...", flush=True)
    t0 = time.time()
    model = ChatterboxTTS.from_pretrained(device="cuda")
    sr = model.sr
    print(f"model loaded in {time.time() - t0:.1f}s, sr={sr}", flush=True)

    # Warmup (exclude from timing): first CUDA kernels + graph compile are slow.
    print("warmup ...", flush=True)
    _ = model.generate("This is a warm up sentence for timing.", audio_prompt_path=ref_wav)
    torch.cuda.synchronize()

    results = []
    total_gen = 0.0
    for c in chunks:
        idx = c["index"]
        text = c["text"]
        torch.cuda.synchronize()
        t = time.time()
        wav = model.generate(text, audio_prompt_path=ref_wav)  # re-embeds ref each call, as v1 does
        torch.cuda.synchronize()
        dt = time.time() - t
        total_gen += dt
        wav_np = wav.squeeze().cpu().numpy().astype(np.float32)
        wav_np = apply_fade(wav_np, sr, FADE_MS)
        p = out_dir / f"seg_{idx:04d}.wav"
        sf.write(str(p), wav_np, sr, subtype="PCM_16")
        # also stash raw float32 (pre-fade would differ; save post-fade to match seg)
        np.save(str(out_dir / f"seg_{idx:04d}.npy"), wav_np)
        dur = len(wav_np) / sr
        results.append({
            "index": idx, "char_len": c["char_len"], "is_heading": c["is_heading"],
            "gen_sec": round(dt, 3), "audio_sec": round(dur, 3),
            "rtf": round(dt / dur, 3) if dur > 0 else None,
        })
        print(f"  [{idx:4d}] {dt:5.2f}s -> {dur:5.2f}s audio  (len {c['char_len']})", flush=True)

    n = len(results)
    summary = {
        "engine": "v1-single",
        "sr": sr,
        "num_chunks": n,
        "total_gen_sec": round(total_gen, 2),
        "chunks_per_min": round(n / (total_gen / 60.0), 2) if total_gen > 0 else None,
        "total_audio_sec": round(sum(r["audio_sec"] for r in results), 2),
        "results": results,
    }
    (out_dir / "metrics.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps({k: summary[k] for k in ("num_chunks", "total_gen_sec", "chunks_per_min", "total_audio_sec")}, indent=2))
    print(f"wrote {n} wavs + metrics -> {out_dir}")


if __name__ == "__main__":
    main()
