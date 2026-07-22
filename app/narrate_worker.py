"""
Narration worker for the Audiobook Studio app. Runs inside the
chatterbox conda env (python 3.11, torch 2.6.0+cu124) as a subprocess
of server.py. Never import this from the base-env server.

Usage: python narrate_worker.py <job_dir>

Reads  <job_dir>/blocks.json   {"blocks": [{"type","text"}, ...]}
       <job_dir>/config.json   pipeline path, pause profile, voice ref
Writes <job_dir>/segments/seg_NNNNNN.wav   one per chunk (resume unit)
       <job_dir>/narrate_progress.json     polled by the server
       <job_dir>/output/part_NN.wav        assembled parts

Chunk plan is derived deterministically from blocks.json, so a rerun
after an interruption rebuilds the same plan and skips finished
segments. Proven Chatterbox setup is reused from narrate_tagged.py:
watermarker stub, sentence-safe packing, quoted-ellipsis fix, fades.
"""

import json
import re
import sys
import time
from pathlib import Path

import numpy as np
import soundfile as sf

# Watermarker stub, required on this stack
import perth


class _NoWatermark:
    def apply_watermark(self, wav, sample_rate=None):
        return wav


perth.PerthImplicitWatermarker = _NoWatermark

from chatterbox.tts import ChatterboxTTS

CHAR_CEILING = 400
SENTENCE_SPLIT_RE = re.compile(r'(?<=[.!?])\s+(?=[A-Z"\'‘“])')

PAUSE_PROFILES = {
    # narrate_tagged.py validated values (Path B tagged material)
    "B": {"gap_ms": 50, "block_gap_ms": 100, "heading_before_ms": 200, "heading_after_ms": 150},
    # chunk_and_narrate.py validated values (Path A novel material)
    "A": {"gap_ms": 150, "block_gap_ms": 400, "heading_before_ms": 200, "heading_after_ms": 150},
}
FADE_MS = 30


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


