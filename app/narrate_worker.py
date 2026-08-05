"""
Narration worker for the Audiobook Studio app. Runs inside the
chatterbox conda env (python 3.11, torch 2.6.0+cu124) as a subprocess
of server.py. Never import this from the base-env server.

Usage: python narrate_worker.py <job_dir>

Reads  <job_dir>/blocks.json   {"blocks": [{"type","text"}, ...]}
       <job_dir>/config.json   pipeline path, pause profile, voice ref
Writes <job_dir>/segments/seg_NNNNNN.wav   one per chunk (resume unit)
       <job_dir>/plan_total.txt            chunk count, for server progress
       <job_dir>/output/<title>.<fmt>      single m4b (default), mp3, or wav

Modes: default runs one shard (index 0 of 1) and assembles. The server
drives parallelism by launching `--shard K --num-shards N` generation
processes (disjoint chunks by index % N) followed by one `--assemble`.
Worker count is sized to the GPU by the server.

Default output is a single .m4b with navigable chapters (each top-level
heading), encoded straight from the segments via ffmpeg with no giant
intermediate WAV. Format is set by config["format"] (m4b | mp3 | wav).

Chunk plan is derived deterministically from blocks.json, so a rerun
after an interruption rebuilds the same plan and skips finished
segments. Proven Chatterbox setup is reused from narrate_tagged.py:
watermarker stub, sentence-safe packing, quoted-ellipsis fix, fades.
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
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
from assembly_metadata import outline_chapter_marks
from narration_safety import repair_capped_sequences

CHAR_CEILING = 400
SENTENCE_SPLIT_RE = re.compile(r'(?<=[.!?])\s+(?=[A-Z"\'‘“])')
# Headings that name a top-level division become navigable chapters in
# the m4b/mp3. Sub-section headings (e.g. "REVIEW THE CHARACTERS") do
# not, so the chapter list stays a real table of contents.
CHAPTER_RE = re.compile(r"^(BOOK|CHAPTER|PART|CANTO|PROLOGUE|EPILOGUE|INTRODUCTION|PREFACE)\b", re.I)
AAC_BITRATE = "64k"  # mono 24 kHz narration; transparent for voice
# Batching controls for engine="batched". BATCH_SIZE is the hard cap on rows
# per batch. BATCH_TOKEN_BUDGET caps rows*Tmax so the KV-cache stays within
# VRAM (a fixed count OOM-thrashes/hangs once chunks get long). Calibrated on a
# 4090 (24 GB) with the LONGEST chunks (Tmax ~323, output ~750): N=3 -> 10 GB,
# N=4 -> 15 GB @ 18 chunks/min, N=5 -> 24 GB (thrash). Budget 1300 lands the
# longest chunks at N=4 (the sweet spot, ~9 GB headroom for model+desktop+
# runaway margin), medium chunks at ~N=8, short at the N=12 cap. On a smaller
# card, lower the budget (peak scales ~linearly with it). Overridable per job or
# via env (AUDIOBOOK_BATCH_SIZE / AUDIOBOOK_BATCH_TOKEN_BUDGET).
BATCH_SIZE = 12
BATCH_TOKEN_BUDGET = 1300
# Vocode a whole bucket in one S3Gen pass rather than row by row. The row-by-row
# loop was ~41% of whole-book time (measured, 472-bucket Odyssey run) and ~67% in
# a book's short-chunk head. Batching it measures 2.05x at N=12 tapering to ~1.0x
# by N=3, 1.42x on the stage, ~1.16x whole book. Audio quality is unchanged: it
# lands 1.006x against the model's OWN run-to-run variation (S3Gen is
# stochastic, so a rerun differs by the same amount). Set to False, or
# AUDIOBOOK_BATCH_S3GEN=0, to fall back to the row-by-row path.
BATCH_S3GEN = os.environ.get("AUDIOBOOK_BATCH_S3GEN", "1") not in ("0", "false", "False")

PAUSE_PROFILES = {
    # narrate_tagged.py validated values (Path B tagged material)
    "B": {"gap_ms": 50, "block_gap_ms": 100, "heading_before_ms": 200, "heading_after_ms": 150},
    # chunk_and_narrate.py validated values (Path A novel material).
    # block_gap_ms raised 400 -> 650 on 2026-08-04 after two blind listening
    # rounds on Power of the Dog. NOTE the nominal value is NOT the audible
    # pause: Chatterbox contributes a measured 380 ms of padding across every
    # join (180 leading + 200 trailing), so 650 sounds like ~1030 ms, which is
    # the commercial recording's p90. Round 1 (400/510/650) picked 650 from
    # below; round 2 (650/900/1200) picked it from above, with 900 called "too
    # long" and 1200 "way too long". gap_ms stays 150 because its audible
    # ~530 ms already matches the reference's 480 ms sentence pause.
    # Pauses are inserted at ASSEMBLY, so changing these needs no re-narration.
    "A": {"gap_ms": 150, "block_gap_ms": 650, "heading_before_ms": 200, "heading_after_ms": 150},
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
        provenance = {
            key: b[key]
            for key in ("source_page", "source_page_end")
            if key in b
        }
        last_block = i == n - 1
        if b["type"] == "heading":
            entry = {
                "text": text,
                "before_ms": profile["heading_before_ms"],
                "after_ms": profile["heading_after_ms"] + (0 if last_block else profile["block_gap_ms"]),
                "heading": text,
            }
            entry.update(provenance)
            plan.append(entry)
        else:
            subs = pack_text(text)
            for j, sc in enumerate(subs):
                after = profile["gap_ms"]
                if j == len(subs) - 1:
                    after = 0 if last_block else profile["block_gap_ms"]
                entry = {"text": sc, "before_ms": 0, "after_ms": after}
                entry.update(provenance)
                plan.append(entry)
    return plan


def _ffmeta_escape(s):
    for ch in ("\\", "=", ";", "#"):
        s = s.replace(ch, "\\" + ch)
    return s.replace("\n", " ")


def write_chapters_file(job_dir, chapters, total_ms, metadata=None):
    """ffmetadata file: global tags (title/artist/album/...) then one [CHAPTER]
    per entry, times in ms. ffmpeg copies the global tags via -map_metadata."""
    lines = [";FFMETADATA1"]
    for key, val in (metadata or {}).items():
        if val:
            lines.append(f"{key}={_ffmeta_escape(str(val))}")
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
    # Installer-fetched static build (install/bootstrap_ffmpeg.py), checked
    # before the chocolatey fallback since it's the path a fresh install
    # actually produces.
    bundled = Path(__file__).resolve().parent.parent / "tools" / "ffmpeg.exe"
    if bundled.exists():
        return str(bundled)
    fallback = r"C:\ProgramData\chocolatey\bin\ffmpeg.exe"
    if Path(fallback).exists():
        return fallback
    raise RuntimeError("ffmpeg not found on PATH; needed for m4b/mp3 output")


def encode_stream(fmt, pcm_iter, sr, out_path, ffmeta_path, logf, cover_path=None):
    """
    Pipe raw int16 PCM into ffmpeg and encode directly to m4b/mp3 with
    embedded chapters, global metadata, and (if given) cover art. No
    intermediate WAV is written to disk.
    """
    ff = find_ffmpeg()
    have_cover = bool(cover_path and Path(cover_path).exists())
    # Inputs: 0 = raw PCM (stdin), 1 = ffmetadata (chapters+tags), [2 = cover].
    inputs = [
        "-f", "s16le", "-ar", str(sr), "-ac", "1", "-i", "pipe:0",
        "-i", str(ffmeta_path),
    ]
    if have_cover:
        inputs += ["-i", str(cover_path)]
    maps = ["-map", "0:a", "-map_metadata", "1"]
    if have_cover:
        # Attach the image as cover art (m4b 'covr' atom / mp3 APIC frame).
        maps += ["-map", "2:v", "-c:v", "mjpeg", "-disposition:v:0", "attached_pic"]
        if fmt != "m4b":
            maps += ["-metadata:s:v", "title=Album cover", "-metadata:s:v", "comment=Cover (front)"]
    if fmt == "m4b":
        codec = ["-c:a", "aac", "-b:a", AAC_BITRATE, "-f", "mp4"]
    else:
        codec = ["-c:a", "libmp3lame", "-b:a", AAC_BITRATE, "-f", "mp3"]
        if have_cover:
            codec += ["-id3v2_version", "3"]
    cmd = [ff, "-y", "-loglevel", "warning", *inputs, *maps, *codec, str(out_path)]
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


def load_plan(job_dir):
    blocks = json.loads((job_dir / "blocks.json").read_text(encoding="utf-8"))["blocks"]
    config = json.loads((job_dir / "config.json").read_text(encoding="utf-8"))
    profile = PAUSE_PROFILES[config.get("path", "B")]
    plan = build_plan(blocks, profile)
    return plan, config, profile


def _write_segment(seg_dir, i, wav_np, sr, shard):
    """Atomic per-chunk segment write, identical for both engines. The temp
    name is unique per process so a fresh worker set and any orphaned workers
    from a prior run can never write the same temp path."""
    wav_np = apply_fade(wav_np.astype(np.float32), sr, FADE_MS)
    seg_path = seg_dir / f"seg_{i:06d}.wav"
    tmp = seg_path.with_suffix(f".tmp{shard}_{os.getpid()}.wav")
    sf.write(str(tmp), wav_np, sr, subtype="PCM_16")
    tmp.replace(seg_path)


def _generate_serial(model, plan, ref_wav, todo, seg_dir, sr, shard):
    """v1 engine: one model.generate per chunk (re-embeds the voice each call)."""
    done = 0
    for i in todo:
        wav = model.generate(plan[i]["text"], audio_prompt_path=ref_wav)
        _write_segment(seg_dir, i, wav.squeeze().cpu().numpy(), sr, shard)
        done += 1
        if done % 10 == 0:
            print(f"shard {shard}: {done} generated", flush=True)


def _make_buckets(toks_sorted, max_batch, token_budget):
    """Greedy VRAM-aware bucketing. The batched KV-cache scales with
    (rows x sequence_length), so a FIXED batch size blows past 24 GB once
    chunks get long (measured: 6 x 234-token chunks peaked at ~19 GB, and the
    longest chunks at batch 6 exceeded the card and thrashed into shared
    memory, i.e. hung). Instead we cap rows*Tmax by a token budget: many short
    chunks per bucket, few long ones. `toks_sorted` is ascending by token
    length, so the running max is just the newest chunk's length."""
    buckets, cur = [], []
    for item in toks_sorted:
        tl = int(item[1].numel())
        if cur and (len(cur) + 1 > max_batch or (len(cur) + 1) * tl > token_budget):
            buckets.append(cur)
            cur = []
        cur.append(item)          # a single chunk over budget still goes alone
    if cur:
        buckets.append(cur)
    return buckets


