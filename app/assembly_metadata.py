"""Dependency-free helpers for chapter metadata assembled from PDF provenance."""

import bisect
import re


DIVISION_RE = re.compile(
    r"^(BOOK|CHAPTER|PART|CANTO|PROLOGUE|EPILOGUE|INTRODUCTION|PREFACE|FOREWORD|AFTERWORD)\b",
    re.IGNORECASE,
)
NUMBERED_TITLE_RE = re.compile(r"^\d+\s*(?:[-:\u2013\u2014]|$)")
ROMAN_TITLE_RE = re.compile(r"^[IVXLCDM]+\s*(?:[-:\u2013\u2014]|$)", re.IGNORECASE)


def is_outline_chapter_title(title):
    """True for top-level book divisions, not ordinary numbered sections."""
    text = " ".join(str(title or "").split())
    return bool(
        text
        and (
            DIVISION_RE.match(text)
            or NUMBERED_TITLE_RE.match(text)
            or ROMAN_TITLE_RE.match(text)
        )
    )


def outline_chapter_marks(outline, page_starts):
    """Map selected PDF-outline entries to exact first-audio timestamps.

    ``outline`` entries contain ``level``, ``title``, and 1-based ``page``.
    ``page_starts`` is an iterable of ``(source_page, milliseconds)`` for the
    first narration chunk on each extracted page. If an outline destination is
    a decorative/empty page, it maps to the first narrated page after it.
    """
    first_by_page = {}
    for page, milliseconds in page_starts:
        page = int(page)
        first_by_page.setdefault(page, int(milliseconds))
    pages = sorted(first_by_page)
    if not pages:
        return []

    by_time = {}
    for entry in outline or []:
        title = " ".join(str(entry.get("title", "")).split())
        if not is_outline_chapter_title(title):
            continue
        try:
            page = int(entry.get("page"))
            level = int(entry.get("level", 1))
        except (TypeError, ValueError):
            continue
        if page < pages[0] or page > pages[-1]:
            continue
        pos = bisect.bisect_left(pages, page)
        if pos >= len(pages):
            continue
        milliseconds = first_by_page[pages[pos]]
        existing = by_time.get(milliseconds)
        # Duplicate destinations cannot form valid zero-length ffmetadata
        # chapters. Prefer the more specific (deeper) outline entry.
        if existing is None or level >= existing[0]:
            by_time[milliseconds] = (level, title)
    return [(milliseconds, value[1]) for milliseconds, value in sorted(by_time.items())]
