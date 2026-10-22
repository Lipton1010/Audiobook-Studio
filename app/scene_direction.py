"""Optional source-bound performance notes. No inference or I/O at import time.

Offsets are Unicode code points, never UTF-16 indices. Canonical text is immutable;
only the compiler may insert cues, and it records every insertion for exact undo.
"""
import copy
import hashlib
import json
import math
import re

POLICY = "scene_direction_v2_source_context"
CUE_VERSION = "drama3_native_4e6018f_documented_v1"
# Documented syntax, NOT a claim of perceptually validated local delivery.
# No generic S1/S2 vocabulary, invented neutral reset, or nonverbal auto-insertion.
CUES = {"whisper": "[whisper]", "angry": "[angry]", "laughing": "[laughing]",
        "sighs": "[sighs]", "laughs": "[laughs]"}
EVENTS = {"laughing", "sighs", "laughs"}
MIN_CONFIDENCE = 0.85


def digest(value):
    data = value if isinstance(value, str) else json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def canonical(passages, extraction_sha256):
    """Snapshot the existing planner's text separately from original extraction."""
    rows, offset = [], 0
    for index, passage in enumerate(passages):
        text = passage["text"]
        if not isinstance(text, str) or not text:
            raise ValueError("Canonical passage must contain text")
        rows.append({"index": index, "start": offset, "end": offset + len(text),
                     "text": text, "text_sha256": digest(text),
                     "source_pages": passage.get("source_pages", []),
                     "heading": bool(passage.get("heading"))})
        offset += len(text) + 2
    return {"schema": 1, "extraction_sha256": extraction_sha256,
            "text": "\n\n".join(row["text"] for row in rows), "passages": rows}


def validate_source(source):
    if not isinstance(source, dict) or source.get("schema") != 1 or not isinstance(source.get("passages"), list):
        raise ValueError("Invalid canonical schema")
    rebuilt = canonical(source["passages"], source.get("extraction_sha256"))
    if rebuilt != source:
        raise ValueError("Canonical offsets, hashes or text changed")
    return source["text"]


def new_plan(source, model, model_digest):
    validate_source(source)
    return {"schema": 1, "policy": POLICY, "cue_version": CUE_VERSION,
            "canonical_sha256": digest(source), "model": model, "model_digest": model_digest,
            "spans": [], "context": [], "overrides": {}}


def _string(value, name, maximum=2000, empty=False):
    if not isinstance(value, str) or (not empty and not value.strip()) or len(value) > maximum:
        raise ValueError("Invalid " + name)


def _anchor(anchor, text):
    if not isinstance(anchor, dict) or set(anchor) != {"start", "end", "quote"}:
        raise ValueError("Evidence needs exact start/end/quote")
    start, end = anchor["start"], anchor["end"]
    if type(start) is not int or type(end) is not int or not 0 <= start < end <= len(text) or text[start:end] != anchor["quote"]:
        raise ValueError("Stale or invented source span")


def source_frame(source, start, end, limit=6000):
    """Exact paragraph context, independent of analysis-window boundaries.

    An oversized paragraph stays explicitly incomplete, never a silent summary.
    The prefix is retained so introductory attribution/medium cannot disappear.
    """
    text = source['text']
    left = text.rfind('\n\n', 0, start) + 2 if '\n\n' in text[:start] else 0
    right = text.find('\n\n', end)
    right = len(text) if right < 0 else right
    stop = min(right, left + limit)
    return {'start': left, 'end': stop, 'quote': text[left:stop],
            'paragraph_end': right, 'complete': stop == right}


def source_flags(source, span):
    """Conservative review signals, not semantic role or speaker assignments.

    Only markers preceding the quote in its paragraph can affect its medium.
    In particular, a later email must not turn earlier spoken dialogue into mail.
    """
    frame = source_frame(source, span['start'], span['end'])
    text = source['text']
    prefix = text[frame['start']:span['start']]
    flags = []
    def flag(code, start, end):
        flags.append({'code': code, 'evidence': {'start': start, 'end': end, 'quote': text[start:end]}})
    written = list(re.finditer(r'\b(?:Facebook|written response|private channel|e-?mail|text message|messaged|wrote|letter)\b', prefix, re.I))
    spoken = list(re.finditer(r'\b(?:spoke to|spoke with|on the phone|phone call|said aloud)\b', prefix, re.I))
    if written and (not spoken or written[-1].start() > spoken[-1].start()):
        marker = written[-1]
        flag('possible_written_medium', frame['start'] + marker.start(), frame['start'] + marker.end())
    quote = text[span['start']:span['end']].lstrip('"\u201c\u201d\u2018\u2019 ')
    if quote and quote[0].islower():
        flag('possible_quoted_fragment', span['start'], span['end'])
    reported = list(re.finditer(r'\b(?:report|reported)\b[^.!?\n]{0,120}\b(?:yell\w*|cried|cry|shout\w*)\b', prefix, re.I))
    if reported and len(prefix) - reported[-1].end() < 60:
        marker = reported[-1]
        flag('reported_cry_not_current_turn', frame['start'] + marker.start(), frame['start'] + marker.end())
    if not frame['complete']:
        flag('paragraph_context_exceeds_bound', frame['start'], frame['end'])
    return flags


