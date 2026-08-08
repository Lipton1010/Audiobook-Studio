"""Local speaking-character discovery for Path A prose jobs.

The model is allowed to propose metadata only.  Extracted book text remains in
``blocks.json`` and is never copied into the persisted cast sidecar.  Every
model claim is anchored to deterministic quote spans, then validated against
the current block hashes before it can reach the UI.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
import time
from dataclasses import dataclass
from typing import Any, Callable, Iterable

import requests


SCHEMA_VERSION = 1
DEFAULT_NUM_CTX = 8192
DEFAULT_WINDOW_CHARS = 18000
CONFIDENCE_VALUES = {"high", "medium", "low"}
EVIDENCE_VALUES = {"explicit", "context", "alternation", "unknown"}
VOICE_TYPE_VALUES = {"male", "female", "unknown"}


class CastPlanError(ValueError):
    """A model response or persisted cast plan failed strict validation."""


class CharacterAnalysisCancelled(RuntimeError):
    """The owning job was canceled between local model requests."""


@dataclass(frozen=True)
class AnalysisWindow:
    start_block: int
    end_block: int
    target_turn_ids: tuple[str, ...]


def _json_bytes(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def block_text_hash(block: dict[str, Any]) -> str:
    return hashlib.sha256(str(block.get("text", "")).encode("utf-8")).hexdigest()


def source_hash(blocks: list[dict[str, Any]]) -> str:
    spoken = [
        {"type": block.get("type"), "text": block.get("text", "")}
        for block in blocks
    ]
    return hashlib.sha256(_json_bytes(spoken)).hexdigest()


def _is_straight_quote(text: str, index: int) -> bool:
    """Reject inch marks while retaining ordinary straight dialogue quotes."""
    prev = text[index - 1] if index else ""
    nxt = text[index + 1] if index + 1 < len(text) else ""
    return not (prev.isdigit() and (nxt.isdigit() or not nxt))


def find_dialogue_candidates(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Index double-quoted spans without deciding whether they are speech.

    Curly and straight quotes may remain open across paragraph blocks.  Each
    block-local span gets its own turn id and a shared group id so a later
    compiler can keep multi-paragraph speech connected without storing text in
    the sidecar.
    """
    turns: list[dict[str, Any]] = []
    open_kind: str | None = None
    group_number = 0
    active_group: str | None = None
    turn_number = 0

    for block_index, block in enumerate(blocks):
        if block.get("type") == "heading":
            continue
        text = str(block.get("text", ""))
        if not text:
            continue
        segment_start = 0 if open_kind else None
        i = 0
        while i < len(text):
            ch = text[i]
            if open_kind is None:
                if ch == "“" or (ch == '"' and _is_straight_quote(text, i)):
                    open_kind = "curly" if ch == "“" else "straight"
                    group_number += 1
                    active_group = f"group_{group_number:06d}"
                    segment_start = i
            else:
                closes = (open_kind == "curly" and ch == "”") or (
                    open_kind == "straight" and ch == '"' and _is_straight_quote(text, i)
                )
                if closes:
                    turn_number += 1
                    turns.append(
                        _turn_record(
                            block, block_index, int(segment_start or 0), i + 1,
                            turn_number, active_group, continues=False,
                        )
                    )
                    open_kind = None
                    active_group = None
                    segment_start = None
            i += 1
        if open_kind is not None and segment_start is not None:
            turn_number += 1
            turns.append(
                _turn_record(
                    block, block_index, int(segment_start), len(text),
                    turn_number, active_group, continues=True,
                )
            )
            segment_start = 0

    return turns


def _turn_record(
    block: dict[str, Any],
    block_index: int,
    start: int,
    end: int,
    turn_number: int,
    group_id: str | None,
    *,
    continues: bool,
) -> dict[str, Any]:
    return {
        "id": f"turn_{turn_number:06d}",
        "group_id": group_id or f"group_{turn_number:06d}",
        "block_index": block_index,
        "start": start,
        "end": end,
        "block_sha256": block_text_hash(block),
        "source_page": block.get("source_page"),
        "source_page_end": block.get("source_page_end"),
        "continues": bool(continues),
    }