def _generate_batched(model, plan, ref_wav, todo, seg_dir, sr, shard, batch_size,
                      token_budget=BATCH_TOKEN_BUDGET, batch_s3gen=BATCH_S3GEN):
    """
    Batched engine: generate several chunks per T3 forward-pass batch.
    Verified numerically equivalent to the serial path per chunk (see
    batched_narrate.py and ab_selftest.py), so segments from either engine are
    interchangeable and resume still works across an engine switch.

    Chunks are sorted by token length, then bucketed by a VRAM budget
    (rows x Tmax <= token_budget, capped at batch_size rows) so batches pad
    little, finish at similar times, and never exceed the GPU's memory.
    """
    import batched_narrate as bn

    # The voice conditioning is identical for every chunk, so compute it ONCE
    # instead of re-embedding the reference per chunk as the serial path does.
    model.prepare_conditionals(ref_wav)
    conds = model.conds

    import time as _time
    import torch as _torch

    toks = [(i, bn.tokenize_chunk(model, plan[i]["text"]).cpu()) for i in todo]
    toks.sort(key=lambda it: it[1].numel())
    buckets = _make_buckets(toks, batch_size, token_budget)
    done = 0
    for bnum, bucket in enumerate(buckets):
        _tmax = max(int(t.numel()) for _, t in bucket)
        _t0 = _time.time()
        seqs = bn.batched_generate(model, [t for _, t in bucket], conds)
        _t3s = _time.time() - _t0
        original_tok_out = [len(s) for s in seqs]
        if any(n >= bn.MAX_NEW_TOKENS for n in original_tok_out):
            def _retry_one(row, _attempt):
                return bn.batched_generate(model, [bucket[row][1]], conds)[0]

            def _log_retry(row, attempt, token_count):
                chunk_index = bucket[row][0]
                print(
                    f"shard {shard}: chunk {chunk_index} hit the "
                    f"{token_count}-token decode cap; isolated retry "
                    f"{attempt}/3",
                    flush=True,
                )

            seqs = repair_capped_sequences(
                seqs,
                bn.MAX_NEW_TOKENS,
                _retry_one,
                max_attempts=3,
                on_retry=_log_retry,
            )
        _t0 = _time.time()
        wavs = (bn.seqs_to_wavs_batched if batch_s3gen else bn.seqs_to_wavs)(
            model, conds, seqs)
        _s3s = _time.time() - _t0
        # Per-bucket telemetry: without this a stall is invisible, since
        # segments are only written once a whole bucket finishes.
        print(f"shard {shard}: bucket {bnum+1}/{len(buckets)} N={len(bucket)} Tmax={_tmax} "
              f"t3={_t3s:.2f}s s3gen={_s3s:.2f}s "
              f"tok_out={original_tok_out} final_tok_out={[len(s) for s in seqs]} "
              f"reserved={_torch.cuda.memory_reserved()/1e9:.2f}GB", flush=True)
        for (i, _), wav in zip(bucket, wavs):
            if wav is None:
                # Degenerate empty token stream: fall back to the serial path
                # for just this chunk rather than emitting silence.
                print(f"shard {shard}: chunk {i} empty from batch, retrying serially", flush=True)
                wav = model.generate(plan[i]["text"], audio_prompt_path=ref_wav)
                wav = wav.squeeze().cpu().numpy()
            _write_segment(seg_dir, i, wav, sr, shard)
            done += 1
        print(f"shard {shard}: {done}/{len(toks)} generated", flush=True)


