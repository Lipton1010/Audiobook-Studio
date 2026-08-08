"""Deterministic cast-to-voice narration planning.

The character model is never allowed to rewrite the book.  This module turns
the validated spans in ``cast_plan.json`` into narration chunks by slicing the
canonical text in ``blocks.json``.  Every chunk retains its exact source span
and block hash, and the completed plan is checked for non-whitespace source
preservation before it can reach Chatterbox.

This module is stdlib-only so both the base-env server and the isolated
Chatterbox worker can use the same compiler.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import OrderedDict
from typing import Any, Iterable


PLAN_VERSION = "1"
NARRATOR_ID = "narrator"
NARRATION_CHAR_CEILING = 400
# Stage 0/1 listening preferred a complete 480-character turn.  Keep common
# dialogue turns whole and only fall back to sentence/clause packing for the
# rare much longer turn.
DIALOGUE_CHAR_CEILING = 600
SENTENCE_SPLIT_RE = re.compile(r'(?<=[.!?])\s+(?=[A-Z"\'‘“])')
CLAUSE_SPLIT_RE = re.compile(r"(?<=[,;])\s+")


class MultiVoicePlanError(ValueError):
    """The cast assignments cannot produce a source-safe narration plan."""


def block_text_hash(block: dict[str, Any]) -> str:
    return hashlib.sha256(str(block.get("text", "")).encode("utf-8")).hexdigest()


def source_hash(blocks: list[dict[str, Any]]) -> str:
    spoken = [
        {"type": block.get("type"), "text": block.get("text", "")}
        for block in blocks
    ]
    payload = json.dumps(
        spoken, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def validate_cast_anchors(
    cast_plan: dict[str, Any], blocks: list[dict[str, Any]]
) -> None:
    """Enforce the source contract again inside the TTS environment."""
    if cast_plan.get("source_sha256") != source_hash(blocks):
        raise MultiVoicePlanError("cast source hash does not match blocks.json")
    for turn in cast_plan.get("turns", []):
        block_index = turn.get("block_index")
        if not isinstance(block_index, int) or not 0 <= block_index < len(blocks):
            raise MultiVoicePlanError("cast turn has an invalid block index")
        text = str(blocks[block_index].get("text", ""))
        start, end = turn.get("start"), turn.get("end")
        if (
            not isinstance(start, int)
            or not isinstance(end, int)
            or not 0 <= start < end <= len(text)
        ):
            raise MultiVoicePlanError("cast turn has an invalid source span")
        if turn.get("block_sha256") != block_text_hash(blocks[block_index]):
            raise MultiVoicePlanError("cast turn block hash does not match source")


def required_voice_roles(cast_plan: dict[str, Any]) -> list[dict[str, Any]]:
    """Narrator plus active characters that own at least one attributed turn."""
    narrator = cast_plan.get("narrator") or {}
    roles = [{
        "id": NARRATOR_ID,
        "display_name": str(narrator.get("display_name") or "Narrator"),
        "voice_name": narrator.get("voice_name"),
        "voice_type": narrator.get("voice_type", "unknown"),
        "role": "narrator",
        "turn_count": None,
    }]
    for character in cast_plan.get("characters", []):
        if character.get("invalid") or int(character.get("turn_count", 0)) <= 0:
            continue
        roles.append({
            "id": character["id"],
            "display_name": character["display_name"],
            "voice_name": character.get("voice_name"),
            "voice_type": character.get("voice_type", "unknown"),
            "role": "character",
            "turn_count": int(character.get("turn_count", 0)),
        })
    return roles


def _trim_span(text: str, start: int, end: int) -> tuple[int, int] | None:
    while start < end and text[start].isspace():
        start += 1
    while end > start and text[end - 1].isspace():
        end -= 1
    return (start, end) if start < end else None


def _split_spans(
    text: str, start: int, end: int, pattern: re.Pattern[str]
) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    cursor = start
    for match in pattern.finditer(text, start, end):
        trimmed = _trim_span(text, cursor, match.start())
        if trimmed:
            spans.append(trimmed)
        cursor = match.end()
    trimmed = _trim_span(text, cursor, end)
    if trimmed:
        spans.append(trimmed)
    return spans


def _greedy_spans(
    text: str, units: Iterable[tuple[int, int]], ceiling: int
) -> list[tuple[int, int]]:
    packed: list[tuple[int, int]] = []
    current: tuple[int, int] | None = None
    for start, end in units:
        if current is None:
            current = (start, end)
            continue
        candidate = text[current[0]:end].strip()
        if len(candidate) <= ceiling:
            current = (current[0], end)
        else:
            packed.append(current)
            current = (start, end)
    if current:
        packed.append(current)
    return packed


def pack_source_span(
    text: str, start: int, end: int, ceiling: int
) -> list[tuple[int, int]]:
    """Sentence-safe packing that returns exact offsets into ``text``.

    A single clause longer than the ceiling remains whole, matching the
    existing packer's soft-ceiling behavior instead of cutting through words.
    """
    trimmed = _trim_span(text, start, end)
    if not trimmed:
        return []
    start, end = trimmed
    if end - start <= ceiling:
        return [(start, end)]

    sentences = _split_spans(text, start, end, SENTENCE_SPLIT_RE)
    expanded: list[tuple[int, int]] = []
    for sentence_start, sentence_end in sentences:
        if sentence_end - sentence_start <= ceiling:
            expanded.append((sentence_start, sentence_end))
            continue
        clauses = _split_spans(
            text, sentence_start, sentence_end, CLAUSE_SPLIT_RE
        )
        expanded.extend(_greedy_spans(text, clauses, ceiling))
    return _greedy_spans(text, expanded, ceiling)


def normalize_quoted_ellipsis(text: str) -> str:
    """Retain the production worker's deterministic spoken-text normalization."""
    quote_pairs = [("\"", "\""), ("“", "”"), ("'", "'"), ("‘", "’")]
    result = text
    for open_q, close_q in quote_pairs:
        pattern = (
            re.escape(open_q)
            + r"([^"
            + re.escape(open_q)
            + re.escape(close_q)
            + r"]*?)"
            + re.escape(close_q)
        )

        def replacer(match: re.Match[str]) -> str:
            inner = re.sub(r"\.{2,}", "", match.group(1)).rstrip()
            return open_q + inner + close_q

        result = re.sub(pattern, replacer, result)
    return result


