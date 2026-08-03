"""Generate a private dialogue A/B sample without changing production narration.

The input is a JSON array of logical delivery segments.  Each segment is
generated in one Chatterbox call so a single speaker is not split merely to
meet the production worker's character ceiling.  Text may be read from stdin
(`--input -`) so copyrighted test passages never need to be written to the
repository.

Example input:
[
  {"role": "character", "text": "...", "after_ms": 850},
  {"role": "narrator", "text": "...", "after_ms": 0}
]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import sys
from pathlib import Path

import numpy as np
import perth
import soundfile as sf
import torch


class _NoWatermark:
    """Compatibility shim required by the project's pinned perth package."""

    def apply_watermark(self, wav, sample_rate=None):
        return wav


perth.PerthImplicitWatermarker = _NoWatermark

from chatterbox.tts import ChatterboxTTS  # noqa: E402


FADE_MS = 30


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default="-", help="JSON file, or - for stdin")
    parser.add_argument("--reference", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--seed", type=int, default=20260729)
    parser.add_argument("--exaggeration", type=float, default=0.5)
    parser.add_argument("--cfg-weight", type=float, default=0.5)
    parser.add_argument("--temperature", type=float, default=0.8)
    return parser.parse_args()


def _read_segments(input_name: str) -> list[dict]:
    if input_name == "-":
        raw = json.load(sys.stdin)
    else:
        with Path(input_name).open("r", encoding="utf-8") as handle:
            raw = json.load(handle)
    if not isinstance(raw, list) or not raw:
        raise ValueError("input must be a non-empty JSON array")

    segments = []
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            raise ValueError(f"segment {index} must be an object")
        text = item.get("text")
        if not isinstance(text, str) or not text.strip():
            raise ValueError(f"segment {index} has no text")
        if any(0xD800 <= ord(char) <= 0xDFFF for char in text):
            raise ValueError(
                f"segment {index} contains an invalid Unicode surrogate; "
                "use a UTF-8 JSON file or encoding-safe punctuation"
            )
        after_ms = item.get("after_ms", 0)
        if not isinstance(after_ms, int) or not 0 <= after_ms <= 5000:
            raise ValueError(f"segment {index} has invalid after_ms")
        segments.append(
            {
                "role": str(item.get("role", "unspecified")),
                "text": text.strip(),
                "after_ms": after_ms,
            }
        )
    return segments


def _fade(wav: np.ndarray, sample_rate: int) -> np.ndarray:
    count = min(round(sample_rate * FADE_MS / 1000), len(wav) // 3)
    if count <= 0:
        return wav
    wav = wav.copy()
    wav[:count] *= np.linspace(0.0, 1.0, count, dtype=np.float32)
    wav[-count:] *= np.linspace(1.0, 0.0, count, dtype=np.float32)
    return wav


def main() -> int:
    args = _parse_args()
    segments = _read_segments(args.input)
    reference = Path(args.reference).resolve()
    output = Path(args.output).resolve()
    if not reference.is_file():
        raise FileNotFoundError(reference)

    random.seed(args.seed)
    np.random.seed(args.seed)
    torch.manual_seed(args.seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(args.seed)

    print("loading Chatterbox...", flush=True)
    model = ChatterboxTTS.from_pretrained(device="cuda")
    sample_rate = model.sr
    assembled = []
    report = {
        "engine": "chatterbox-tts",
        "mode": "logical-speaker-segments",
        "seed": args.seed,
        "reference_name": reference.name,
        "reference_sha256": hashlib.sha256(reference.read_bytes()).hexdigest(),
        "settings": {
            "exaggeration": args.exaggeration,
            "cfg_weight": args.cfg_weight,
            "temperature": args.temperature,
            "fade_ms": FADE_MS,
        },
        "segments": [],
    }

    for index, segment in enumerate(segments):
        print(
            f"generating segment {index + 1}/{len(segments)} "
            f"role={segment['role']} chars={len(segment['text'])}",
            flush=True,
        )
        generated = model.generate(
            segment["text"],
            audio_prompt_path=str(reference),
            exaggeration=args.exaggeration,
            cfg_weight=args.cfg_weight,
            temperature=args.temperature,
        )
        wav = generated.squeeze().detach().cpu().numpy().astype(np.float32)
        wav = _fade(wav, sample_rate)
        assembled.append(wav)
        if segment["after_ms"]:
            assembled.append(
                np.zeros(round(sample_rate * segment["after_ms"] / 1000), dtype=np.float32)
            )
        report["segments"].append(
            {
                "index": index,
                "role": segment["role"],
                "characters": len(segment["text"]),
                "text_sha256": hashlib.sha256(segment["text"].encode("utf-8")).hexdigest(),
                "speech_seconds": round(len(wav) / sample_rate, 3),
                "after_ms": segment["after_ms"],
            }
        )

    final = np.concatenate(assembled)
    peak = float(np.max(np.abs(final))) if len(final) else 0.0
    if peak > 0.99:
        final = final * (0.99 / peak)

    output.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(output), final, sample_rate, subtype="PCM_16")
    report["output"] = str(output)
    report["sample_rate"] = sample_rate
    report["total_seconds"] = round(len(final) / sample_rate, 3)
    report["peak_before_safety_scale"] = round(peak, 5)
    report_path = output.with_suffix(".json")
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {output}", flush=True)
    print(f"wrote {report_path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
