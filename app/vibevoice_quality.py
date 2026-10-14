"""Shared transcript coverage gate and the legacy isolated CPU checker."""

import argparse
import json
import re
import sys
from difflib import SequenceMatcher
from pathlib import Path

PARAKEET_WORKFLOW = "generate_first_parakeet_v1"
PARAKEET_MODEL_ID = "nvidia/parakeet-tdt-0.6b-v3"
PARAKEET_REVISION = "541d1f99c6b0c3cd0b11a95167540bb8edefd82b"


def parakeet_setup_error(python, model):
    if not python or not Path(python).is_file():
        return "Parakeet Python was not found. Run install/bootstrap_parakeet.py to configure its isolated runtime."
    folder = Path(model) if model else None
    names = ("config.json", "model.safetensors", "processor_config.json", "tokenizer.json", "tokenizer_config.json")
    if not folder or any(not (folder / name).is_file() for name in names):
        return "Parakeet model files are incomplete. Run install/bootstrap_parakeet.py before starting narration."
    try:
        if json.loads((folder / "config.json").read_text(encoding="utf-8")).get("architectures") != ["ParakeetForTDT"]:
            return "The configured checker is not the Parakeet TDT model. Re-run its setup."
    except (OSError, ValueError):
        return "The Parakeet model configuration is unreadable. Re-run its setup."
    return None


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
_SPELLING_VARIANTS = {
    frozenset(("acknowledgment", "acknowledgement")),
    frozenset(("acknowledgments", "acknowledgements")),
    frozenset(("favourite", "favorite")),
    frozenset(("favourites", "favorites")),
}
# Exact lexical variants, not phonetic/fuzzy matching: names and changed words
# must remain differences. Keep inflections explicit to avoid broad rewrites.
_SPELLING_VARIANTS.update(frozenset(pair.split("/")) for pair in (
    "adviser/advisor", "advisers/advisors", "behaviour/behavior", "behaviours/behaviors",
    "colour/color", "colours/colors", "coloured/colored", "colouring/coloring",
    "favour/favor", "favours/favors", "favoured/favored", "favouring/favoring",
    "favourable/favorable", "favourably/favorably", "honour/honor", "honours/honors",
    "honoured/honored", "honouring/honoring", "honourable/honorable",
    "humour/humor", "humours/humors", "labour/labor", "labours/labors",
    "laboured/labored", "labouring/laboring", "neighbour/neighbor", "neighbours/neighbors",
    "odour/odor", "odours/odors", "jeopardise/jeopardize", "jeopardised/jeopardized",
    "jeopardises/jeopardizes", "jeopardising/jeopardizing",
))
# These spellings cannot be distinguished by listening. Normalize only complete
# tokens for alignment; keep source text, identifiers and nonhomophones intact.
_HOMOPHONES = {
    word: group.split("/")[0]
    for group in (
        "be/bee", "see/sea", "hear/here", "know/no", "knew/new",
        "to/too/two", "for/four", "one/won", "there/their/they're",
        "your/you're", "its/it's", "right/write/rite", "night/knight",
        "son/sun", "wood/would", "wear/where", "wait/weight", "by/buy/bye",
        "whole/hole", "peace/piece", "plain/plane", "week/weak", "meet/meat",
    )
    for word in group.split("/")
}
# Unambiguous expansions only: forms such as "he's" and "I'd" have multiple
# meanings and must remain differences. This does not normalize missing words.
_CONTRACTIONS = {
    "i'm": ("i", "am"), "you're": ("you", "are"),
    "we're": ("we", "are"), "they're": ("they", "are"),
    "i've": ("i", "have"), "you've": ("you", "have"),
    "we've": ("we", "have"), "they've": ("they", "have"),
}
_ORDINALS = dict(zip(
    ("one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten",
     "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen", "seventeen",
     "eighteen", "nineteen", "twenty", "thirty", "forty", "fifty", "sixty", "seventy",
     "eighty", "ninety", "hundred", "thousand", "million", "billion", "trillion"),
    ("first", "second", "third", "fourth", "fifth", "sixth", "seventh", "eighth", "ninth", "tenth",
     "eleventh", "twelfth", "thirteenth", "fourteenth", "fifteenth", "sixteenth", "seventeenth",
     "eighteenth", "nineteenth", "twentieth", "thirtieth", "fortieth", "fiftieth", "sixtieth",
     "seventieth", "eightieth", "ninetieth", "hundredth", "thousandth", "millionth", "billionth", "trillionth")))