def run_generate(job_dir, plan, ref_wav, shard, nshards, engine="parallel",
                 batch_size=BATCH_SIZE, token_budget=BATCH_TOKEN_BUDGET,
                 batch_s3gen=BATCH_S3GEN):
    """
    Generate this shard's segments. Work is split by index modulo nshards,
    so N workers cover disjoint chunks with no coordination, and every
    worker still skips segments that already exist (resume-safe).

    engine="parallel" -> v1 one-at-a-time generation (the shipped default).
    engine="batched"  -> batched T3 inference; the server runs a single worker
                         for this engine because batching, not multiprocessing,
                         is what fills the GPU.
    """
    seg_dir = job_dir / "segments"
    seg_dir.mkdir(exist_ok=True)
    (job_dir / "plan_total.txt").write_text(str(len(plan)), encoding="utf-8")
    my_indices = [i for i in range(len(plan)) if i % nshards == shard]
    todo = [i for i in my_indices if not (seg_dir / f"seg_{i:06d}.wav").exists()]
    print(f"Shard {shard}/{nshards}: {len(my_indices)} of {len(plan)} chunks, "
          f"{len(todo)} to generate, engine={engine}")
    print("Loading Chatterbox model...")
    model = ChatterboxTTS.from_pretrained(device="cuda")
    sr = model.sr

    if engine == "batched":
        _generate_batched(model, plan, ref_wav, todo, seg_dir, sr, shard, batch_size,
                          token_budget, batch_s3gen)
    else:
        _generate_serial(model, plan, ref_wav, todo, seg_dir, sr, shard)

    print(f"shard {shard} finished: generated {len(todo)}, "
          f"{len(my_indices) - len(todo)} already present")