def build_windows(
    blocks: list[dict[str, Any]],
    turns: list[dict[str, Any]],
    char_limit: int = DEFAULT_WINDOW_CHARS,
) -> list[AnalysisWindow]:
    """Build non-overlapping target windows; rendering adds context blocks."""
    if char_limit < 1000:
        raise ValueError("character analysis window must be at least 1000 characters")
    turns_by_block: dict[int, list[str]] = {}
    for turn in turns:
        turns_by_block.setdefault(int(turn["block_index"]), []).append(str(turn["id"]))

    if not turns:
        return []
    windows: list[AnalysisWindow] = []
    start = min(turns_by_block)
    chars = 0
    targets: list[str] = []
    for block_index in range(start, len(blocks)):
        block = blocks[block_index]
        block_chars = len(str(block.get("text", ""))) + 32
        if block_index > start and targets and chars + block_chars > char_limit:
            windows.append(AnalysisWindow(start, block_index, tuple(targets)))
            start = block_index
            chars = 0
            targets = []
        elif block_index > start and not targets and chars + block_chars > char_limit:
            # A long narration-only gap carries no discovery targets.  Keep at
            # most one bounded window of it as context for the next quotation.
            start = block_index
            chars = 0
        chars += block_chars
        targets.extend(turns_by_block.get(block_index, ()))
    if targets:
        windows.append(AnalysisWindow(start, len(blocks), tuple(targets)))
    return windows


def _render_window(
    blocks: list[dict[str, Any]],
    turns: list[dict[str, Any]],
    window: AnalysisWindow,
) -> str:
    by_block: dict[int, list[dict[str, Any]]] = {}
    target_ids = set(window.target_turn_ids)
    for turn in turns:
        if turn["id"] in target_ids:
            by_block.setdefault(int(turn["block_index"]), []).append(turn)

    rendered: list[str] = []
    context_start = max(0, window.start_block - 2)
    context_end = min(len(blocks), window.end_block + 2)
    for block_index in range(context_start, context_end):
        block = blocks[block_index]
        text = str(block.get("text", ""))
        for turn in sorted(by_block.get(block_index, ()), key=lambda item: item["start"], reverse=True):
            start, end = int(turn["start"]), int(turn["end"])
            text = (
                text[:start]
                + f"<TURN id=\"{turn['id']}\">"
                + text[start:end]
                + "</TURN>"
                + text[end:]
            )
        page = block.get("source_page")
        rendered.append(f"[BLOCK {block_index} PAGE {page if page is not None else '?'}] {text}")
    return "\n".join(rendered)


