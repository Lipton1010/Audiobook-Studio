"""CPU-only VibeVoice transcript coverage gate, run in its isolated environment."""

import argparse
import json
import re
from difflib import SequenceMatcher
from pathlib import Path


WORD_RE = re.compile(r"[a-z0-9]+(?:'[a-z0-9]+)?")


def words(text):
    return WORD_RE.findall(text.lower().replace("’", "'"))


def assess(expected, heard, major_words=5):
    expected_words, heard_words = words(expected), words(heard)
    differences, major = [], []
    for op, a, b, c, d in SequenceMatcher(None, expected_words, heard_words, autojunk=False).get_opcodes():
        if op == "equal":
            continue
        item = {"kind": op, "expected": expected_words[a:b], "heard": heard_words[c:d]}
        differences.append(item)
        # A one-word spelling, number, or recognition difference is diagnostic,
        # not proof that VibeVoice inserted or lost a passage.
        if max(b - a, d - c) >= major_words:
            major.append(item)
    missing = sum(len(item["expected"]) for item in differences if item["kind"] in {"delete", "replace"})
    inserted = sum(len(item["heard"]) for item in differences if item["kind"] in {"insert", "replace"})
    aggregate_major = missing >= major_words or inserted >= major_words
    return {"expected_words": len(expected_words), "heard_words": len(heard_words), "differences": differences, "major": major, "missing_words": missing, "inserted_words": inserted, "ok": not major and not aggregate_major}


def transcribe(audio, model_name):
    from faster_whisper import WhisperModel

    model = WhisperModel(model_name, device="cpu", compute_type="int8")
    segments, _ = model.transcribe(str(audio), beam_size=5, vad_filter=True)
    return " ".join(segment.text.strip() for segment in segments)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--audio", required=True)
    parser.add_argument("--expected", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--report", required=True)
    parser.add_argument("--major-words", type=int, default=5)
    args = parser.parse_args()
    heard = transcribe(Path(args.audio), args.model)
    report = assess(args.expected, heard, args.major_words)
    report["transcript"] = heard
    Path(args.report).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if report["ok"] else 3


if __name__ == "__main__":
    raise SystemExit(main())
