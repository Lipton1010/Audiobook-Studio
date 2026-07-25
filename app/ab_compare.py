"""
Compare two A/B output sets by speaker-embedding cosine similarity + audio
stats, per chunk (chatterbox env). Used first for v1-vs-v1b (natural sampling
noise floor), then for v1-vs-batched (the real quality test).

Usage: python ab_compare.py <ref_dir> <test_dir> <label>
Each dir holds seg_XXXX.npy (mono float32) written by ab_v1.py / ab_batched.py.
"""
import json
import sys
from pathlib import Path

import numpy as np

import perth


class _NoWatermark:
    def apply_watermark(self, wav, sample_rate=None):
        return wav


perth.PerthImplicitWatermarker = _NoWatermark

from chatterbox.tts import ChatterboxTTS
import ab_metrics as M


def main():
    ref_dir = Path(sys.argv[1])
    test_dir = Path(sys.argv[2])
    label = sys.argv[3]

    print("loading model (for VoiceEncoder) ...", flush=True)
    model = ChatterboxTTS.from_pretrained(device="cuda")
    ve = model.ve
    sr = model.sr

    ref_npys = sorted(ref_dir.glob("seg_*.npy"))
    rows = []
    for rp in ref_npys:
        idx = rp.stem
        tp = test_dir / (idx + ".npy")
        if not tp.exists():
            continue
        a = np.load(str(rp))
        b = np.load(str(tp))
        ea = M.speaker_embed(ve, a, sr)
        eb = M.speaker_embed(ve, b, sr)
        cos = M.cosine(ea, eb)
        sa = M.audio_stats(a, sr)
        sb = M.audio_stats(b, sr)
        rows.append({
            "index": idx, "cos": round(cos, 4),
            "ref_sec": sa["sec"], "test_sec": sb["sec"],
            "ref_rms": sa["rms"], "test_rms": sb["rms"],
        })

    cosines = [r["cos"] for r in rows]
    out = {
        "label": label,
        "ref_dir": str(ref_dir), "test_dir": str(test_dir),
        "n": len(rows),
        "cos_mean": round(float(np.mean(cosines)), 4) if cosines else None,
        "cos_min": round(float(np.min(cosines)), 4) if cosines else None,
        "cos_max": round(float(np.max(cosines)), 4) if cosines else None,
        "rows": rows,
    }
    (test_dir / f"compare_vs_{Path(ref_dir).name}.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"\n=== {label}: speaker-embedding cosine (ref={ref_dir.name} vs test={test_dir.name}) ===")
    print(f"{'idx':>9} {'cos':>7} {'ref_s':>6} {'test_s':>6}  dur_delta")
    for r in rows:
        dd = round(r["test_sec"] - r["ref_sec"], 2)
        print(f"{r['index']:>9} {r['cos']:>7.4f} {r['ref_sec']:>6.2f} {r['test_sec']:>6.2f}  {dd:+.2f}")
    print(f"\ncos mean={out['cos_mean']} min={out['cos_min']} max={out['cos_max']} (n={out['n']})")


if __name__ == "__main__":
    main()