def _role_parts(
    block_index: int,
    text: str,
    turns: list[dict[str, Any]],
    active_characters: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    narrator_voice = active_characters[NARRATOR_ID].get("voice_name")
    parts: list[dict[str, Any]] = []

    def append_part(start: int, end: int, speaker_id: str) -> None:
        trimmed = _trim_span(text, start, end)
        if not trimmed:
            return
        start, end = trimmed
        role = active_characters[speaker_id]
        if (
            parts
            and parts[-1]["speaker_id"] == speaker_id
            and not text[parts[-1]["end"]:start].strip()
        ):
            parts[-1]["end"] = end
            return
        parts.append({
            "block_index": block_index,
            "start": start,
            "end": end,
            "speaker_id": speaker_id,
            "role": role["role"],
            "voice_name": role.get("voice_name") or narrator_voice,
        })

    cursor = 0
    for turn in sorted(turns, key=lambda item: (item["start"], item["end"])):
        start, end = int(turn["start"]), int(turn["end"])
        if start < cursor:
            raise MultiVoicePlanError(
                f"cast turns overlap in block {block_index}"
            )
        append_part(cursor, start, NARRATOR_ID)
        speaker_id = turn.get("speaker_id")
        if (
            turn.get("status") != "attributed"
            or speaker_id not in active_characters
            or speaker_id == NARRATOR_ID
        ):
            speaker_id = NARRATOR_ID
        append_part(start, end, speaker_id)
        cursor = end
    append_part(cursor, len(text), NARRATOR_ID)
    return parts


def compile_chunks(
    blocks: list[dict[str, Any]], cast_plan: dict[str, Any]
) -> list[dict[str, Any]]:
    """Compile exact source slices into role-aware speech chunks."""
    validate_cast_anchors(cast_plan, blocks)
    roles = required_voice_roles(cast_plan)
    missing = [role["display_name"] for role in roles if not role.get("voice_name")]
    if missing:
        raise MultiVoicePlanError(
            "assign a voice to: " + ", ".join(missing)
        )

    active_characters = {
        NARRATOR_ID: {
            "id": NARRATOR_ID,
            "role": "narrator",
            "voice_name": roles[0]["voice_name"],
        }
    }
    for character in cast_plan.get("characters", []):
        if not character.get("invalid") and int(character.get("turn_count", 0)) > 0:
            active_characters[character["id"]] = character

    turns_by_block: dict[int, list[dict[str, Any]]] = {}
    for turn in cast_plan.get("turns", []):
        turns_by_block.setdefault(int(turn["block_index"]), []).append(turn)

    chunks: list[dict[str, Any]] = []
    for block_index, block in enumerate(blocks):
        text = str(block.get("text", ""))
        if not text.strip():
            continue
        block_hash = block_text_hash(block)
        block_type = str(block.get("type", "body"))
        parts = _role_parts(
            block_index,
            text,
            turns_by_block.get(block_index, []),
            active_characters,
        )
        for part_number, part in enumerate(parts):
            ceiling = (
                DIALOGUE_CHAR_CEILING
                if part["role"] == "character"
                else NARRATION_CHAR_CEILING
            )
            for start, end in pack_source_span(
                text, part["start"], part["end"], ceiling
            ):
                entry = {
                    "text": normalize_quoted_ellipsis(text[start:end].strip()),
                    "speaker_id": part["speaker_id"],
                    "role": part["role"],
                    "voice_name": part["voice_name"],
                    "block_index": block_index,
                    "block_type": block_type,
                    "source_start": start,
                    "source_end": end,
                    "block_sha256": block_hash,
                    "_part_number": part_number,
                }
                for key in ("source_page", "source_page_end"):
                    if key in block:
                        entry[key] = block[key]
                chunks.append(entry)

    validate_compiled_chunks(chunks, blocks)
    return chunks


def build_plan(
    blocks: list[dict[str, Any]],
    cast_plan: dict[str, Any],
    profile: dict[str, int],
) -> list[dict[str, Any]]:
    """Add assembly pauses and chapter metadata to compiled role chunks."""
    chunks = compile_chunks(blocks, cast_plan)
    by_block: dict[int, list[dict[str, Any]]] = {}
    for entry in chunks:
        by_block.setdefault(entry["block_index"], []).append(entry)

    for block_index, entries in by_block.items():
        is_heading = entries[0]["block_type"] == "heading"
        last_source_block = block_index == len(blocks) - 1
        for index, entry in enumerate(entries):
            entry["before_ms"] = (
                profile["heading_before_ms"]
                if is_heading and index == 0
                else 0
            )
            if index == len(entries) - 1:
                entry["after_ms"] = (
                    (profile["heading_after_ms"] if is_heading else 0)
                    + (0 if last_source_block else profile["block_gap_ms"])
                )
            elif entry["_part_number"] == entries[index + 1]["_part_number"]:
                entry["after_ms"] = profile["gap_ms"]
            else:
                # Chatterbox contributes about 380 ms of padding at every call
                # boundary.  Do not add another explicit sentence gap merely
                # because the reference voice changes inside one paragraph.
                entry["after_ms"] = 0
            if is_heading and index == 0:
                entry["heading"] = normalize_quoted_ellipsis(
                    str(blocks[block_index].get("text", "")).strip()
                )
            entry.pop("_part_number", None)
    return chunks


def validate_compiled_chunks(
    chunks: list[dict[str, Any]], blocks: list[dict[str, Any]]
) -> None:
    """Prove that chunks are ordered canonical slices and preserve all text."""
    by_block: dict[int, list[dict[str, Any]]] = {}
    for entry in chunks:
        block_index = entry.get("block_index")
        if not isinstance(block_index, int) or not 0 <= block_index < len(blocks):
            raise MultiVoicePlanError("multi-voice chunk has an invalid block index")
        by_block.setdefault(block_index, []).append(entry)

    for block_index, block in enumerate(blocks):
        text = str(block.get("text", ""))
        entries = by_block.get(block_index, [])
        cursor = 0
        recovered: list[str] = []
        for entry in entries:
            start, end = entry.get("source_start"), entry.get("source_end")
            if (
                not isinstance(start, int)
                or not isinstance(end, int)
                or not 0 <= start < end <= len(text)
                or start < cursor
            ):
                raise MultiVoicePlanError(
                    f"multi-voice chunks are not ordered in block {block_index}"
                )
            if entry.get("block_sha256") != block_text_hash(block):
                raise MultiVoicePlanError(
                    f"multi-voice chunk hash mismatch in block {block_index}"
                )
            source_slice = text[start:end].strip()
            if entry.get("text") != normalize_quoted_ellipsis(source_slice):
                raise MultiVoicePlanError(
                    f"multi-voice chunk rewrites source text in block {block_index}"
                )
            if not entry.get("voice_name"):
                raise MultiVoicePlanError("multi-voice chunk has no assigned voice")
            recovered.append(re.sub(r"\s+", "", text[start:end]))
            cursor = end
        if "".join(recovered) != re.sub(r"\s+", "", text):
            raise MultiVoicePlanError(
                f"multi-voice chunks do not preserve block {block_index}"
            )


def group_indices_by_voice(
    plan: list[dict[str, Any]], indices: Iterable[int], default_voice_path: str
) -> list[tuple[str, list[int]]]:
    """Stable generation groups: one conditioning pass per reference voice."""
    groups: OrderedDict[str, list[int]] = OrderedDict()
    for index in indices:
        voice_path = str(plan[index].get("voice_path") or default_voice_path)
        groups.setdefault(voice_path, []).append(index)
    return list(groups.items())