def run_assemble(job_dir, plan, config, profile):
    seg_dir = job_dir / "segments"
    out_dir = job_dir / "output"
    out_dir.mkdir(exist_ok=True)

    missing = [i for i in range(len(plan)) if not (seg_dir / f"seg_{i:06d}.wav").exists()]
    if missing:
        raise RuntimeError(f"cannot assemble: {len(missing)} segments missing (first: {missing[0]})")

    sr = sf.info(str(seg_dir / "seg_000000.wav")).samplerate
    fmt = config.get("format", "m4b").lower()
    if fmt not in ("m4b", "mp3", "wav"):
        fmt = "m4b"
    fallback_part_sec = config.get("fallback_part_minutes", 240) * 60
    safe_title = re.sub(r"[^\w \-]", "", config.get("title", "audiobook")).strip() or "audiobook"

    print(f"Assembling audiobook ({fmt})...")

    # Clear any prior assembly output so a re-run or format change never
    # leaves a stale file of another format next to the new one.
    for old in out_dir.glob("*"):
        if old.suffix.lower() in (".wav", ".m4b", ".mp3"):
            old.unlink()

    def gap(ms):
        return np.zeros(int(sr * ms / 1000.0), dtype=np.float32)

    def audio_stream():
        """Segments and inter-block silences in order, float32."""
        for i, entry in enumerate(plan):
            if entry["before_ms"]:
                yield gap(entry["before_ms"])
            seg, _ = sf.read(str(seg_dir / f"seg_{i:06d}.wav"), dtype="float32")
            yield seg
            if entry["after_ms"]:
                yield gap(entry["after_ms"])

    # One header-only pass: total length + chapter marks. sf.info does
    # not read audio data, so this is cheap even for thousands of chunks.
    total_samples = 0
    detected_chapters = []
    page_starts = []
    seen_pages = set()
    cursor = 0
    for i, entry in enumerate(plan):
        frames = sf.info(str(seg_dir / f"seg_{i:06d}.wav")).frames
        before = int(sr * entry["before_ms"] / 1000.0)
        after = int(sr * entry["after_ms"] / 1000.0)
        head = entry.get("heading")
        if head and CHAPTER_RE.match(head):
            detected_chapters.append((int(cursor / sr * 1000), head))
        source_page = entry.get("source_page")
        if source_page is not None and source_page not in seen_pages:
            page_starts.append((source_page, int(cursor / sr * 1000)))
            seen_pages.add(source_page)
        cursor += before + frames + after
    total_samples = cursor
    total_ms = int(total_samples / sr * 1000)
    outline_chapters = outline_chapter_marks(config.get("pdf_outline"), page_starts)
    chapters = (
        outline_chapters
        if len(outline_chapters) > len(detected_chapters)
        else detected_chapters
    )
    # If the book opens with lead-in before the first chapter heading,
    # give that region a chapter so navigation covers the whole file.
    if chapters and chapters[0][0] > 1500:
        chapters.insert(0, (0, "Opening"))
    print(f"{len(chapters)} chapters, {total_ms/3600000:.2f} hours total")

    if fmt in ("m4b", "mp3"):
        out_path = out_dir / f"{safe_title}.{fmt}"
        # Book metadata + cover art, prepared by the server from the PDF.
        metadata = config.get("metadata") or {}
        cover = config.get("cover_image")
        if cover and not Path(cover).exists():
            cover = None
        ffmeta = write_chapters_file(job_dir, chapters, total_ms, metadata)
        with open(job_dir / "log.txt", "a", encoding="utf-8") as logf:
            encode_stream(fmt, audio_stream(), sr, out_path, ffmeta, logf, cover_path=cover)
        tags = ", ".join(k for k, v in metadata.items() if v) or "none"
        print(f"wrote {out_path} ({fmt}, {len(chapters)} chapters, cover={'yes' if cover else 'no'}, tags: {tags})")
    else:
        # Lossless WAV master. Splits only if one file would top the
        # WAV format's ~4 GB ceiling (roughly a 22+ hour book).
        MAX_WAV_BYTES = int(3.9 * 1024 ** 3)
        if total_samples * 2 + 44 <= MAX_WAV_BYTES:
            out_path = out_dir / f"{safe_title}.wav"
            with sf.SoundFile(str(out_path), mode="w", samplerate=sr, channels=1, subtype="PCM_16") as out:
                for chunk in audio_stream():
                    out.write(chunk)
            print(f"wrote {out_path} ({total_ms/3600000:.2f} hours, single WAV)")
        else:
            print(f"WAV would exceed 4 GB; splitting into <= {fallback_part_sec/60:.0f} min parts")
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
            print(f"wrote {part_idx} WAV parts")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("job_dir")
    ap.add_argument("--shard", type=int, default=None, help="this worker's index, 0..num-shards-1")
    ap.add_argument("--num-shards", type=int, default=1)
    ap.add_argument("--assemble", action="store_true", help="assemble only, no model load")
    args = ap.parse_args()

    job_dir = Path(args.job_dir)
    plan, config, profile = load_plan(job_dir)

    if args.assemble:
        run_assemble(job_dir, plan, config, profile)
        print("Assembly complete.")
        return

    shard = args.shard if args.shard is not None else 0
    engine = config.get("engine", "parallel")
    batch_size = int(config.get("batch_size", BATCH_SIZE))
    token_budget = int(config.get("batch_token_budget", BATCH_TOKEN_BUDGET))
    batch_s3gen = bool(config.get("batch_s3gen", BATCH_S3GEN))
    run_generate(job_dir, plan, config["reference_wav"], shard, args.num_shards,
                 engine=engine, batch_size=batch_size, token_budget=token_budget,
                 batch_s3gen=batch_s3gen)

    # Manual single-worker convenience: `python narrate_worker.py <job>` with
    # no shard args generates everything and assembles in one pass. The server
    # always drives the split path (shards, then a separate --assemble).
    if args.shard is None and args.num_shards == 1:
        run_assemble(job_dir, plan, config, profile)
        print("Narration complete.")


if __name__ == "__main__":
    main()