def _normal_name(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()


def _stable_character_id(display_name: str) -> str:
    normal = _normal_name(display_name) or "speaker"
    slug = re.sub(r"\s+", "_", normal)[:36]
    digest = hashlib.sha1(normal.encode("utf-8")).hexdigest()[:8]
    return f"char_{slug}_{digest}"


def _voice_type(value: Any) -> str:
    """Normalize the small, casting-only voice presentation vocabulary."""
    if value in (None, ""):
        return "unknown"
    normalized = str(value).strip().casefold()
    if normalized not in VOICE_TYPE_VALUES:
        raise CastPlanError(
            "voice type must be one of: female, male, unknown"
        )
    return normalized


def _merge_voice_types(first: Any, second: Any) -> str:
    """Prefer explicit agreement; conflicting model evidence stays unknown."""
    first_type = _voice_type(first)
    second_type = _voice_type(second)
    if first_type == "unknown":
        return second_type
    if second_type == "unknown" or first_type == second_type:
        return first_type
    return "unknown"


def _merge_character_candidates(
    raw_characters: Iterable[dict[str, Any]], valid_turn_ids: set[str]
) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    keys: list[set[str]] = []
    for raw in raw_characters:
        name = str(raw.get("display_name", "")).strip()
        if not name:
            continue
        aliases = [str(item).strip() for item in raw.get("aliases", []) if str(item).strip()]
        candidate_keys = {_normal_name(name), *(_normal_name(alias) for alias in aliases)} - {""}
        evidence = [
            str(item) for item in raw.get("evidence_turn_ids", [])
            if str(item) in valid_turn_ids
        ]
        if not evidence:
            raise CastPlanError(
                f"character candidate {name!r} has no valid anchored turn evidence"
            )
        voice_type = _voice_type(raw.get("voice_type"))
        match = next((index for index, known in enumerate(keys) if known & candidate_keys), None)
        if match is None:
            merged.append({
                "id": _stable_character_id(name),
                "role": "character",
                "display_name": name,
                "aliases": sorted(set(aliases), key=str.casefold),
                "evidence_turn_ids": sorted(set(evidence)),
                "turn_count": 0,
                "confidence_counts": {"high": 0, "medium": 0, "low": 0},
                "voice_type": voice_type,
                "voice_name": None,
                "invalid": False,
                "user_edited": False,
            })
            keys.append(set(candidate_keys))
        else:
            item = merged[match]
            all_aliases = set(item["aliases"]) | set(aliases)
            if _normal_name(name) != _normal_name(item["display_name"]):
                all_aliases.add(name)
            item["aliases"] = sorted(all_aliases, key=str.casefold)
            item["evidence_turn_ids"] = sorted(
                set(item["evidence_turn_ids"]) | set(evidence)
            )
            item["voice_type"] = _merge_voice_types(
                item.get("voice_type"), voice_type
            )
            keys[match].update(candidate_keys)
    return merged


class OllamaJSONClient:
    def __init__(
        self,
        generate_url: str,
        model: str,
        *,
        num_ctx: int = DEFAULT_NUM_CTX,
        timeout: int = 900,
        session: requests.Session | None = None,
    ) -> None:
        self.generate_url = generate_url
        self.model = model
        self.num_ctx = int(num_ctx)
        self.timeout = int(timeout)
        self.session = session or requests.Session()

    def call_json(self, prompt: str) -> dict[str, Any]:
        last_error: Exception | None = None
        repair = ""
        for attempt in range(2):
            payload = {
                "model": self.model,
                "prompt": prompt + repair,
                "stream": False,
                "format": "json",
                "think": False,
                "keep_alive": "10m",
                "options": {"temperature": 0, "num_ctx": self.num_ctx},
            }
            response = self.session.post(
                self.generate_url, json=payload, timeout=self.timeout
            )
            response.raise_for_status()
            try:
                result = json.loads(response.json()["response"])
                if not isinstance(result, dict):
                    raise CastPlanError("Ollama returned JSON that is not an object")
                return result
            except (KeyError, TypeError, json.JSONDecodeError, CastPlanError) as exc:
                last_error = exc
                repair = (
                    "\n\nYour previous reply was invalid. Return one JSON object only, "
                    "with exactly the requested keys and no markdown."
                )
        raise CastPlanError(f"Ollama returned invalid JSON twice: {last_error}")

    def unload(self) -> None:
        try:
            self.session.post(
                self.generate_url,
                json={"model": self.model, "keep_alive": 0},
                timeout=60,
            )
        except Exception:
            # Unloading is best effort.  The owning workflow logs model errors,
            # and a failed cleanup must not hide a valid cast report.
            pass


def _census_prompt(window_text: str, target_ids: Iterable[str]) -> str:
    ids = ", ".join(target_ids)
    return f"""You are identifying speaking roles in a legally owned novel for a local audiobook.
Return JSON only. Do not rewrite, summarize, or quote the book in your answer.

Target turn ids: {ids}

Return this shape:
{{"characters":[{{"display_name":"canonical name from the text","aliases":["title or alias"],"evidence_turn_ids":["turn_000001"],"voice_type":"male|female|unknown"}}]}}

Rules:
1. Include only people or personified beings who speak in a target TURN.
2. Do not include the narrator, authors, quoted titles, or merely mentioned people.
3. Merge titles and aliases when the surrounding text makes identity explicit.
4. Every character must cite at least one supplied target turn id.
5. If a speaker cannot be identified, omit that speaker rather than inventing a name.
6. Set voice_type to male or female only when names, pronouns, titles, or explicit nearby text support it. Otherwise use unknown.

LOCAL TEXT WINDOW:
{window_text}"""


def _attribution_prompt(
    window_text: str,
    target_ids: Iterable[str],
    characters: list[dict[str, Any]],
) -> str:
    cast = [
        {"id": item["id"], "name": item["display_name"], "aliases": item["aliases"]}
        for item in characters
    ]
    return f"""Attribute possible quotation spans in a legally owned novel.
Return JSON only. Do not rewrite, summarize, or quote the book in your answer.

Allowed cast:
{json.dumps(cast, ensure_ascii=False, separators=(',', ':'))}

Target turn ids: {', '.join(target_ids)}

Return this shape with exactly one entry per target id:
{{"attributions":[{{"turn_id":"turn_000001","is_speech":true,"speaker_id":"char_allowed_id_or_null","confidence":"high|medium|low","evidence_type":"explicit|context|alternation|unknown"}}]}}

Rules:
1. speaker_id must be one allowed cast id or null.
2. Use high only for explicit attribution or unambiguous naming.
3. Use medium for strong nearby context and low for conversational alternation.
4. If the quote is not spoken dialogue, set is_speech false and speaker_id null.
5. If it is speech but the speaker is uncertain or absent from the cast, use null and unknown.

LOCAL TEXT WINDOW:
{window_text}"""


def analyze_blocks(
    blocks: list[dict[str, Any]],
    client: Any,
    *,
    model_name: str,
    num_ctx: int = DEFAULT_NUM_CTX,
    window_chars: int = DEFAULT_WINDOW_CHARS,
    progress: Callable[[str, int, int], None] | None = None,
    cancelled: Callable[[], bool] | None = None,
    log: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    turns = find_dialogue_candidates(blocks)
    windows = build_windows(blocks, turns, window_chars) if turns else []
    valid_turn_ids = {str(turn["id"]) for turn in turns}
    raw_characters: list[dict[str, Any]] = []
    total_steps = len(windows) * 2

    try:
        for index, window in enumerate(windows, 1):
            _check_cancelled(cancelled)
            rendered = _render_window(blocks, turns, window)
            response = client.call_json(_census_prompt(rendered, window.target_turn_ids))
            candidates = response.get("characters", [])
            if not isinstance(candidates, list):
                raise CastPlanError("census response characters must be a list")
            raw_characters.extend(item for item in candidates if isinstance(item, dict))
            if progress:
                progress("census", index, total_steps)
            if log:
                log(f"character census window {index}/{len(windows)} complete")

        characters = _merge_character_candidates(raw_characters, valid_turn_ids)
        allowed_ids = {item["id"] for item in characters}
        attributions: dict[str, dict[str, Any]] = {}
        for index, window in enumerate(windows, 1):
            _check_cancelled(cancelled)
            rendered = _render_window(blocks, turns, window)
            response = client.call_json(
                _attribution_prompt(rendered, window.target_turn_ids, characters)
            )
            items = response.get("attributions", [])
            if not isinstance(items, list):
                raise CastPlanError("attribution response must contain a list")
            expected = set(window.target_turn_ids)
            seen: set[str] = set()
            for raw in items:
                if not isinstance(raw, dict):
                    raise CastPlanError("attribution entry must be an object")
                turn_id = str(raw.get("turn_id", ""))
                if turn_id not in expected or turn_id in seen:
                    raise CastPlanError(f"unexpected or duplicate attribution {turn_id!r}")
                seen.add(turn_id)
                is_speech = raw.get("is_speech")
                if not isinstance(is_speech, bool):
                    raise CastPlanError("attribution is_speech must be a JSON boolean")
                speaker_id = raw.get("speaker_id")
                if speaker_id in ("", "null", "unknown"):
                    speaker_id = None
                if speaker_id is not None and speaker_id not in allowed_ids:
                    raise CastPlanError(f"attribution references unknown speaker {speaker_id!r}")
                confidence = str(raw.get("confidence", "low")).lower()
                evidence = str(raw.get("evidence_type", "unknown")).lower()
                if confidence not in CONFIDENCE_VALUES:
                    raise CastPlanError(f"invalid confidence {confidence!r}")
                if evidence not in EVIDENCE_VALUES:
                    raise CastPlanError(f"invalid evidence type {evidence!r}")
                if not is_speech:
                    speaker_id = None
                attributions[turn_id] = {
                    "status": "not_speech" if not is_speech else (
                        "attributed" if speaker_id else "unknown"
                    ),
                    "speaker_id": speaker_id,
                    "confidence": confidence,
                    "evidence_type": evidence,
                }
            missing = expected - seen
            if missing:
                raise CastPlanError(
                    "attribution response omitted target ids: " + ", ".join(sorted(missing))
                )
            if progress:
                progress("attribution", len(windows) + index, total_steps)
            if log:
                log(f"speaker attribution window {index}/{len(windows)} complete")

        planned_turns: list[dict[str, Any]] = []
        for turn in turns:
            planned = dict(turn)
            planned.update(attributions.get(turn["id"], {
                "status": "unknown",
                "speaker_id": None,
                "confidence": "low",
                "evidence_type": "unknown",
            }))
            planned_turns.append(planned)

        _recount_characters(characters, planned_turns)
        characters = [item for item in characters if item["turn_count"] > 0]
        retained = {item["id"] for item in characters}
        for turn in planned_turns:
            if turn.get("speaker_id") not in retained:
                turn.update({
                    "status": "unknown" if turn["status"] != "not_speech" else "not_speech",
                    "speaker_id": None,
                    "confidence": "low",
                    "evidence_type": "unknown",
                })

        plan = {
            "schema_version": SCHEMA_VERSION,
            "source_sha256": source_hash(blocks),
            "model": model_name,
            "analysis": {
                "num_ctx": int(num_ctx),
                "window_chars": int(window_chars),
                "window_count": len(windows),
                "created_at": time.time(),
            },
            "narrator": {
                "id": "narrator",
                "role": "narrator",
                "display_name": "Narrator",
                "voice_type": "unknown",
                "voice_name": None,
            },
            "characters": characters,
            "turns": planned_turns,
            "edits": [],
        }
        plan["summary"] = summarize_cast_plan(plan)
        validate_cast_plan(plan, blocks)
        return plan
    finally:
        client.unload()


def _check_cancelled(cancelled: Callable[[], bool] | None) -> None:
    if cancelled and cancelled():
        raise CharacterAnalysisCancelled("character discovery canceled")


def _recount_characters(
    characters: list[dict[str, Any]], turns: list[dict[str, Any]]
) -> None:
    by_id = {item["id"]: item for item in characters}
    for item in characters:
        item["turn_count"] = 0
        item["confidence_counts"] = {"high": 0, "medium": 0, "low": 0}
    for turn in turns:
        speaker_id = turn.get("speaker_id")
        if speaker_id in by_id and turn.get("status") == "attributed":
            character = by_id[speaker_id]
            character["turn_count"] += 1
            confidence = turn.get("confidence", "low")
            character["confidence_counts"][confidence] += 1


def summarize_cast_plan(plan: dict[str, Any]) -> dict[str, int]:
    turns = plan.get("turns", [])
    characters = [item for item in plan.get("characters", []) if not item.get("invalid")]
    return {
        "speaking_characters": len(characters),
        "candidate_turns": len(turns),
        "attributed_turns": sum(1 for item in turns if item.get("status") == "attributed"),
        "unknown_turns": sum(1 for item in turns if item.get("status") == "unknown"),
        "non_speech_quotes": sum(1 for item in turns if item.get("status") == "not_speech"),
    }


def validate_cast_plan(plan: dict[str, Any], blocks: list[dict[str, Any]]) -> None:
    if plan.get("schema_version") != SCHEMA_VERSION:
        raise CastPlanError("unsupported cast plan schema")
    if plan.get("source_sha256") != source_hash(blocks):
        raise CastPlanError("cast plan source hash does not match blocks.json")
    characters = plan.get("characters")
    turns = plan.get("turns")
    if not isinstance(characters, list) or not isinstance(turns, list):
        raise CastPlanError("cast plan characters and turns must be lists")
    narrator = plan.get("narrator")
    if (
        not isinstance(narrator, dict)
        or narrator.get("id") != "narrator"
        or narrator.get("role") != "narrator"
    ):
        raise CastPlanError("cast plan narrator is missing or invalid")
    _validate_voice_name(narrator.get("voice_name"))
    _voice_type(narrator.get("voice_type"))
    ids = [str(item.get("id", "")) for item in characters]
    if any(not item for item in ids) or len(ids) != len(set(ids)):
        raise CastPlanError("cast character ids must be non-empty and unique")
    allowed = set(ids)
    evidence_by_character = {}
    for item in characters:
        name = str(item.get("display_name", "")).strip()
        aliases = item.get("aliases", [])
        evidence = item.get("evidence_turn_ids", [])
        if not name or len(name) > 120:
            raise CastPlanError("character names must be 1 to 120 characters")
        if not isinstance(aliases, list) or len(aliases) > 20:
            raise CastPlanError(f"character {name!r} has invalid aliases")
        if any(not str(alias).strip() or len(str(alias)) > 120 for alias in aliases):
            raise CastPlanError(f"character {name!r} has an invalid alias")
        _validate_voice_name(item.get("voice_name"))
        _voice_type(item.get("voice_type"))
        if not isinstance(evidence, list) or not evidence:
            raise CastPlanError(f"character {name!r} has no anchored evidence")
        evidence_by_character[item["id"]] = set(str(value) for value in evidence)
    seen_turns: set[str] = set()
    for turn in turns:
        turn_id = str(turn.get("id", ""))
        if not turn_id or turn_id in seen_turns:
            raise CastPlanError("cast turn ids must be non-empty and unique")
        seen_turns.add(turn_id)
        block_index = turn.get("block_index")
        if not isinstance(block_index, int) or not (0 <= block_index < len(blocks)):
            raise CastPlanError(f"turn {turn_id} has an invalid block index")
        block = blocks[block_index]
        text = str(block.get("text", ""))
        start, end = turn.get("start"), turn.get("end")
        if not isinstance(start, int) or not isinstance(end, int) or not (0 <= start < end <= len(text)):
            raise CastPlanError(f"turn {turn_id} has an invalid source span")
        if turn.get("block_sha256") != block_text_hash(block):
            raise CastPlanError(f"turn {turn_id} block hash does not match source")
        speaker_id = turn.get("speaker_id")
        if speaker_id is not None and speaker_id not in allowed:
            raise CastPlanError(f"turn {turn_id} references an unknown speaker")
        if turn.get("confidence") not in CONFIDENCE_VALUES:
            raise CastPlanError(f"turn {turn_id} has invalid confidence")
        if turn.get("evidence_type") not in EVIDENCE_VALUES:
            raise CastPlanError(f"turn {turn_id} has invalid evidence")
    for character_id, evidence in evidence_by_character.items():
        if not evidence <= seen_turns:
            raise CastPlanError(
                f"character {character_id} cites evidence outside the cast plan"
            )
    recounted = copy.deepcopy(characters)
    _recount_characters(recounted, turns)
    for stored, computed in zip(characters, recounted):
        if stored.get("turn_count") != computed.get("turn_count"):
            raise CastPlanError(f"character {stored['id']} turn count is stale")
        if stored.get("confidence_counts") != computed.get("confidence_counts"):
            raise CastPlanError(f"character {stored['id']} confidence counts are stale")
    expected = summarize_cast_plan(plan)
    if plan.get("summary") != expected:
        raise CastPlanError("cast plan summary is stale or inconsistent")


def _validate_voice_name(value: Any) -> None:
    if value is None:
        return
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > 120:
        raise CastPlanError("voice names must be 1 to 120 characters")


def apply_voice_assignment(
    plan: dict[str, Any],
    blocks: list[dict[str, Any]],
    role_id: str,
    voice_name: str | None,
) -> dict[str, Any]:
    """Assign or clear a local voice name and retain an audit entry."""
    updated = copy.deepcopy(plan)
    role_id = str(role_id or "")
    if voice_name is not None:
        voice_name = str(voice_name).strip() or None
    _validate_voice_name(voice_name)

    if role_id == "narrator":
        role = updated.get("narrator")
    else:
        role = next(
            (
                item
                for item in updated.get("characters", [])
                if item.get("id") == role_id and not item.get("invalid")
            ),
            None,
        )
    if not role:
        raise CastPlanError("cast role not found")

    previous = role.get("voice_name")
    role["voice_name"] = voice_name
    updated.setdefault("edits", []).append({
        "action": "assign_voice",
        "role_id": role_id,
        "previous_voice_name": previous,
        "voice_name": voice_name,
        "applied_at": time.time(),
    })
    validate_cast_plan(updated, blocks)
    return updated


def apply_voice_type(
    plan: dict[str, Any],
    blocks: list[dict[str, Any]],
    role_id: str,
    voice_type: str,
) -> dict[str, Any]:
    """Set a reviewed role's casting voice type and retain an audit entry."""
    updated = copy.deepcopy(plan)
    role_id = str(role_id or "")
    normalized = _voice_type(voice_type)
    if role_id == "narrator":
        role = updated.get("narrator")
    else:
        role = next(
            (
                item
                for item in updated.get("characters", [])
                if item.get("id") == role_id and not item.get("invalid")
            ),
            None,
        )
    if not role:
        raise CastPlanError("cast role not found")

    previous = _voice_type(role.get("voice_type"))
    role["voice_type"] = normalized
    role["user_edited"] = True
    updated.setdefault("edits", []).append({
        "action": "set_voice_type",
        "role_id": role_id,
        "previous_voice_type": previous,
        "voice_type": normalized,
        "applied_at": time.time(),
    })
    validate_cast_plan(updated, blocks)
    return updated


def apply_cast_edit(
    plan: dict[str, Any], blocks: list[dict[str, Any]], edit: dict[str, Any]
) -> dict[str, Any]:
    updated = copy.deepcopy(plan)
    action = str(edit.get("action", ""))
    character_id = str(edit.get("character_id", ""))
    by_id = {item["id"]: item for item in updated.get("characters", [])}
    if character_id not in by_id:
        raise CastPlanError("character not found")
    character = by_id[character_id]

    if action == "rename":
        name = str(edit.get("display_name", "")).strip()
        if not name or len(name) > 120:
            raise CastPlanError("character name must be 1 to 120 characters")
        old = character["display_name"]
        if _normal_name(old) != _normal_name(name):
            character["aliases"] = sorted(
                set(character.get("aliases", [])) | {old}, key=str.casefold
            )
        character["display_name"] = name
        character["user_edited"] = True
    elif action == "merge":
        target_id = str(edit.get("target_character_id", ""))
        if target_id not in by_id or target_id == character_id:
            raise CastPlanError("choose a different valid merge target")
        target = by_id[target_id]
        target["aliases"] = sorted(
            set(target.get("aliases", []))
            | set(character.get("aliases", []))
            | {character["display_name"]},
            key=str.casefold,
        )
        target["evidence_turn_ids"] = sorted(
            set(target.get("evidence_turn_ids", []))
            | set(character.get("evidence_turn_ids", []))
        )
        target["user_edited"] = True
        target["voice_type"] = _merge_voice_types(
            target.get("voice_type"), character.get("voice_type")
        )
        if not target.get("voice_name") and character.get("voice_name"):
            target["voice_name"] = character["voice_name"]
        for turn in updated["turns"]:
            if turn.get("speaker_id") == character_id:
                turn["speaker_id"] = target_id
        updated["characters"] = [
            item for item in updated["characters"] if item["id"] != character_id
        ]
    elif action == "invalidate":
        character["invalid"] = True
        character["user_edited"] = True
        character["voice_name"] = None
        for turn in updated["turns"]:
            if turn.get("speaker_id") == character_id:
                turn.update({
                    "status": "unknown",
                    "speaker_id": None,
                    "confidence": "low",
                    "evidence_type": "unknown",
                })
    else:
        raise CastPlanError("unsupported cast edit action")

    _recount_characters(updated["characters"], updated["turns"])
    updated.setdefault("edits", []).append({
        "action": action,
        "character_id": character_id,
        "target_character_id": edit.get("target_character_id"),
        "display_name": edit.get("display_name"),
        "applied_at": time.time(),
    })
    updated["summary"] = summarize_cast_plan(updated)
    validate_cast_plan(updated, blocks)
    return updated
