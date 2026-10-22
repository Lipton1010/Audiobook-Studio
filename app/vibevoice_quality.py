"""Shared transcript coverage gate and the legacy isolated CPU checker."""

import argparse
import hashlib
import json
import re
import sys
from difflib import SequenceMatcher
from pathlib import Path

PARAKEET_WORKFLOW = "generate_first_parakeet_v1"
PARAKEET_MODEL_ID = "nvidia/parakeet-tdt-0.6b-v3"
PARAKEET_REVISION = "541d1f99c6b0c3cd0b11a95167540bb8edefd82b"
COMPARISON_POLICY = "narration_v2_critical_review"


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
    "might've": ("might", "have"), "must've": ("must", "have"),
    "should've": ("should", "have"), "would've": ("would", "have"),
    "could've": ("could", "have"),
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
        item = {"kind": op, "expected": expected_words[a:b], "heard": heard_words[c:d],
                "expected_span": [a, b], "heard_span": [c, d]}
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


def _year_words(value):
    century, remainder = divmod(value, 100)
    if 2000 <= value < 2010:
        return ' '.join(_integer_words(str(value)))
    tail = ['hundred'] if remainder == 0 else (['oh'] if remainder < 10 else []) + _integer_words(str(remainder))
    return ' '.join(_integer_words(str(century)) + tail)