_ORDINAL_RE = re.compile(r"[1-9]\d{0,12}(?:st|nd|rd|th)")


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
    entries = []
    for match in WORD_RE.finditer(source):
        token = match.group()
        expanded = _integer_words(token)
        if _ORDINAL_RE.fullmatch(token) and _standalone((token, match.start(), match.end()), source):
            value = int(token[:-2])
            suffix = "th" if 10 <= value % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(value % 10, "th")
            before = source[match.start() - 1] if match.start() else ""
            compound = before == "-" and match.start() > 1 and source[match.start() - 2].isalpha()
            if token.endswith(suffix) and (not before or before not in "+-−./" or compound) and value <= 1_000_000_000_000:
                expanded = _integer_words(str(value))
                expanded[-1] = _ORDINALS[expanded[-1]]
        entries.extend((word, match.start(), match.end()) for word in expanded)
    return entries


def _spacing_equivalent(expected, heard, expected_source, heard_source):
    """Allow only a conservative one-word/two-word spacing difference."""
    if sorted((len(expected), len(heard))) != [1, 2]:
        return False
    joined, parts, source = ((expected[0], heard, heard_source) if len(expected) == 1
                             else (heard[0], expected, expected_source))
    joined, parts = joined[0], [part[0] for part in parts]
    # A terminal possessive must survive exactly ("worker's" != "workers").
    stems = [part.removesuffix("'s") for part in parts]
    explicit = (joined, tuple(parts)) in {("forever", ("for", "ever")), ("awhile", ("a", "while"))}
    if (not joined.removesuffix("'s").isalpha() or len(joined) < 3 or joined in _MEANING_CHANGING_COMPOUNDS
            or (not explicit and any(not part.isalpha() or len(part) < 3 or part in _COMPOUND_RISK_WORDS for part in stems))):
        return False
    separator = (source[expected[0][2]:expected[1][1]] if len(expected) == 2
                 else source[heard[0][2]:heard[1][1]])
    if not all(_standalone(entry, text) for entries, text in ((expected, expected_source), (heard, heard_source)) for entry in entries):
        return False
    return bool(separator and (separator.isspace() or separator in _COMPOUND_SEPARATORS)
                and joined == "".join(parts))


def _standalone(entry, source):
    start, end = entry[1:]
    before = source[start - 1] if start else ""
    after = source[end] if end < len(source) else ""
    return not any(character == "_" or character.isalnum() for character in (before, after))


def _comparison_word(entry, source):
    word = entry[0]
    return _HOMOPHONES.get(word, word) if _standalone(entry, source) else word


def _spelling_equivalent(expected, heard, expected_source, heard_source):
    return (len(expected) == len(heard) == 1
            and frozenset((expected[0][0], heard[0][0])) in _SPELLING_VARIANTS
            and _standalone(expected[0], expected_source) and _standalone(heard[0], heard_source))


def _orthographic_equivalent(expected, heard, expected_source, heard_source):
    """Recognize adjacent safe variants without excusing a mixed real change."""
    if _formatting_equivalent(expected, heard, expected_source, heard_source):
        return True
    left = right = 0
    while left < len(expected) and right < len(heard):
        for a, b in ((1, 1), (1, 2), (2, 1)):
            one, two = expected[left:left + a], heard[right:right + b]
            if len(one) != a or len(two) != b:
                continue
            if ((a == b == 1 and one[0][0] == two[0][0])
                    or _spelling_equivalent(one, two, expected_source, heard_source)
                    or _spacing_equivalent(one, two, expected_source, heard_source)):
                left, right = left + a, right + b
                break
        else:
            return False
    return left == len(expected) and right == len(heard)


