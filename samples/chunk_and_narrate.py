import re
import sys
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
# Includes curly quote variants (U+2018, U+201C) since novel text from path_a.py
# commonly has smart quotes, not straight ones.
SENTENCE_SPLIT_RE = re.compile(r'(?<=[.!?])\s+(?=[A-Z"\'\u2018\u201c])')


def split_sentences(paragraph: str):
    paragraph = paragraph.strip()
    if not paragraph:
        return []
    parts = SENTENCE_SPLIT_RE.split(paragraph)
    return [p.strip() for p in parts if p.strip()]


def pack_chunks(paragraphs, ceiling=CHAR_CEILING):
    """
    Returns a list of dicts: {text, end_of_paragraph}
    Packing never splits a sentence. A chunk only spans multiple
    sentences from the SAME paragraph, never across paragraphs,
    so paragraph pause cues stay correct.
    """
    chunks = []
    for para in paragraphs:
        sentences = split_sentences(para)
        if not sentences:
            continue
        current = ""
        for sent in sentences:
            candidate = (current + " " + sent).strip() if current else sent
            if len(candidate) <= ceiling:
                current = candidate
            else:
                if current:
                    chunks.append({"text": current, "end_of_paragraph": False})
                # handle a single sentence longer than ceiling on its own
                if len(sent) > ceiling:
                    # hard fallback: split long sentence on commas/semicolons, last resort on words
                    sub_parts = re.split(r'(?<=[,;])\s+', sent)
                    buf = ""
                    for sp in sub_parts:
                        cand2 = (buf + " " + sp).strip() if buf else sp
                        if len(cand2) <= ceiling:
                            buf = cand2
                        else:
                            if buf:
                                chunks.append({"text": buf, "end_of_paragraph": False})
                            buf = sp
                    if buf:
                        current = buf
                    else:
                        current = ""
                else:
                    current = sent
        if current:
            chunks.append({"text": current, "end_of_paragraph": True})
        elif chunks:
            chunks[-1]["end_of_paragraph"] = True
    return chunks


def apply_fade(wav: np.ndarray, sr: int, fade_ms: int) -> np.ndarray:
    """
    Applies a short linear fade in at the start and fade out at the end
    of a chunk's speech audio. This is what actually softens the boundary,
    since the silence gap itself is zeros and fading zeros has no effect.
    Fade length is clamped so it never exceeds a third of the clip, so a
    very short chunk cannot fade its entire content away.
    """
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


def load_paragraphs(txt_path: Path):
    raw = txt_path.read_text(encoding="utf-8")
    # paragraphs separated by blank lines, matching path_a.py output convention
    paras = re.split(r'\n\s*\n', raw)
    return [p.replace("\n", " ").strip() for p in paras if p.strip()]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("input_txt")
    ap.add_argument("reference_wav")
    ap.add_argument("output_wav")
    ap.add_argument("--ceiling", type=int, default=CHAR_CEILING)
    ap.add_argument("--gap-ms", type=int, default=150, help="silence between chunks within a paragraph")
    ap.add_argument("--para-gap-ms", type=int, default=400, help="silence at paragraph ends")
    ap.add_argument("--fade-ms", type=int, default=30, help="fade in/out applied to each chunk's speech audio at the boundary, softens the cut into and out of silence")
    ap.add_argument("--dry-run", action="store_true", help="print chunk plan only, do not load model or generate audio")
    args = ap.parse_args()

    txt_path = Path(args.input_txt)
    paragraphs = load_paragraphs(txt_path)
    chunks = pack_chunks(paragraphs, ceiling=args.ceiling)

    print(f"Loaded {len(paragraphs)} paragraphs, packed into {len(chunks)} chunks.")
    lengths = [len(c["text"]) for c in chunks]
    print(f"Chunk length min {min(lengths)} max {max(lengths)} avg {sum(lengths)//len(lengths)}")
    over = [c for c in chunks if len(c["text"]) > args.ceiling]
    if over:
        print(f"WARNING: {len(over)} chunks exceeded ceiling after fallback split, longest {max(len(c['text']) for c in over)}")

    if args.dry_run:
        for i, c in enumerate(chunks):
            tag = "PARA_END" if c["end_of_paragraph"] else "mid"
            print(f"[{i:03d}] ({len(c['text'])} chars, {tag}) {c['text'][:80]}...")
        return

    print("Loading Chatterbox model, this takes a moment...")
    model = ChatterboxTTS.from_pretrained(device="cuda")

    sr = model.sr
    gap_samples = int(sr * (args.gap_ms / 1000.0))
    para_gap_samples = int(sr * (args.para_gap_ms / 1000.0))
    silence_gap = np.zeros(gap_samples, dtype=np.float32)
    silence_para = np.zeros(para_gap_samples, dtype=np.float32)

    all_audio = []
    for i, c in enumerate(chunks):
        print(f"Generating chunk {i+1}/{len(chunks)} ({len(c['text'])} chars)...")
        wav = model.generate(c["text"], audio_prompt_path=args.reference_wav)
        wav_np = wav.squeeze().cpu().numpy().astype(np.float32)
        wav_np = apply_fade(wav_np, sr, args.fade_ms)
        all_audio.append(wav_np)
        if i < len(chunks) - 1:
            all_audio.append(silence_para if c["end_of_paragraph"] else silence_gap)

    final = np.concatenate(all_audio)
    sf.write(args.output_wav, final, sr)
    print(f"Wrote {args.output_wav}, {len(final)/sr:.1f} seconds total.")


if __name__ == "__main__":
    main()