def validate_context_fact(text, fact):
    """Require an exact extract in its selected evidence, not a plausible paraphrase.

    This proves provenance only. It does not prove the attribution, entailment,
    completeness or truth of a statement; proposals never become prompt memory.
    """
    if not isinstance(fact, dict) or set(fact) != {'character', 'fact', 'evidence'}:
        raise ValueError('Invalid character/story context')
    _string(fact['character'], 'character', 200)
    _string(fact['fact'], 'fact', 600)
    _anchor(fact['evidence'], text)
    excerpt = fact['fact']
    evidence = fact['evidence']['quote']
    if excerpt not in evidence:
        raise ValueError('Context proposal is not an exact extract of selected evidence')
    offset = evidence.index(excerpt)
    if ((offset and evidence[offset-1].isalnum() and excerpt[0].isalnum()) or
            (offset + len(excerpt) < len(evidence) and excerpt[-1].isalnum() and evidence[offset+len(excerpt)].isalnum())):
        raise ValueError('Context extract cuts a word boundary')
    if not excerpt.rstrip(' \t\r\n"\u201d\u2019\'').endswith(('.', '!', '?')):
        raise ValueError('Context extract is an incomplete sentence or fragment')


def validate_plan(source, plan):
    text = validate_source(source)
    required = {"schema", "policy", "cue_version", "canonical_sha256", "model", "model_digest", "spans", "context", "overrides"}
    if not isinstance(plan, dict) or set(plan) != required or plan["schema"] != 1 or plan["policy"] != POLICY or plan["cue_version"] != CUE_VERSION or plan["canonical_sha256"] != digest(source):
        raise ValueError("Stale or unsupported direction plan")
    _string(plan["model"], "model", 200)
    _string(plan["model_digest"], "model digest", 100)
    if not isinstance(plan["spans"], list) or len(plan["spans"]) > 10000 or not isinstance(plan["context"], list) or len(plan["context"]) > 200:
        raise ValueError("Invalid annotation arrays")
    span_keys = {"id", "start", "end", "quote", "scene", "kind", "speaker", "intention", "emotion", "intensity", "delivery", "confidence", "evidence", "ambiguity"}
    previous_end, ids = 0, set()
    for span in plan["spans"]:
        if not isinstance(span, dict) or set(span) != span_keys:
            raise ValueError("Invalid annotation schema")
        _anchor({key: span[key] for key in ("start", "end", "quote")}, text)
        if span["start"] < previous_end or span["id"] in ids:
            raise ValueError("Overlapping or duplicate annotations")
        previous_end = span["end"]
        ids.add(span["id"])
        for key in ("id", "scene", "speaker", "intention", "emotion", "delivery"):
            _string(span[key], key, 500)
        _string(span["ambiguity"], "ambiguity", empty=True)
        if span["kind"] not in ("dialogue", "narrator") or (span["kind"] == "narrator" and span["speaker"] != "narrator"):
            raise ValueError("Narrator and dialogue roles must be explicit")
        if type(span["intensity"]) is not int or not 0 <= span["intensity"] <= 3:
            raise ValueError("Invalid intensity")
        confidence = span["confidence"]
        if type(confidence) not in (int, float) or not math.isfinite(confidence) or not 0 <= confidence <= 1:
            raise ValueError("Invalid confidence")
        if not isinstance(span["evidence"], list) or not 1 <= len(span["evidence"]) <= 5:
            raise ValueError("Direction requires source evidence")
        for evidence in span["evidence"]:
            _anchor(evidence, text)
    for fact in plan["context"]:
        validate_context_fact(text, fact)
    if not isinstance(plan["overrides"], dict) or set(plan["overrides"]) - ids:
        raise ValueError("Override does not identify a source-bound annotation")
    for override in plan["overrides"].values():
        if not isinstance(override, dict) or set(override) != {"decision", "delivery", "speaker", "note"} or override["decision"] not in ("use", "plain"):
            raise ValueError("Invalid user override")
        for key in ("delivery", "speaker", "note"):
            _string(override[key], "override " + key, 1000)
    return plan


def effective(span, plan):
    result = copy.deepcopy(span)
    override = plan["overrides"].get(span["id"])
    if override:
        result.update(delivery=override["delivery"] if override["decision"] == "use" else "plain",
                      speaker=override["speaker"], user_override=override)
    return result


def _reason(span):
    if not span.get("user_override") and (span["confidence"] < MIN_CONFIDENCE or span["ambiguity"] or span["speaker"] == "unknown"):
        return "ambiguous direction; review or render plain"
    if span["delivery"] in ("plain", "neutral", "calm"):
        return None  # Calm surface delivery must not inherit concealed anger.
    if span["delivery"] not in CUES:
        return "unsupported delivery; retained as a note, rendered plain"
    if not span.get("user_override"):
        if span["delivery"] in EVENTS:
            return "nonverbal event requires explicit user choice"
    if span["kind"] == "narrator":
        return "narrator delivery remains plain in this first audition"
    return None