def _calendar_comparison(text):
    """Normalize explicit dates, clocks and years, retaining quantity wording."""
    try:
        from .vibevoice_delivery import calendar_clock_edits
    except ImportError:
        from vibevoice_delivery import calendar_clock_edits
    for edit in reversed(sorted(calendar_clock_edits(text), key=lambda edit: edit['start'])):
        text = text[:edit['start']] + edit['after'] + text[edit['end']:]
    months = r'January|February|March|April|May|June|July|August|September|October|November|December'
    context = re.compile(
        r'\b(?:in|during|since|until|by|from|between|after|before|year|of|around|born|died|circa|spring|summer|autumn|fall|winter|early|late)\s+(?:the\s+|at least\s+)?$'
        r'|\b(?:' + months + r')(?:\s+[a-z-]+(?:\s+[a-z-]+)?|\s+\d{1,2}(?:st|nd|rd|th)?)?,?\s+$', re.I)

    def replace(match):
        value, plural = int(match[1]), match[2]
        prefix, suffix = text[:match.start()], text[match.end():]
        timeline = (not prefix.strip() or re.search(r'[.!?]\s+$', prefix)) and re.match(r'\s*(?:[.,;:]|was\b)', suffix)
        if not plural and not timeline and not context.search(prefix):
            return match[0]
        century, remainder = divmod(value, 100)
        if plural:
            if remainder % 10 or not remainder:
                return match[0]
            decade = _TENS[remainder // 10][:-1] + 'ies'
            return ' '.join(_integer_words(str(century)) + [decade])
        return _year_words(value)

    text = re.sub(r'(?<![\w.,/+-])((?:18|19|20)\d{2})(s?)(?![\w.,]\d|[\w/])', replace, text)
    # Both twenty twelve and two thousand twelve are ordinary 21st-century years.
    # Convert only in the same explicit year contexts, never bare quantities.
    for value in (range(2010, 2100) if re.search(r'\btwo[\s-]+thousand\b', text, re.I) else ()):
        literal = ' '.join(_integer_words(str(value)))
        pattern = re.compile(r'\b' + literal.replace(' ', r'[\s-]+') + r'\b', re.I)
        for match in reversed(list(pattern.finditer(text))):
            if context.search(text[:match.start()]):
                text = text[:match.start()] + 'twenty ' + ' '.join(_integer_words(str(value % 100))) + text[match.end():]
    return text


def _notation_comparison(text):
    """Exact audible notation only; do not erase source markers or fuzzy names."""
    text = text.replace('’', "'")
    text = re.sub(r'(?<!\w)&(?!\w)', ' and ', text)
    text = re.sub(r'(?<=\d)%', ' percent', text)
    fractions = {'½': 'a half', '¼': 'a quarter', '¾': 'three quarters'}
    text = re.sub(r'(?<![\w./])([0-9]+)([½¼¾])(?!\w)',
                  lambda m: m[1] + ' and ' + fractions[m[2]], text)
    text = re.sub(r'(?<=\d)\s+([ap])\.m\.(?!\w)', lambda m: ' ' + m[1] + 'm', text, flags=re.I)
    text = re.sub(r'(?<![\w.])([ab])\.([dc])\.\s+(?=\d)',
                  lambda m: m[1] + m[2] + ' ', text, flags=re.I)
    text = re.sub(r"\b([a-z]+)'s\b", r'\1s', text, flags=re.I)
    return re.sub(r'\b(?:re-(?:enter(?:ed|ing)?|entry)|co-star(?:red|ring)?|e-mails?)\b',
                  lambda m: m[0].replace('-', ''), text, flags=re.I)


def assess_narration(expected, heard, major_words=5):
    try:
        from .vibevoice_delivery import spoken_text
    except ImportError:
        from vibevoice_delivery import spoken_text
    expected_hash = hashlib.sha256(expected.encode('utf-8')).hexdigest()
    expected = _calendar_comparison(_notation_comparison(spoken_text(expected)))
    comparison = _calendar_comparison(_notation_comparison(heard))
    # Digit-only ASR cannot reveal year pronunciation. When the source already
    # specifies that year's spoken form, align it without guessing at quantities.
    expected_tokens = ' ' + ' '.join(words(expected)) + ' '
    def source_year(match):
        year = _year_words(int(match[0]))
        cardinal = ' '.join(_integer_words(match[0]))
        return year if f' {year} ' in expected_tokens and f' {cardinal} ' not in expected_tokens else match[0]
    comparison = re.sub(r'(?<![\w.,/+-])(?:18|19|20)\d{2}(?![\w/]|[.,]\d)', source_year, comparison)
    report = assess(expected, comparison, major_words)
    # A cardinal reading of a historical year violates the narration contract,
    # even when its short difference fits the normal ASR word-error budget.
    wrong_style = []
    literal = ' '.join(m[0] for m in WORD_RE.finditer(heard.lower()))
    for difference in report['differences']:
        for century, cardinal in (('eighteen', 'one thousand eight hundred'),
                                  ('nineteen', 'one thousand nine hundred')):
            if (century in difference['expected'] and cardinal in ' '.join(difference['heard'])
                    and cardinal in literal):
                wrong_style.append({'expected':century, 'heard':cardinal})
    if wrong_style:
        report['year_style_mismatches'] = wrong_style
        report['ok'] = False
    if comparison != heard:
        report['comparison_transcript'] = comparison
    report['content_diagnostics'] = content_diagnostics(report)
    report['comparison_policy'] = COMPARISON_POLICY
    report['expected_spoken_sha256'] = expected_hash
    reasons = []
    critical = {'he', 'she', 'him', 'her', 'his', 'hers', 'they', 'them', 'their',
                'for', 'from', 'to', 'before', 'after', 'above', 'below', 'inside', 'outside'}
    for diagnostic in report['content_diagnostics']:
        reasons.extend(reason for reason in diagnostic['reasons']
                       if reason in {'negation differs', 'numeric wording differs'})
    for item in report['differences']:
        if item.get('orthographic_equivalent'):
            continue
        if (set(item['expected']) | set(item['heard'])) & critical:
            reasons.append('pronoun or direction differs')
        if item['kind'] in {'insert', 'delete'}:
            start, end = item['expected_span']
            if max(len(item['expected']), len(item['heard'])) >= 2 or start == 0 or end == report['expected_words']:
                reasons.append('phrase or boundary differs')
    report['review_required'] = bool(report['ok'] and reasons)
    report['review_reasons'] = sorted(set(reasons)) if report['review_required'] else []
    return report


def content_diagnostics(report):
    """Shadow-only semantic leads; ASR differences do not prove speech defects."""
    numeric = set(_ONES + _TEENS + _TENS + _SCALES) | set(_ORDINALS.values()) | {'hundred'}
    negation = {'no', 'not', 'never', 'neither', 'nor', 'nothing', 'nobody', 'without'}
    result = []
    for item in report['differences']:
        if item.get('orthographic_equivalent'):
            continue
        expected, heard = item['expected'], item['heard']
        reasons = []
        negative = lambda words: [word for word in words if word in negation or word.endswith("n't")]
        values = lambda words: [word for word in words if word in numeric or re.search(r'\d', word)]
        if negative(expected) != negative(heard):
            reasons.append('negation differs')
        if values(expected) != values(heard):
            reasons.append('numeric wording differs')
        if item['kind'] == 'delete':
            reasons.append('omission candidate')
        elif item['kind'] == 'insert':
            reasons.append('addition candidate')
        if reasons:
            result.append({'reasons': reasons, 'difference': item, 'authority': 'shadow_only'})
    return result


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
    if raw.get('review_required'):
        raw['ok'] = False
        return raw
    return raw if unit.get("numbered_heading") or raw.get('year_style_mismatches') else apply_review(expected, saved, raw)


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
