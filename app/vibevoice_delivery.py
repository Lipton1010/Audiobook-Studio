"""Conservative spoken-text cleanup and explicit dialogue/aside boundaries."""

import re
import hashlib
import json
import calendar

PROFILE = "dialogue_asides_no_page_refs_v1"
INTACT_PROFILE = "intact_context_no_page_refs_v1"
PROJECTION_VERSION = "calendar_clock_v2"
_POLICIES = {
    PROFILE: {"split": "quotes_asides_v1", "gap_ms": 200, "fade_ms": 5, "aside_gain": 0.84},
    INTACT_PROFILE: {"split": "none", "gap_ms": 0, "fade_ms": 0, "aside_gain": 1.0},
    "ascii_intra_word_apostrophe_v1": {"split": "none", "apostrophes": "ascii"},
    "outline_prefix_case_ascii_apostrophe_v1": {"split": "none", "heading": "outline_prefix_v1"},
    "numbered_outline_heading_ascii_apostrophe_v1": {"split": "none", "heading": "numbered_outline_v1"},
    None: {"split": "none", "text": "canonical_v1"},
}
_PAGE_REFERENCE = re.compile(r"\(\s*pp?\.\s*\d+(?:\s*[-–]\s*\d+)?\s*(?:;\s*([^()]+))?\)", re.I)


def spoken_text(text):
    # Keep prose parentheses and in-sentence references such as 'see page 12'.
    return " ".join(_PAGE_REFERENCE.sub(lambda m: f"({m[1].strip()})" if m[1] else "", text).split())


def spoken_units(units):
    """Project reference omissions across old unit boundaries without repacking."""
    text = " ".join(unit["text"] for unit in units)
    keep = bytearray(b'\x01') * len(text)
    for match in _PAGE_REFERENCE.finditer(text):
        keep[match.start():match.end()] = b'\x00' * (match.end() - match.start())
        if match[1]:
            keep[match.start(1):match.end(1)] = b'\x01' * len(match[1])
    offset = 0
    result = []
    for unit in units:
        end = offset + len(unit["text"])
        spoken = " ".join(''.join(text[i] for i in range(offset, end) if keep[i]).split())
        result.append({**unit, **({"spoken_text": spoken} if spoken != unit["text"] else {})})
        offset = end + 1
    return result


