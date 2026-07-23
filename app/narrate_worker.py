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
import shutil
import subprocess
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
# Headings that name a top-level division become navigable chapters in
# the m4b/mp3. Sub-section headings (e.g. "REVIEW THE CHARACTERS") do
# not, so the chapter list stays a real table of contents.
CHAPTER_RE = re.compile(r"^(BOOK|CHAPTER|PART|CANTO|PROLOGUE|EPILOGUE|INTRODUCTION|PREFACE)\b", re.I)
AAC_BITRATE = "64k"  # mono 24 kHz narration; transparent for voice

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
                    "heading": text,
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


def _ffmeta_escape(s):
    for ch in ("\\", "=", ";", "#"):
        s = s.replace(ch, "\\" + ch)
    return s.replace("\n", " ")


def write_chapters_file(job_dir, chapters, total_ms):
    """ffmetadata file: one [CHAPTER] per entry, times in ms."""
    lines = [";FFMETADATA1"]
    for idx, (start_ms, title) in enumerate(chapters):
        end_ms = chapters[idx + 1][0] if idx + 1 < len(chapters) else total_ms
        if end_ms <= start_ms:
            end_ms = start_ms + 1000
        lines += ["[CHAPTER]", "TIMEBASE=1/1000",
                  f"START={start_ms}", f"END={end_ms}", f"title={_ffmeta_escape(title)}"]
    p = job_dir / "chapters.ffmeta"
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return p


def find_ffmpeg():
    ff = shutil.which("ffmpeg")
    if ff:
        return ff
    fallback = r"C:\ProgramData\chocolatey\bin\ffmpeg.exe"
    if Path(fallback).exists():
        return fallback
    raise RuntimeError("ffmpeg not found on PATH; needed for m4b/mp3 output")


def encode_stream(fmt, pcm_iter, sr, out_path, ffmeta_path, logf):
    """
    Pipe raw int16 PCM into ffmpeg and encode directly to m4b/mp3 with
    embedded chapters. No intermediate WAV is written to disk.
    """
    ff = find_ffmpeg()
    if fmt == "m4b":
        codec = ["-c:a", "aac", "-b:a", AAC_BITRATE, "-f", "mp4"]
    else:
        codec = ["-c:a", "libmp3lame", "-b:a", AAC_BITRATE, "-f", "mp3"]
    cmd = [
        ff, "-y", "-loglevel", "warning",
        "-f", "s16le", "-ar", str(sr), "-ac", "1", "-i", "pipe:0",
        "-i", str(ffmeta_path), "-map", "0:a", "-map_metadata", "1",
        *codec, str(out_path),
    ]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=logf, stderr=logf)
    try:
        for chunk in pcm_iter:
            pcm = np.clip(chunk, -1.0, 1.0)
            proc.stdin.write((pcm * 32767).astype("<i2").tobytes())
        proc.stdin.close()
    except BrokenPipeError:
        proc.wait()
        raise RuntimeError("ffmpeg closed the pipe early; see log")
    rc = proc.wait()
    if rc != 0:
        raise RuntimeError(f"ffmpeg exited {rc}; see log")


def main():
    job_dir = Path(sys.argv[1])
    blocks = json.loads((job_dir / "blocks.json").read_text(encoding="utf-8"))["blocks"]
    config = json.loads((job_dir / "config.json").read_text(encoding="utf-8"))
    profile = PAUSE_PROFILES[config.get("path", "B")]
    ref_wav = config["reference_wav"]
    fmt = config.get("format", "m4b").lower()
    if fmt not in ("m4b", "mp3", "wav"):
        fmt = "m4b"
    fallback_part_sec = config.get("fallback_part_minutes", 240) * 60
    safe_title = re.sub(r"[^\w \-]", "", config.get("title", "audiobook")).strip() or "audiobook"

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
    print("Assembling audiobook...")

    # Clear any prior assembly output so a re-run never leaves stale
    # part files next to a freshly written single file.
    for old in out_dir.glob("*.wav"):
        old.unlink()

    def gap(ms):
        return np.zeros(int(sr * ms / 1000.0), dtype=np.float32)

    # A single mono PCM_16 WAV is capped near 4 GB by the format's
    # 32-bit size field. Project the size and only split into parts if
    # one file would exceed that (roughly a 22+ hour book).
    MAX_WAV_BYTES = int(3.9 * 1024 ** 3)
    total_samples = 0
    for i, entry in enumerate(plan):
        total_samples += sf.info(str(seg_dir / f"seg_{i:06d}.wav")).frames
        total_samples += int(sr * (entry["before_ms"] + entry["after_ms"]) / 1000.0)
    projected_bytes = total_samples * 2 + 44
    single_file = want_single and projected_bytes <= MAX_WAV_BYTES

    if single_file:
        out_path = out_dir / f"{safe_title}.wav"
        with sf.SoundFile(str(out_path), mode="w", samplerate=sr, channels=1, subtype="PCM_16") as out:
            for i, entry in enumerate(plan):
                if entry["before_ms"]:
                    out.write(gap(entry["before_ms"]))
                seg, _ = sf.read(str(seg_dir / f"seg_{i:06d}.wav"), dtype="float32")
                out.write(seg)
                if entry["after_ms"]:
                    out.write(gap(entry["after_ms"]))
        print(f"wrote {out_path} ({total_samples/sr/3600:.2f} hours, single file)")
    else:
        print(f"Projected {projected_bytes/1024**3:.1f} GB exceeds the WAV limit; "
              f"splitting into parts of up to {fallback_part_sec/60:.0f} min")
        part_idx = 1
        part_sec = 0.0
        writer = sf.SoundFile(str(out_dir / f"{safe_title} - part {part_idx:02d}.wav"),
                              mode="w", samplerate=sr, channels=1, subtype="PCM_16")
        for i, entry in enumerate(plan):
            if entry["before_ms"]:
                writer.write(gap(entry["before_ms"]))
            seg, _ = sf.read(str(seg_dir / f"seg_{i:06d}.wav"), dtype="float32")
            writer.write(seg)
            if entry["after_ms"]:
                writer.write(gap(entry["after_ms"]))
            part_sec += len(seg) / sr + (entry["before_ms"] + entry["after_ms"]) / 1000.0
            block_end = entry["after_ms"] != profile["gap_ms"]
            if part_sec >= fallback_part_sec and block_end:
                writer.close()
                part_idx += 1
                part_sec = 0.0
                writer = sf.SoundFile(str(out_dir / f"{safe_title} - part {part_idx:02d}.wav"),
                                      mode="w", samplerate=sr, channels=1, subtype="PCM_16")
        writer.close()
        print(f"wrote {part_idx} parts")

    write_progress(job_dir, total, total, started, "done")
    print("Narration complete.")


if __name__ == "__main__":
    main()
