import re
import json
import argparse
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
SENTENCE_SPLIT_RE = re.compile(r'(?<=[.!?])\s+(?=[A-Z"\'\u2018\u201c])')


def split_sentences(paragraph: str):
    paragraph = paragraph.strip()
    if not paragraph:
        return []
    parts = SENTENCE_SPLIT_RE.split(paragraph)
    return [p.strip() for p in parts if p.strip()]


def pack_text(text: str, ceiling=CHAR_CEILING):
    """
    Same sentence-safe packer as chunk_and_narrate.py, applied to a single
    block's text (body, dialogue). Never splits a sentence.
    """
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
                sub_parts = re.split(r'(?<=[,;])\s+', sent)
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


def normalize_quoted_ellipsis(text: str) -> str:
    """
    Finds quoted spans (straight or curly quotes) and strips ellipsis
    (2+ dots) from inside them. Quote marks are kept, since they carry
    real meaning (a named term or quoted aside), only the ellipsis is
    removed. Ellipsis inside quotes was observed to cause a broken,
    stop-start cadence from Chatterbox (e.g. "Yes, and..." read as
    "Yes," [pause] "and" as if two separate fragments).
    """
    quote_pairs = [('"', '"'), ('\u201c', '\u201d'), ("'", "'"), ('\u2018', '\u2019')]
    result = text
    for open_q, close_q in quote_pairs:
        pattern = re.escape(open_q) + r'([^' + re.escape(open_q) + re.escape(close_q) + r']*?)' + re.escape(close_q)

        def replacer(m):
            inner = re.sub(r'\.{2,}', '', m.group(1)).rstrip()
            return open_q + inner + close_q

        result = re.sub(pattern, replacer, result)
    return result


def apply_fade(wav: np.ndarray, sr: int, fade_ms: int) -> np.ndarray:
    fade_samples = int(sr * (fade_ms / 1000.0))
    fade_samples = min(fade_samples, len(wav) // 3)
    if fade_samples <= 0:
        return wav
    wav = wav.copy()
    fade_in = np.linspace(0.0, 1.0, fade_samples, dtype=np.float32)
    fade_out = np.linspace(1.0, 0.0, fade_samples, dtype=np.float32)
    wav[:fade_samples] *= fade_in
    wav[-fade_samples:] *= fade_out
    return wav


def make_silence(sr: int, ms: int) -> np.ndarray:
    return np.zeros(int(sr * (ms / 1000.0)), dtype=np.float32)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("input_json", help="path to a .tagged.json file from stage_two.py")
    ap.add_argument("reference_wav")
    ap.add_argument("output_wav")
    ap.add_argument("--ceiling", type=int, default=CHAR_CEILING)
    ap.add_argument("--gap-ms", type=int, default=50, help="silence between chunks within a block")
    ap.add_argument("--block-gap-ms", type=int, default=100, help="silence between blocks")
    ap.add_argument("--heading-pause-before-ms", type=int, default=200)
    ap.add_argument("--heading-pause-after-ms", type=int, default=150)
    ap.add_argument("--fade-ms", type=int, default=30)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    data = json.loads(Path(args.input_json).read_text(encoding="utf-8"))
    blocks = data["blocks"]

    print(f"Loaded {len(blocks)} blocks from {args.input_json}")
    type_counts = {}
    for b in blocks:
        type_counts[b["type"]] = type_counts.get(b["type"], 0) + 1
    print("Block types:", type_counts)

    if args.dry_run:
        for i, b in enumerate(blocks):
            preview = b["text"][:70]
            print(f"[{i:03d}] {b['type']:12s} {preview}")
        return

    print("Loading Chatterbox model, this takes a moment...")
    model = ChatterboxTTS.from_pretrained(device="cuda")
    sr = model.sr

    def generate_chunk(text):
        wav = model.generate(text, audio_prompt_path=args.reference_wav)
        wav_np = wav.squeeze().cpu().numpy().astype(np.float32)
        return apply_fade(wav_np, sr, args.fade_ms)

    all_audio = []
    gap = make_silence(sr, args.gap_ms)
    block_gap = make_silence(sr, args.block_gap_ms)
    heading_before = make_silence(sr, args.heading_pause_before_ms)
    heading_after = make_silence(sr, args.heading_pause_after_ms)

    for i, b in enumerate(blocks):
        btype = b["type"]
        text = normalize_quoted_ellipsis(b["text"].strip())
        if not text:
            continue

        print(f"Block {i+1}/{len(blocks)} ({btype})...")

        if btype == "heading":
            all_audio.append(heading_before)
            wav_np = generate_chunk(text)
            all_audio.append(wav_np)
            all_audio.append(heading_after)
        else:
            # body, dialogue, table, omitted_data: table/omitted_data text
            # is already a short spoken marker, pack_text handles any length safely
            sub_chunks = pack_text(text, ceiling=args.ceiling)
            for j, sc in enumerate(sub_chunks):
                all_audio.append(generate_chunk(sc))
                if j < len(sub_chunks) - 1:
                    all_audio.append(gap)

        if i < len(blocks) - 1:
            all_audio.append(block_gap)

    final = np.concatenate(all_audio)
    sf.write(args.output_wav, final, sr)
    print(f"Wrote {args.output_wav}, {len(final)/sr:.1f} seconds total.")


if __name__ == "__main__":
    main()