def text_hash(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def policy_hash(profile):
    """Frozen policies let old receipts retain their original meaning."""
    return text_hash(json.dumps(_POLICIES[profile], sort_keys=True, separators=(',', ':')))


def calendar_clock_edits(text):
    """Only explicit calendar days and clocks; leave bare numbers and names alone."""
    try:
        from .vibevoice_quality import integer_words
    except ImportError:
        from vibevoice_quality import integer_words
    ordinals = ('', 'first', 'second', 'third', 'fourth', 'fifth', 'sixth', 'seventh',
                'eighth', 'ninth', 'tenth', 'eleventh', 'twelfth', 'thirteenth',
                'fourteenth', 'fifteenth', 'sixteenth', 'seventeenth', 'eighteenth',
                'nineteenth', 'twentieth', 'twenty-first', 'twenty-second', 'twenty-third',
                'twenty-fourth', 'twenty-fifth', 'twenty-sixth', 'twenty-seventh',
                'twenty-eighth', 'twenty-ninth', 'thirtieth', 'thirty-first')
    months = '|'.join(calendar.month_name[1:])
    edits = []
    for match in re.finditer(r'\b(' + months + r') ([1-9]|[12]\d|3[01])(?: (and|or) ([1-9]|[12]\d|3[01]))?(?![\w/–-]|\.\d)', text):
        month, day, join, other = match.groups()
        tail = text[match.end():]
        prefix = text[:match.start()]
        if month == 'May' and not (re.match(r',?\s+(?:18|19|20)\d{2}\b', tail)
                                   or re.search(r'\b(?:on|by|since|until)\s+$', prefix, re.I)):
            continue
        year = re.match(r',?\s+((?:18|19|20)\d{2})\b', tail)
        maximum = calendar.monthrange(int(year[1]) if year else 2000, list(calendar.month_name).index(month))[1]
        if any(int(value) > maximum for value in (day, other) if value):
            continue
        after = month + ' ' + ordinals[int(day)]
        if other:
            after += ' ' + join + ' ' + ordinals[int(other)]
        edits.append({'start': match.start(), 'end': match.end(), 'before': match[0],
                      'after': after, 'reason': 'explicit calendar day'})
    clock = r'(?<![\w:])([1-9]|1[0-2]):([0-5]\d)\s*([ap])\.?m\.?(?!\w)'
    for match in re.finditer(clock, text, re.I):
        hour, minute, period = int(match[1]), int(match[2]), match[3].upper()
        after = ' '.join(integer_words(hour))
        after += " o'clock" if minute == 0 else ' ' + ('oh ' if minute < 10 else '') + ' '.join(integer_words(minute))
        # Preserve a sentence-ending dot while spelling out the clock suffix.
        after += ' ' + period + ' M' + ('.' if match[0].endswith('.') else '')
        edits.append({'start': match.start(), 'end': match.end(), 'before': match[0],
                      'after': after, 'reason': 'explicit clock'})
    return edits


def project_units(units, parent, config):
    """Apply exact, evidence-backed edits without rewriting canonical source."""
    projection = config.get('spoken_projection', {})
    version = projection.get('version')
    if version not in (None, PROJECTION_VERSION):
        raise ValueError('Unknown spoken projection version')
    text = ' '.join(unit['text'] for unit in units)
    edits = calendar_clock_edits(text) if version == PROJECTION_VERSION else []
    for edit in projection.get('corrections', []):
        if edit.get('parent_identity') != parent['identity']:
            continue
        if not edit.get('evidence') or not edit.get('source_pages'):
            raise ValueError('Spoken correction requires source evidence and pages')
        edits.append(edit)
    chars = list(text)
    end = 0
    for edit in sorted(edits, key=lambda e: e['start']):
        start, stop = edit['start'], edit['end']
        if (type(start) is not int or type(stop) is not int or start < end
                or not 0 <= start < stop <= len(text) or text[start:stop] != edit['before']
                or not isinstance(edit['after'], str)):
            raise ValueError('Spoken correction has stale, overlapping, or invalid source offsets')
        chars[start] = edit['after']
        chars[start + 1:stop] = [''] * (stop - start - 1)
        end = stop
    result, offset = [], 0
    # Reference omission still spans unit boundaries, using the existing layer.
    projected = []
    for unit in units:
        stop = offset + len(unit['text'])
        item = {**unit, 'text': ''.join(chars[offset:stop])}
        item.pop('spoken_text', None)
        projected.append(item)
        offset = stop + 1
    for unit, spoken in zip(units, spoken_units(projected)):
        value = spoken.get('spoken_text', spoken['text'])
        value = ' '.join(value.split())
        item = {**unit}
        item.pop('spoken_text', None)
        if value != unit['text']:
            item['spoken_text'] = value
        profile = config.get('delivery_profiles', {}).get(unit['identity'])
        if profile is not None:
            if profile not in (PROFILE, INTACT_PROFILE):
                raise ValueError('Unknown requested delivery policy')
            item['render_profile'] = profile
        result.append(item)
    return result


def receipt_matches_projection(receipt, unit):
    """Legacy receipts are compatible only with the text they actually rendered."""
    profile = receipt.get('render_profile')
    if profile not in _POLICIES:
        return False
    if receipt.get('render_policy_sha256', policy_hash(profile)) != policy_hash(profile):
        return False
    if unit.get('render_profile') in (PROFILE, INTACT_PROFILE) and profile != unit['render_profile']:
        return False
    spoken = unit.get('spoken_text', unit['text'])
    if 'spoken_text_sha256' in receipt and receipt['spoken_text_sha256'] != text_hash(spoken):
        return False
    if profile is None:
        return spoken == unit['text'] and receipt.get('render_text_sha256', text_hash(spoken)) == text_hash(spoken)
    rendered = spoken
    if profile == 'outline_prefix_case_ascii_apostrophe_v1':
        heading = unit.get('render_heading') or receipt.get('render_heading', '')
        rendered = heading + spoken[len(heading):]
    elif profile == 'numbered_outline_heading_ascii_apostrophe_v1':
        rendered = unit.get('render_heading') or receipt.get('render_heading', '')
    rendered = re.sub(r"(?<=[^\W\d_])’(?=[^\W\d_])", "'", rendered)
    if unit.get('scene_direction_compiled'):
        try:
            from scene_direction import render_unit
            rendered = render_unit(unit, rendered)
        except ValueError:
            return False
    return receipt.get('render_text_sha256') == text_hash(rendered)


def delivery_parts(text, profile=PROFILE):
    """Keep every spoken word; distinguish quotes from in-word apostrophes."""
    text = spoken_text(text)
    if profile == INTACT_PROFILE:
        return [{'text': text, 'aside': False}] if text else []
    if profile != PROFILE:
        raise ValueError('Unknown delivery policy')
    cuts = {0, len(text)}
    asides = []
    for match in re.finditer(r"\([^()]+\)", text):
        cuts.update((match.start(), match.end()))
        asides.append((match.start(), match.end()))
    quotes = []
    for index, char in enumerate(text):
        before = text[index - 1] if index else ''
        after = text[index + 1] if index + 1 < len(text) else ''
        if char not in "‘’'“”\"" or (before.isalnum() and after.isalnum()):
            continue
        if char in '‘“' or (char in "'\"" and (not before or before.isspace() or before in '(:')):
            # Keep attribution with the following speech. Tiny isolated
            # narrator fragments are less reliable than complete context.
            closing = '’' if char == '‘' else '”' if char == '“' else char
            quotes.append((closing, index))
        elif quotes and char == quotes[-1][0]:
            quotes.pop()
            if not quotes and before in '.!?,…':
                cuts.add(index + 1)
        elif not quotes and char in '’”' and before in '.!?…':
            cuts.add(index + 1)
    ordered = sorted(cuts)
    parts = []
    for start, end in zip(ordered, ordered[1:]):
        piece = text[start:end].strip().lstrip(':; ')
        if not piece or not any(c.isalnum() for c in piece):
            continue
        aside = (start, end) in asides
        if aside:
            piece = piece[1:-1].strip()
        parts.append({'text': piece, 'aside': aside})
    return parts