def apply_fade(wav, sr, fade_ms):
    fade_samples = int(sr * (fade_ms / 1000.0))
    fade_samples = min(fade_samples, len(wav) // 3)
    if fade_samples <= 0:
        return wav
    wav = wav.copy()
    wav[:fade_samples] *= np.linspace(0.0, 1.0, fade_samples, dtype=np.float32)
    wav[-fade_samples:] *= np.linspace(1.0, 0.0, fade_samples, dtype=np.float32)
    return wav


def build_plan(blocks, profile):
    """
    Flat chunk plan: [{text, before_ms, after_ms}]. Deterministic given
    blocks + profile, which is what makes segment resume safe.
    """
    plan = []
    n = len(blocks)
    for i, b in enumerate(blocks):
        text = normalize_quoted_ellipsis(b["text"].strip())
        if not text:
            continue
        last_block = i == n - 1
        if b["type"] == "heading":
            plan.append(
                {
                    "text": text,
                    "before_ms": profile["heading_before_ms"],
                    "after_ms": profile["heading_after_ms"] + (0 if last_block else profile["block_gap_ms"]),
                }
            )
        else:
            subs = pack_text(text)
            for j, sc in enumerate(subs):
                after = profile["gap_ms"]
                if j == len(subs) - 1:
                    after = 0 if last_block else profile["block_gap_ms"]
                plan.append({"text": sc, "before_ms": 0, "after_ms": after})
    return plan


def write_progress(job_dir, done, total, started, msg=""):
    elapsed = time.time() - started
    rate = done / elapsed if elapsed > 0 and done > 0 else 0
    eta = (total - done) / rate if rate > 0 else None
    (job_dir / "narrate_progress.json").write_text(
        json.dumps(
            {
                "done": done,
                "total": total,
                "elapsed_sec": round(elapsed, 1),
                "eta_sec": round(eta, 1) if eta is not None else None,
                "message": msg,
                "updated_at": time.time(),
            }
        ),
        encoding="utf-8",
    )


def main():
    job_dir = Path(sys.argv[1])
    blocks = json.loads((job_dir / "blocks.json").read_text(encoding="utf-8"))["blocks"]
    config = json.loads((job_dir / "config.json").read_text(encoding="utf-8"))
    profile = PAUSE_PROFILES[config.get("path", "B")]
    ref_wav = config["reference_wav"]
    part_max_sec = config.get("part_max_minutes", 60) * 60

    seg_dir = job_dir / "segments"
    out_dir = job_dir / "output"
    seg_dir.mkdir(exist_ok=True)
    out_dir.mkdir(exist_ok=True)

    plan = build_plan(blocks, profile)
    total = len(plan)
    print(f"Plan: {total} chunks from {len(blocks)} blocks")
    started = time.time()

    # Segments are keyed by plan index, so a changed plan (re-tagged
    # blocks) invalidates every existing segment. Compare a fingerprint
    # and wipe stale segments rather than stitching mismatched audio.
    import hashlib

    fingerprint = hashlib.sha256(
        "\x00".join(e["text"] for e in plan).encode("utf-8")
    ).hexdigest()
    plan_file = job_dir / "plan_fingerprint.txt"
    if plan_file.exists() and plan_file.read_text(encoding="utf-8").strip() != fingerprint:
        stale = list(seg_dir.glob("seg_*.wav"))
        for f in stale:
            f.unlink()
        print(f"Plan changed: removed {len(stale)} stale segments")
    plan_file.write_text(fingerprint, encoding="utf-8")

    done_already = sum(1 for i in range(total) if (seg_dir / f"seg_{i:06d}.wav").exists())
    print(f"Resume check: {done_already}/{total} segments already exist")

    write_progress(job_dir, done_already, total, started, "loading model")
    print("Loading Chatterbox model...")
    model = ChatterboxTTS.from_pretrained(device="cuda")
    sr = model.sr

    done = 0
    for i, entry in enumerate(plan):
        seg_path = seg_dir / f"seg_{i:06d}.wav"
        if seg_path.exists():
            done += 1
            continue
        wav = model.generate(entry["text"], audio_prompt_path=ref_wav)
        wav_np = wav.squeeze().cpu().numpy().astype(np.float32)
        wav_np = apply_fade(wav_np, sr, FADE_MS)
        tmp = seg_path.with_suffix(".tmp.wav")
        sf.write(str(tmp), wav_np, sr, subtype="PCM_16")
        tmp.replace(seg_path)
        done += 1
        if done % 5 == 0 or done == total:
            write_progress(job_dir, done, total, started, "generating")
        print(f"chunk {done}/{total}")

    write_progress(job_dir, done, total, started, "assembling")
    print("Assembling parts...")

    part_idx = 1
    part_audio = []
    part_sec = 0.0

    def flush_part():
        nonlocal part_idx, part_audio, part_sec
        if not part_audio:
            return
        final = np.concatenate(part_audio)
        out_path = out_dir / f"part_{part_idx:02d}.wav"
        sf.write(str(out_path), final, sr, subtype="PCM_16")
        print(f"wrote {out_path} ({len(final)/sr:.1f} sec)")
        part_idx += 1
        part_audio = []
        part_sec = 0.0

    for i, entry in enumerate(plan):
        seg, seg_sr = sf.read(str(seg_dir / f"seg_{i:06d}.wav"), dtype="float32")
        if entry["before_ms"]:
            part_audio.append(np.zeros(int(sr * entry["before_ms"] / 1000.0), dtype=np.float32))
        part_audio.append(seg)
        if entry["after_ms"]:
            part_audio.append(np.zeros(int(sr * entry["after_ms"] / 1000.0), dtype=np.float32))
        part_sec += len(seg) / sr + (entry["before_ms"] + entry["after_ms"]) / 1000.0
        block_end = entry["after_ms"] != profile["gap_ms"]
        if part_sec >= part_max_sec and block_end:
            flush_part()
    flush_part()

    write_progress(job_dir, total, total, started, "done")
    print("Narration complete.")


if __name__ == "__main__":
    main()