def _formatting_equivalent(expected, heard, expected_source, heard_source):
    """Match bounded formatting variants and unambiguous contractions."""
    if not expected or not heard:
        return False
    pairs = ((expected, expected_source), (heard, heard_source))
    if not all(_standalone(("", entries[0][1], entries[-1][2]), source) for entries, source in pairs):
        return False
    for entries, source in pairs:
        start, end = entries[0][1], entries[-1][2]
        before = source[start - 1] if start else ""
        if before and before in ".:/\\+-−":
            return False
        if re.match(r"[./\\]\w", source[end:]):
            return False
    raw = [source[entries[0][1]:entries[-1][2]] for entries, source in pairs]
    compact = [re.sub(r"[.\s]", "", text) for text in raw]
    # Keep ordinary "ma", names and untested initialisms distinct.
    if (compact[0].upper() == compact[1].upper()
            and all(value in {"MA", "PhD", "PHD"} for value in compact)
            and any("." in text for text in raw)):
        return True
    for joined, parts, source, parts_source in (
        (expected, heard, expected_source, heard_source),
        (heard, expected, heard_source, expected_source),
    ):
        if len(joined) != 1 or len(parts) < 2:
            continue
        if (_CONTRACTIONS.get(joined[0][0]) == tuple(part[0] for part in parts)
                and len(parts) == 2
                and not parts_source[parts[0][2]:parts[1][1]].strip()):
            return True
        match = re.fullmatch(r"(pp?)([1-9]\d{0,12})", joined[0][0])
        if not match:
            continue
        tail = source[joined[0][2]:]
        if tail.startswith(("/", "-", "−")) or re.match(r"[.,]\d", tail):
            continue
        prefix, digits = match.groups()
        separator = parts_source[parts[0][2]:parts[1][1]]
        if (separator.strip() == "."
                and [part[0] for part in parts] == [prefix] + _integer_words(digits)):
            return True
    return False


def assess(expected, heard, major_words=5):
    expected_source = expected.lower().replace("’", "'")
    heard_source = heard.lower().replace("’", "'")
    expected_entries, heard_entries = _word_entries(expected_source), _word_entries(heard_source)
    expected_words = [entry[0] for entry in expected_entries]
    heard_words = [entry[0] for entry in heard_entries]
    differences, major = [], []
    expected_keys = [_comparison_word(entry, expected_source) for entry in expected_entries]
    heard_keys = [_comparison_word(entry, heard_source) for entry in heard_entries]
    for op, a, b, c, d in SequenceMatcher(None, expected_keys, heard_keys, autojunk=False).get_opcodes():
        if op == "equal":
            continue
        item = {"kind": op, "expected": expected_words[a:b], "heard": heard_words[c:d]}
        if op == "replace" and _orthographic_equivalent(expected_entries[a:b], heard_entries[c:d], expected, heard):
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


def assess_narration(expected, heard, major_words=5):
    try:
        from .vibevoice_delivery import spoken_text
    except ImportError:
        from vibevoice_delivery import spoken_text
    return assess(spoken_text(expected), heard, major_words)


def unit_assessment(unit, saved):
    """Use the same source-bound review in scheduling, reuse, and listening UI."""
    try:
        from .transcript_review import apply_review
    except ImportError:
        from transcript_review import apply_review
    expected = unit.get("spoken_text", unit["text"])
    raw = (numbered_heading_assessment(unit["text"], saved.get("transcript", ""))
           if unit.get("numbered_heading") else assess_narration(expected, saved.get("transcript", "")))
    # Heading numbers and exact titles retain their separate strict contract.
    return raw if unit.get("numbered_heading") else apply_review(expected, saved, raw)


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
    report = assess_narration(expected, heard, major_words)
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