def compile_range(source, plan, start, end, base_text=None, max_chars=1000):
    """Insert sparse supported cues; never guess a reset across narrator prose.

    We keep complete turns and existing chunks. Until a neutral reset is auditioned,
    a cue followed by prose/another turn within the chunk is withheld for review.
    """
    validate_plan(source, plan)
    text = source["text"]
    if type(start) is not int or type(end) is not int or not 0 <= start < end <= len(text):
        raise ValueError("Invalid compile range")
    original = text[start:end]
    base = original if base_text is None else base_text
    rows = [effective(s, plan) for s in plan["spans"] if s["start"] < end and s["end"] > start]
    insertions, review = [], []
    for span in rows:
        reason = _reason(span)
        flags = source_flags(source, span)
        if not span.get('user_override') and flags:
            reason = 'source context requires review: ' + ', '.join(row['code'] for row in flags)
        cue = CUES.get(span["delivery"])
        if not cue:
            if reason:
                review.append({"id": span["id"], "reason": reason})
            continue
        if not reason and (span["start"] < start or span["end"] > end):
            reason = "turn crosses existing chunk boundary; kept intact and plain"
        if not reason and base != original:
            reason = "spoken projection differs; exact cue alignment needs review"
        if not reason and original[span["end"] - start:].strip(' \t\r\n\"\u201d\u2019\'.!?,;:'):
            reason = "following narrator or turn needs an auditioned reset; rendered plain"
        if not reason and (insertions or span["start"] - start < 0):
            reason = "sparse cue budget exhausted"
        if reason:
            review.append({"id": span["id"], "reason": reason})
        else:
            insertions.append({"at": span["start"] - start, "cue": cue, "id": span["id"]})
    rendered = base
    for insertion in reversed(insertions):
        rendered = rendered[:insertion["at"]] + insertion["cue"] + rendered[insertion["at"]:]
    if len(rendered) > max_chars:
        if len(base) > max_chars:
            raise ValueError("Source exceeds native chunk bound; no text was truncated")
        review += [{"id": row["id"], "reason": "cue exceeds native chunk bound; rendered plain"} for row in insertions]
        insertions, rendered = [], base
    # Undo only our insertions, not bracketed source text.
    restored = rendered
    for insertion in insertions:
        at, cue = insertion["at"], insertion["cue"]
        if restored[at:at + len(cue)] != cue:
            raise ValueError("Cue integrity failure")
        restored = restored[:at] + restored[at + len(cue):]
    if restored != base:
        raise ValueError("Compilation changed source text")
    return {"base_sha256": digest(base), "render_text": rendered, "render_sha256": digest(rendered),
            "insertions": insertions, "review": review, "plan_sha256": digest(plan), "policy": POLICY}


def binding(config):
    value = config.get("scene_direction")
    if value is None:
        return None
    if not isinstance(value, dict) or set(value) != {"source", "plan"}:
        raise ValueError("Invalid scene direction binding")
    validate_plan(value["source"], value["plan"])
    return value


def attach_units(units, parent, config):
    bound = binding(config)
    if not bound:
        return units
    source, plan = bound["source"], bound["plan"]
    index = parent["index"]
    if not 0 <= index < len(source["passages"]):
        raise ValueError("Directed passage missing from canonical source")
    passage = source["passages"][index]
    if parent["text"] != passage["text"]:
        raise ValueError("Direction source differs from narration plan")
    result, cursor = [], 0
    for unit in units:
        start = passage["text"].find(unit["text"], cursor)
        if start < 0 or passage["text"][cursor:start].strip():
            raise ValueError("Cannot map narration unit to exact source span")
        stop = start + len(unit["text"])
        # Match the pre-existing ASCII apostrophe rendering, without editing canonical.
        base = re.sub(r"(?<=[^\W\d_])\u2019(?=[^\W\d_])", "'", unit.get("spoken_text", unit["text"]))
        compiled = compile_range(source, plan, passage["start"] + start, passage["start"] + stop, base)
        result.append({**unit, "scene_direction_compiled": compiled})
        cursor = stop
    if passage["text"][cursor:].strip():
        raise ValueError("Directed unit coverage is incomplete")
    return result


def render_unit(unit, base):
    compiled = unit.get("scene_direction_compiled")
    if not compiled:
        return base
    if compiled.get("policy") != POLICY or compiled.get("base_sha256") != digest(base) or compiled.get("render_sha256") != digest(compiled.get("render_text", "")):
        raise ValueError("Stale compiled direction")
    restored = compiled["render_text"]
    for row in compiled["insertions"]:
        at, cue = row["at"], row["cue"]
        if cue not in CUES.values() or restored[at:at + len(cue)] != cue:
            raise ValueError("Unsupported compiled cue")
        restored = restored[:at] + restored[at + len(cue):]
    if restored != base:
        raise ValueError("Compiled text does not preserve narration text")
    return compiled["render_text"]
