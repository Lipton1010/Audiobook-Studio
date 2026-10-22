"""Deterministic sub-passage planning for VibeVoice quality repair."""

import hashlib
import json
import re

try:
    from .vibevoice_plan import _split_oversize, normalize_text
    from .vibevoice_quality import assess_narration as assess, numbered_heading_assessment
except ImportError:  # Worker execution adds app/ directly to sys.path.
    from vibevoice_plan import _split_oversize, normalize_text
    from vibevoice_quality import assess_narration as assess, numbered_heading_assessment


UNIT_TARGET_WORDS = 120
UNIT_MAX_WORDS = 180
UNIT_SPLIT_REVISION = 1
_UNIT_INDEX_STRIDE = 10_000
_ABBREVIATIONS = {"dr.", "fig.", "i.e.", "jr.", "mr.", "mrs.", "ms.", "no.", "prof.", "sr.", "st.", "vs."}


def _sentence_parts(text, boundary_policy='initials_v2'):
    if boundary_policy not in ('legacy_v1', 'initials_v2', 'captions_v3', 'sentences_v4'):
        raise ValueError('Unknown unit boundary policy')
    start, parts = 0, []
    for index, character in enumerate(text):
        if character not in ".!?":
            continue
        before = text[start:index + 1]
        token = before.rsplit(None, 1)[-1].lower()
        if (any(text[max(start, index - 11):index + 1].lower().endswith(a) for a in _ABBREVIATIONS)
                if boundary_policy == 'legacy_v1' else token in _ABBREVIATIONS):
            continue
        end = index + 1
        closing = "\"'”’)]}" if boundary_policy in ('captions_v3', 'sentences_v4') else "\"'”’"
        if boundary_policy == 'sentences_v4':
            closing += '*†‡⁰¹²³⁴⁵⁶⁷⁸⁹'
        while end < len(text) and text[end] in closing:
            end += 1
        if end >= len(text) or not text[end].isspace():
            continue
        next_start = end
        while next_start < len(text) and text[next_start].isspace():
            next_start += 1
        # A capital initial followed by a name keeps its surname context.
        # Clock abbreviations are deliberately absent: p.m. can end a sentence.
        initial = re.search(r"(?:^|\s)([A-Z])\.$", before)
        if (boundary_policy != 'legacy_v1' and character == "." and initial
                and (initial[1] != "I" or re.search(r"[A-Z][a-z]+\s+I\.$|[A-Z]\.\s+I\.$", before))
                and re.match(r"[A-Z][a-z]+\b|[A-Z]\.", text[next_start:])):
            continue
        opening = "\"'“‘([{" if boundary_policy in ('captions_v3', 'sentences_v4') else "\"'“‘"
        if next_start < len(text) and (text[next_start].isupper() or text[next_start].isdigit() or text[next_start] in opening):
            parts.append(text[start:end])
            start = next_start
    parts.append(text[start:])
    return [part for part in parts if part]


def _identity(parent_identity, unit_index, text):
    payload = {"parent_identity": parent_identity, "split_revision": UNIT_SPLIT_REVISION, "unit_index": unit_index, "text": text}
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _bounded_sentence(text, max_words):
    parts = _split_oversize(text, max_words)
    names = list(re.finditer(r'\b(?:[A-Z][a-z]+\s+)?(?:[A-Z]\.\s+)+[A-Z][a-z]+\b|\b(?:Dr|Mr|Mrs|Ms|Prof)\.\s+[A-Z][a-z]+\b', text))
    ends, offset = [], 0
    for part in parts[:-1]:
        offset += len(part) + 1
        ends.append(offset)
    if not any(m.start() < end < m.end() for end in ends for m in names):
        return parts
    words = list(re.finditer(r'\S+', text))
    parts, start = [], 0
    while start < len(words):
        stop = min(start + max_words, len(words))
        while stop < len(words) and any(m.start() < words[stop].start() < m.end() for m in names):
            stop -= 1
            if stop <= start:
                raise ValueError('Name exceeds the unit word bound')
        parts.append(text[words[start].start():words[stop - 1].end()])
        start = stop
    return parts


def repair_limits(passage, config):
    """Use the saved backend budget in both rendering and listening review."""
    if config.get('backend') != 'drama3':
        return {}
    limits = dict(config.get('drama3_unit_limits', {'target_words': 55, 'max_words': 75}))
    limits.update(config.get('drama3_passage_unit_limits', {}).get(passage['identity'], {}))
    boundary = config.get('unit_boundary_policies', {}).get(passage['identity'], config.get('unit_boundary_policy'))
    list_max = config.get('drama3_list_max_words')
    if boundary != 'sentences_v4' and list_max and passage.get('text', '').count(';') >= 3:
        limits = {key: min(value, list_max) for key, value in limits.items()}
    if boundary == 'sentences_v4':
        try:
            from .drama3 import MAX_TEXT_CHARS
        except ImportError:
            from drama3 import MAX_TEXT_CHARS
        limits['max_chars'] = MAX_TEXT_CHARS
    return limits


