"""Deterministic sub-passage planning for VibeVoice quality repair."""

import hashlib
import json

try:
    from .vibevoice_plan import _split_oversize, normalize_text
    from .vibevoice_quality import assess
except ImportError:  # Worker execution adds app/ directly to sys.path.
    from vibevoice_plan import _split_oversize, normalize_text
    from vibevoice_quality import assess


UNIT_TARGET_WORDS = 120
UNIT_MAX_WORDS = 180
UNIT_SPLIT_REVISION = 1
_UNIT_INDEX_STRIDE = 10_000
_ABBREVIATIONS = {"dr.", "fig.", "i.e.", "jr.", "mr.", "mrs.", "ms.", "no.", "prof.", "sr.", "st.", "vs."}


def _sentence_parts(text):
    start, parts = 0, []
    for index, character in enumerate(text):
        if character not in ".!?":
            continue
        before = text[max(start, index - 11):index + 1].lower()
        if any(before.endswith(abbreviation) for abbreviation in _ABBREVIATIONS):
            continue
        end = index + 1
        while end < len(text) and text[end] in "\"'”’":
            end += 1
        if end >= len(text) or not text[end].isspace():
            continue
        next_start = end
        while next_start < len(text) and text[next_start].isspace():
            next_start += 1
        if next_start < len(text) and (text[next_start].isupper() or text[next_start].isdigit() or text[next_start] in "\"'“‘"):
            parts.append(text[start:end])
            start = next_start
    parts.append(text[start:])
    return [part for part in parts if part]


def _identity(parent_identity, unit_index, text):
    payload = {"parent_identity": parent_identity, "split_revision": UNIT_SPLIT_REVISION, "unit_index": unit_index, "text": text}
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def repair_units(passage, target_words=UNIT_TARGET_WORDS, max_words=UNIT_MAX_WORDS):
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
        sentences = _sentence_parts(source)
        pieces = []
        for sentence in sentences:
            pieces.extend(_split_oversize(sentence, max_words) if len(sentence.split()) > max_words else [sentence])
        parts, current = [], []
        for piece in pieces:
            candidate = " ".join(current + [piece])
            if current and len(candidate.split()) > max_words:
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
    transcript = " ".join(str(reports[index].get("transcript", "")).strip() for index in range(len(units))).strip()
    return assess(normalize_text(passage["text"]), transcript)


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
