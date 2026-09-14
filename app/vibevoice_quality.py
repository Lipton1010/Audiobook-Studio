"""CPU-only VibeVoice transcript coverage gate, run in its isolated environment."""

import argparse
import json
import re
import sys
from difflib import SequenceMatcher
from pathlib import Path


WORD_RE = re.compile(r"(?<![a-z0-9])[+\-−]?(?:\d+(?:[.,/]\d+)*|\.\d+(?:[.,/]\d+)*)(?![a-z0-9])|[a-z0-9]+(?:'[a-z0-9]+)?")
_INTEGER_RE = re.compile(r"(?:0|[1-9]\d{0,12}|[1-9]\d{0,2}(?:,\d{3})+)")
_ONES = ("zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine")
_TEENS = ("ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen", "nineteen")
_TENS = ("", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety")
_SCALES = ("", "thousand", "million", "billion", "trillion")


def _under_thousand(value):
    result = []
    if value >= 100:
        result.extend((_ONES[value // 100], "hundred"))
        value %= 100
    if value >= 20:
        result.append(_TENS[value // 10])
        value %= 10
    if 10 <= value < 20:
        result.append(_TEENS[value - 10])
    elif value:
        result.append(_ONES[value])
    return result


def _integer_words(token):
    if not _INTEGER_RE.fullmatch(token):
        return [token]
    value = int(token.replace(",", ""))
    if value > 1_000_000_000_000:
        return [token]
    if value == 0:
        return ["zero"]
    groups = []
    scale = 0
    while value:
        value, group = divmod(value, 1000)
        if group:
            groups.append(_under_thousand(group) + ([_SCALES[scale]] if scale else []))
        scale += 1
    return [word for group in reversed(groups) for word in group]


def words(text):
    tokens = WORD_RE.findall(text.lower().replace("’", "'"))
    return [word for token in tokens for word in _integer_words(token)]


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


def load_model(model_name):
    from faster_whisper import WhisperModel
    return WhisperModel(model_name, device="cpu", compute_type="int8")


def transcribe_with_model(audio, model):
    segments, _ = model.transcribe(str(audio), beam_size=5, vad_filter=True)
    return " ".join(segment.text.strip() for segment in segments)


def transcribe(audio, model_name):
    return transcribe_with_model(audio, load_model(model_name))


def _report(audio, expected, model, major_words):
    heard = transcribe_with_model(audio, model)
    report = assess(expected, heard, major_words)
    report["transcript"] = heard
    return report


def serve(model_name):
    model = load_model(model_name)
    print(json.dumps({"ready": True}), flush=True)
    for line in sys.stdin:
        try:
            request = json.loads(line)
            report = _report(Path(request["audio"]), request["expected"], model, int(request["major_words"]))
            path = Path(request["report"])
            path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            response = {"ok": report["ok"], "report": str(path)}
        except Exception as exc:
            response = {"error": str(exc)}
        print(json.dumps(response), flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--audio")
    parser.add_argument("--expected")
    parser.add_argument("--model", required=True)
    parser.add_argument("--report")
    parser.add_argument("--major-words", type=int, default=5)
    parser.add_argument("--serve", action="store_true")
    args = parser.parse_args()
    if args.serve:
        serve(args.model)
        return 0
    if not args.audio or args.expected is None or not args.report:
        parser.error("--audio, --expected, and --report are required without --serve")
    report = _report(Path(args.audio), args.expected, load_model(args.model), args.major_words)
    Path(args.report).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if report["ok"] else 3


if __name__ == "__main__":
    raise SystemExit(main())