def repair_units(passage, target_words=UNIT_TARGET_WORDS, max_words=UNIT_MAX_WORDS, boundary_policy='initials_v2', max_chars=None):
    """Split one parent passage into stable, independently verifiable units."""
    if not 1 <= target_words <= max_words:
        raise ValueError("target_words must be between 1 and max_words")
    parent_index = passage.get("index")
    if not isinstance(parent_index, int) or isinstance(parent_index, bool) or parent_index < 0:
        raise ValueError("passage index must be a non-negative integer")
    if parent_index > (2**63 - _UNIT_INDEX_STRIDE) // _UNIT_INDEX_STRIDE:
        raise ValueError("passage index cannot produce a safe unit index")
    parent_identity = passage.get("identity")
    if not parent_identity:
        raise ValueError("passage identity is required")
    source = normalize_text(passage.get("text", ""))
    if not source:
        raise ValueError("passage text is required")
    if passage.get("heading"):
        parts = [source]
    else:
        sentences = _sentence_parts(source, boundary_policy)
        pieces = []
        for sentence in sentences:
            if boundary_policy == 'sentences_v4':
                # Long enumerations may stop at an existing semicolon, never at
                # an arbitrary word. An oversized indivisible sentence stays whole.
                pieces.extend(re.split(r'(?<=;)\s+', sentence)
                              if max_chars and len(sentence) > max_chars else [sentence])
            else:
                splitter = _split_oversize if boundary_policy == 'legacy_v1' else _bounded_sentence
                pieces.extend(splitter(sentence, max_words) if len(sentence.split()) > max_words else [sentence])
        parts, current = [], []
        for piece in pieces:
            candidate = " ".join(current + [piece])
            if current and (len(candidate.split()) > max_words or (max_chars and len(candidate) > max_chars)):
                parts.append(" ".join(current))
                current = [piece]
            else:
                current.append(piece)
            if len(" ".join(current).split()) >= target_words:
                parts.append(" ".join(current))
                current = []
        if current:
            parts.append(" ".join(current))
    if " ".join(parts) != source:
        raise ValueError("unit split did not preserve normalized parent text")
    if len(parts) >= _UNIT_INDEX_STRIDE:
        raise ValueError("passage has too many repair units")
    return [{
        "index": parent_index * _UNIT_INDEX_STRIDE + unit_index,
        "parent_index": parent_index,
        "unit_index": unit_index,
        "text": text,
        "speaker_text": "Speaker 0: " + text,
        "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "identity": _identity(parent_identity, unit_index, text),
    } for unit_index, text in enumerate(parts)]


def _validate_units(passage, units):
    source = normalize_text(passage["text"])
    parent_index, parent_identity = passage["index"], passage["identity"]
    ordered = sorted(units, key=lambda unit: unit.get("unit_index", -1))
    if [unit.get("unit_index") for unit in ordered] != list(range(len(ordered))):
        raise ValueError("units must have contiguous unique unit_index values")
    if any(unit.get("parent_index") != parent_index for unit in ordered):
        raise ValueError("units belong to a different parent passage")
    if any(unit.get("index") != parent_index * _UNIT_INDEX_STRIDE + unit["unit_index"] for unit in ordered):
        raise ValueError("unit index does not match its parent")
    if any(unit.get("identity") != _identity(parent_identity, unit["unit_index"], unit.get("text", "")) for unit in ordered):
        raise ValueError("unit identity does not match its parent")
    if " ".join(unit.get("text", "") for unit in ordered) != source:
        raise ValueError("units do not preserve normalized parent text")
    return ordered


def _reports_by_unit(units, reports):
    by_index = {}
    for report in reports:
        index = report.get("unit_index")
        if not isinstance(index, int) or index in by_index:
            raise ValueError("reports must provide one unique unit_index per unit")
        by_index[index] = report
    expected = set(range(len(units)))
    if set(by_index) != expected:
        raise ValueError("reports must cover every repair unit")
    return by_index


def parent_quality(passage, unit_reports, units=None):
    """Apply the original parent coverage threshold to ordered unit transcripts."""
    units = _validate_units(passage, repair_units(passage) if units is None else units)
    reports = _reports_by_unit(units, unit_reports)
    transcript = " ".join(str(reports[index].get("comparison_transcript", reports[index].get("transcript", ""))).strip()
                          for index in range(len(units))).strip()
    expected = normalize_text(' '.join(unit.get('spoken_text', unit['text']) for unit in units))
    return numbered_heading_assessment(expected, transcript) if passage.get("heading") else assess(expected, transcript)


def choose_repair_unit(units, reports, exclude=()):
    """Return the highest-impact eligible differing unit, deterministically."""
    by_index = _reports_by_unit(units, reports)
    excluded = set(exclude)
    candidates = []
    for unit in units:
        report = by_index[unit["unit_index"]]
        score = int(report.get("missing_words", 0)) + int(report.get("inserted_words", 0))
        if unit["unit_index"] not in excluded and (score or report.get("differences")):
            candidates.append((-score, unit["unit_index"], unit))
    if not candidates:
        raise ValueError("no repairable unit differences")
    return min(candidates)[2]
