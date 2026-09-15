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
_COMPOUND_RISK_WORDS = {"all", "and", "for", "here", "now", "the", "then", "this", "that", "with"}
_MEANING_CHANGING_COMPOUNDS = {"manslaughter", "nowhere", "therapist"}
_COMPOUND_SEPARATORS = {"-", "‐", "‑"}
# https://www.merriam-webster.com/dictionary/acknowledgment
_ACKNOWLEDGMENT_SPELLING_VARIANTS = {
    frozenset(("acknowledgment", "acknowledgement")),
    frozenset(("acknowledgments", "acknowledgements")),
}


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


def integer_words(value):
    """Return canonical English words for a bounded positive heading number."""
    if not isinstance(value, int) or isinstance(value, bool) or not 1 <= value <= 999:
        raise ValueError("heading number must be between 1 and 999")
    return _integer_words(str(value))


def words(text):
    return [entry[0] for entry in _word_entries(text)]


def _word_entries(text):
    source = text.lower().replace("’", "'")
    return [(word, match.start(), match.end())
            for match in WORD_RE.finditer(source)
            for word in _integer_words(match.group())]


def _spacing_equivalent(expected, heard, expected_source, heard_source):
    """Allow only a conservative one-word/two-word spacing difference."""
    if sorted((len(expected), len(heard))) != [1, 2]:
        return False
    joined, parts, source = ((expected[0], heard, heard_source) if len(expected) == 1
                             else (heard[0], expected, expected_source))
    joined, parts = joined[0], [part[0] for part in parts]
    if (not joined.isalpha() or len(joined) < 3 or joined in _MEANING_CHANGING_COMPOUNDS
            or any(not part.isalpha() or len(part) < 3 or part in _COMPOUND_RISK_WORDS for part in parts)):
        return False
    separator = (source[expected[0][2]:expected[1][1]] if len(expected) == 2
                 else source[heard[0][2]:heard[1][1]])
    return bool(separator and (separator.isspace() or separator in _COMPOUND_SEPARATORS)
                and joined == "".join(parts))


def _standalone(entry, source):
    start, end = entry[1:]
    before = source[start - 1] if start else ""
    after = source[end] if end < len(source) else ""
    return not any(character == "_" or character.isalnum() for character in (before, after))


def _spelling_equivalent(expected, heard, expected_source, heard_source):
    return (len(expected) == len(heard) == 1
            and frozenset((expected[0][0], heard[0][0])) in _ACKNOWLEDGMENT_SPELLING_VARIANTS
            and _standalone(expected[0], expected_source) and _standalone(heard[0], heard_source))


def assess(expected, heard, major_words=5):
    expected_source = expected.lower().replace("’", "'")
    heard_source = heard.lower().replace("’", "'")
    expected_entries, heard_entries = _word_entries(expected_source), _word_entries(heard_source)
    expected_words = [entry[0] for entry in expected_entries]
    heard_words = [entry[0] for entry in heard_entries]
    differences, major = [], []
    for op, a, b, c, d in SequenceMatcher(None, expected_words, heard_words, autojunk=False).get_opcodes():
        if op == "equal":
            continue
        item = {"kind": op, "expected": expected_words[a:b], "heard": heard_words[c:d]}
        if op == "replace" and (_spacing_equivalent(expected_entries[a:b], heard_entries[c:d], expected_source, heard_source)
                                or _spelling_equivalent(expected_entries[a:b], heard_entries[c:d], expected_source, heard_source)):
            item["orthographic_equivalent"] = True
        differences.append(item)
        # A one-word spelling, number, or recognition difference is diagnostic,
        # not proof that VibeVoice inserted or lost a passage.
        if not item.get("orthographic_equivalent") and max(b - a, d - c) >= major_words:
            major.append(item)
    counted = [item for item in differences if not item.get("orthographic_equivalent")]
    missing = sum(len(item["expected"]) for item in counted if item["kind"] in {"delete", "replace"})
    inserted = sum(len(item["heard"]) for item in counted if item["kind"] in {"insert", "replace"})
    aggregate_major = missing >= major_words or inserted >= major_words
    return {"expected_words": len(expected_words), "heard_words": len(heard_words), "differences": differences, "major": major, "missing_words": missing, "inserted_words": inserted, "ok": not major and not aggregate_major}


_NUMBERED_HEADING_RE = re.compile(r"^(0*[1-9]\d{0,2}):\s+(.+)$")


def numbered_heading_assessment(expected, heard):
    """Require a numbered heading's number and title, while retaining raw diagnostics."""
    raw = assess(expected, heard)
    match = _NUMBERED_HEADING_RE.fullmatch(" ".join(str(expected).split()))
    if not match:
        return raw
    digits, title = match.group(1), match.group(2)
    number = int(digits)
    if number > 999:
        return raw
    number_forms = [[digits], integer_words(number)]
    if len(digits) > 1:
        number_forms.append([_ONES[int(digit)] for digit in digits])
    if digits.startswith("0"):
        number_forms.append(["zero"] * (len(digits) - len(str(number))) + integer_words(number))
    reports = [assess(" ".join(form + words(title)), heard, major_words=1) for form in number_forms]
    normalized_report = next((report for report in reports if report["ok"]),
                             min(reports, key=lambda report: (report["missing_words"], report["inserted_words"])))
    raw["normalized_heading_assessment"] = normalized_report
    raw["ok"] = normalized_report["ok"]
    return raw


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
