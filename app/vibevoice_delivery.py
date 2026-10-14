"""Conservative spoken-text cleanup and explicit dialogue/aside boundaries."""

import re

PROFILE = "dialogue_asides_no_page_refs_v1"
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


def delivery_parts(text):
    """Keep every spoken word; distinguish quotes from in-word apostrophes."""
    text = spoken_text(text)
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
