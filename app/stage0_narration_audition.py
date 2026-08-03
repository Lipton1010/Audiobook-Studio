"""Run an isolated three-arm Chatterbox narration audition.

Private passage text belongs in a JSON plan under the gitignored Output tree.
This harness deliberately contains no book text and does not import or modify
production narration code.

The prepare command can recover the exact JSON input used by the older local
A/B prototype from a Codex JSONL record.  It verifies that recovered text
against the older text hashes, then writes a manual Stage 0 plan.  The render
command synthesizes every arm through the same fades and loudness path.  The
blind command copies the results to neutral filenames and writes the concealed
mapping beside them.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import random
import re
import secrets
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import perth
import pyloudnorm as pyln
import soundfile as sf
import torch


class _NoWatermark:
    """Compatibility shim required by the project's pinned perth package."""

    def apply_watermark(self, wav, sample_rate=None):
        return wav


perth.PerthImplicitWatermarker = _NoWatermark

from chatterbox.tts import ChatterboxTTS  # noqa: E402


FADE_MS = 30
LOUDNESS_TARGET_LUFS = -21.0
BASE_SEED = 20260730
SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z\"'‘“])")
LEGACY_SEGMENT_RE = re.compile(
    r"role\s*=\s*'(?P<role>(?:''|[^'])*)'\s+"
    r"text\s*=\s*'(?P<text>(?:''|[^'])*)'\s+"
    r"after_ms\s*=\s*(?P<after>\d+)",
    re.DOTALL,
)
COMMAND_JSON_RE = re.compile(r'command:(?P<json>"(?:\\.|[^"\\])*")', re.DOTALL)

DEFAULT_PARAMS = {
    "exaggeration": 0.5,
    "cfg_weight": 0.5,
    "temperature": 0.8,
    "repetition_penalty": 1.2,
    "min_p": 0.05,
    "top_p": 1.0,
}
CHARACTER_PARAMS = {
    "exaggeration": 0.7,
    "cfg_weight": 0.35,
    "temperature": 0.8,
    "repetition_penalty": 1.2,
    "min_p": 0.05,
    "top_p": 1.0,
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_text(value: str) -> str:
    return _sha256_bytes(value.encode("utf-8"))


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _write_json_new(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def _read_jsonl_record(path: Path, line_number: int) -> dict[str, Any]:
    if line_number < 1:
        raise ValueError("history line number must be at least 1")
    with path.open("r", encoding="utf-8") as handle:
        for current, line in enumerate(handle, start=1):
            if current == line_number:
                return json.loads(line)
    raise ValueError(f"history file has fewer than {line_number} lines")


def _recover_legacy_segments(
    history_path: Path,
    line_number: int,
    content_index: int,
) -> list[dict[str, Any]]:
    record = _read_jsonl_record(history_path, line_number)
    content = record.get("payload", {}).get("content", [])
    if not isinstance(content, list) or not 0 <= content_index < len(content):
        raise ValueError("history content index is out of range")
    wrapped = content[content_index].get("text")
    if not isinstance(wrapped, str):
        raise ValueError("selected history content item has no text")
    command_match = COMMAND_JSON_RE.search(wrapped)
    if not command_match:
        raise ValueError("selected history content does not contain a command string")
    command = json.loads(command_match.group("json"))
    recovered = []
    for match in LEGACY_SEGMENT_RE.finditer(command):
        recovered.append(
            {
                "role": match.group("role").replace("''", "'"),
                "text": match.group("text").replace("''", "'"),
                "after_ms": int(match.group("after")),
            }
        )
    if len(recovered) != 2:
        raise ValueError(f"expected two legacy segments, recovered {len(recovered)}")
    return recovered


def _production_pack(text: str, ceiling: int = 400) -> list[str]:
    """Local copy of the current production sentence packer for Arm A only."""

    sentences = [part.strip() for part in SENTENCE_SPLIT_RE.split(text.strip()) if part.strip()]
    chunks: list[str] = []
    current = ""
    for sentence in sentences:
        candidate = f"{current} {sentence}".strip() if current else sentence
        if len(candidate) <= ceiling:
            current = candidate
            continue
        if current:
            chunks.append(current)
        if len(sentence) > ceiling:
            buffer = ""
            for sub_part in re.split(r"(?<=[,;])\s+", sentence):
                sub_candidate = f"{buffer} {sub_part}".strip() if buffer else sub_part
                if len(sub_candidate) <= ceiling:
                    buffer = sub_candidate
                else:
                    if buffer:
                        chunks.append(buffer)
                    buffer = sub_part
            current = buffer
        else:
            current = sentence
    if current:
        chunks.append(current)
    return chunks


def _locate_parts(source: str, parts: list[str]) -> list[tuple[int, int]]:
    spans = []
    cursor = 0
    for part in parts:
        start = source.find(part, cursor)
        if start < 0:
            raise ValueError("could not locate a planned segment in canonical source")
        end = start + len(part)
        spans.append((start, end))
        cursor = end
    if " ".join(parts) != source:
        raise ValueError("planned segments do not reconstruct canonical source exactly")
    return spans


def _segment(
    *,
    segment_id: str,
    canonical_text: str,
    spoken_text: str,
    source_start: int,
    source_end: int,
    segment_role: str,
    speaker_id: str,
    profile_name: str,
    pause_before_ms: int,
    pause_after_ms: int,
    aliases: list[dict[str, Any]],
    params: dict[str, float],
) -> dict[str, Any]:
    return {
        "segment_id": segment_id,
        "source_span": {"start": source_start, "end": source_end},
        "canonical_text": canonical_text,
        "spoken_text": spoken_text,
        "segment_role": segment_role,
        "speaker_id": speaker_id,
        "delivery_profile_name": profile_name,
        "pause_before_ms": pause_before_ms,
        "pause_after_ms": pause_after_ms,
        "pronunciation_aliases": aliases,
        "seed": BASE_SEED + source_start,
        "chatterbox_parameters": dict(params),
    }


def _build_plan(
    legacy_segments: list[dict[str, Any]],
    legacy_report: dict[str, Any],
    dialogue_pauses_ms: list[int],
) -> dict[str, Any]:
    character = legacy_segments[0]["text"]
    narrator = legacy_segments[1]["text"]
    report_segments = legacy_report.get("segments", [])
    if len(report_segments) != 2:
        raise ValueError("legacy report does not contain two segments")
    for index, text in enumerate((character, narrator)):
        expected = report_segments[index].get("text_sha256")
        actual = _sha256_text(text)
        if expected != actual:
            raise ValueError(
                f"legacy segment {index} hash mismatch: expected {expected}, got {actual}"
            )

    canonical_source = f"{character} {narrator}"
    dialogue_parts = [
        part.strip() for part in SENTENCE_SPLIT_RE.split(character.strip()) if part.strip()
    ]
    if len(dialogue_pauses_ms) != len(dialogue_parts):
        raise ValueError(
            "manual dialogue pause count must equal the recovered dialogue sentence count "
            f"({len(dialogue_parts)})"
        )
    if dialogue_pauses_ms[-1] < 500:
        raise ValueError("final dialogue pause must clearly mark the narrator return")
    if character.lower().count("helluva") != 1:
        raise ValueError("expected exactly one canonical pronunciation alias target")

    arms: dict[str, dict[str, Any]] = {}

    baseline_parts = _production_pack(canonical_source)
    baseline_spans = _locate_parts(canonical_source, baseline_parts)
    baseline_segments = []
    for index, (part, span) in enumerate(zip(baseline_parts, baseline_spans, strict=True)):
        contains_character = span[0] < len(character)
        contains_narrator = span[1] > len(character) + 1
        role = "mixed_body" if contains_character and contains_narrator else "body"
        baseline_segments.append(
            _segment(
                segment_id=f"A-{index + 1:02d}",
                canonical_text=part,
                spoken_text=part,
                source_start=span[0],
                source_end=span[1],
                segment_role=role,
                speaker_id="unattributed",
                profile_name="current_neutral_defaults",
                pause_before_ms=0,
                pause_after_ms=150 if index < len(baseline_parts) - 1 else 0,
                aliases=[],
                params=DEFAULT_PARAMS,
            )
        )
    arms["A"] = {
        "description": "current production-equivalent packing and pause profile",
        "segments": baseline_segments,
    }

    structured_parts = dialogue_parts + [narrator]
    structured_spans = _locate_parts(canonical_source, structured_parts)
    for arm_name in ("B", "C"):
        structured_segments = []
        for index, (part, span) in enumerate(
            zip(structured_parts, structured_spans, strict=True)
        ):
            is_dialogue = index < len(dialogue_parts)
            spoken = part
            aliases: list[dict[str, Any]] = []
            if "helluva" in spoken.lower():
                spoken = re.sub("helluva", "hell of a", spoken, count=1, flags=re.IGNORECASE)
                aliases = [
                    {
                        "canonical_form": "helluva",
                        "spoken_form": "hell of a",
                        "occurrences": 1,
                        "speech_only": True,
                    }
                ]
            if arm_name == "C" and is_dialogue:
                profile_name = "restrained_distinct_character_hypothesis"
                params = CHARACTER_PARAMS
            else:
                profile_name = "current_neutral_defaults"
                params = DEFAULT_PARAMS
            structured_segments.append(
                _segment(
                    segment_id=f"{arm_name}-{index + 1:02d}",
                    canonical_text=part,
                    spoken_text=spoken,
                    source_start=span[0],
                    source_end=span[1],
                    segment_role="dialogue" if is_dialogue else "narration",
                    speaker_id="character_watson" if is_dialogue else "narrator",
                    profile_name=profile_name,
                    pause_before_ms=0,
                    pause_after_ms=dialogue_pauses_ms[index] if is_dialogue else 0,
                    aliases=aliases,
                    params=params,
                )
            )
        arms[arm_name] = {
            "description": (
                "manual speaker and sentence boundaries, spoken alias, and PCM pauses"
                if arm_name == "B"
                else "Arm B structure with one stable restrained character profile"
            ),
            "segments": structured_segments,
        }

    for arm_name, arm in arms.items():
        reconstructed = " ".join(segment["canonical_text"] for segment in arm["segments"])
        if reconstructed != canonical_source:
            raise ValueError(f"Arm {arm_name} does not preserve canonical source")

    return {
        "schema_version": 1,
        "created_utc": _utc_now(),
        "authorship": "manual_stage0_no_llm",
        "scope": "private_gitignored_audition",
        "canonical_source": canonical_source,
        "canonical_source_sha256": _sha256_text(canonical_source),
        "reference_requirements": {
            "same_reference_every_arm": True,
            "same_sample_rate_every_arm": True,
            "same_loudness_path_every_arm": True,
        },
        "rendering": {
            "base_seed": BASE_SEED,
            "per_segment_seed_rule": "base_seed + canonical source span start",
            "fade_ms": FADE_MS,
            "loudness_target_lufs": LOUDNESS_TARGET_LUFS,
            "output_subtype": "PCM_16",
        },
        "legacy_source": {
            "reference_name": legacy_report.get("reference_name"),
            "reference_sha256": legacy_report.get("reference_sha256"),
            "character_text_sha256": _sha256_text(character),
            "narrator_text_sha256": _sha256_text(narrator),
        },
        "manual_boundary_notes": {
            "dialogue_segments": len(dialogue_parts),
            "dialogue_pause_after_ms": dialogue_pauses_ms,
            "narrator_return_pause_ms": dialogue_pauses_ms[-1],
            "narrator_to_character_transition_directly_testable": False,
            "reason": "the recovered excerpt begins with the quoted character turn",
        },
        "arms": arms,
    }


def _prepare(args: argparse.Namespace) -> int:
    history_path = Path(args.history_jsonl).resolve()
    legacy_report_path = Path(args.legacy_report).resolve()
    output_plan = Path(args.output_plan).resolve()
    if output_plan.exists():
        raise FileExistsError(output_plan)
    legacy_segments = _recover_legacy_segments(
        history_path,
        args.history_line,
        args.content_index,
    )
    with legacy_report_path.open("r", encoding="utf-8") as handle:
        legacy_report = json.load(handle)
    pauses = [int(value) for value in args.dialogue_pauses_ms.split(",")]
    if any(value < 0 or value > 5000 for value in pauses):
        raise ValueError("manual pauses must be between 0 and 5000 ms")
    plan = _build_plan(legacy_segments, legacy_report, pauses)
    _write_json_new(output_plan, plan)
    print(f"wrote private plan: {output_plan}")
    print(f"canonical sha256: {plan['canonical_source_sha256']}")
    print(
        "arm segment counts: "
        + ", ".join(
            f"{name}={len(arm['segments'])}" for name, arm in plan["arms"].items()
        )
    )
    return 0


def _prepare_followup(args: argparse.Namespace) -> int:
    source_plan_path = Path(args.source_plan).resolve()
    output_plan_path = Path(args.output_plan).resolve()
    if output_plan_path.exists():
        raise FileExistsError(output_plan_path)
    with source_plan_path.open("r", encoding="utf-8") as handle:
        source_plan = json.load(handle)

    arm_a = json.loads(json.dumps(source_plan["arms"]["A"]))
    arm_c = json.loads(json.dumps(source_plan["arms"]["C"]))
    seed_offset = int(args.seed_offset)
    if seed_offset < 0:
        raise ValueError("follow-up seed offset must be non-negative")
    for arm in (arm_a, arm_c):
        for segment in arm["segments"]:
            segment["seed"] = int(segment["seed"]) + seed_offset
    dialogue_segments = [
        segment
        for segment in arm_c["segments"]
        if segment["segment_role"] == "dialogue"
    ]
    narrator_segments = [
        segment
        for segment in arm_c["segments"]
        if segment["segment_role"] == "narration"
    ]
    if not dialogue_segments or len(narrator_segments) != 1:
        raise ValueError("source Arm C does not have the expected dialogue and narrator shape")

    canonical_character = " ".join(
        segment["canonical_text"] for segment in dialogue_segments
    )
    spoken_character = " ".join(segment["spoken_text"] for segment in dialogue_segments)
    narrator_source = narrator_segments[0]
    aliases = [
        alias
        for segment in dialogue_segments
        for alias in segment["pronunciation_aliases"]
    ]
    character_start = int(dialogue_segments[0]["source_span"]["start"])
    character_end = int(dialogue_segments[-1]["source_span"]["end"])
    character_seed = int(dialogue_segments[0]["seed"])
    transition_ms = int(dialogue_segments[-1]["pause_after_ms"])
    if transition_ms != 850:
        raise ValueError(f"expected the established 850 ms narrator transition, got {transition_ms}")

    arm_d_segments = [
        _segment(
            segment_id="D-01",
            canonical_text=canonical_character,
            spoken_text=spoken_character,
            source_start=character_start,
            source_end=character_end,
            segment_role="dialogue",
            speaker_id="character_watson",
            profile_name="restrained_distinct_character_hypothesis",
            pause_before_ms=0,
            pause_after_ms=transition_ms,
            aliases=aliases,
            params=CHARACTER_PARAMS,
        ),
        _segment(
            segment_id="D-02",
            canonical_text=narrator_source["canonical_text"],
            spoken_text=narrator_source["spoken_text"],
            source_start=int(narrator_source["source_span"]["start"]),
            source_end=int(narrator_source["source_span"]["end"]),
            segment_role="narration",
            speaker_id="narrator",
            profile_name="current_neutral_defaults",
            pause_before_ms=0,
            pause_after_ms=0,
            aliases=[],
            params=DEFAULT_PARAMS,
        ),
    ]
    arm_d_segments[0]["seed"] = character_seed
    arm_d_segments[1]["seed"] = int(narrator_source["seed"])

    canonical_source = source_plan["canonical_source"]
    if " ".join(segment["canonical_text"] for segment in arm_d_segments) != canonical_source:
        raise ValueError("follow-up Arm D does not preserve canonical source")
    if " ".join(segment["canonical_text"] for segment in arm_a["segments"]) != canonical_source:
        raise ValueError("copied Arm A does not preserve canonical source")
    if " ".join(segment["canonical_text"] for segment in arm_c["segments"]) != canonical_source:
        raise ValueError("copied Arm C does not preserve canonical source")

    followup_plan = {
        "schema_version": 2,
        "created_utc": _utc_now(),
        "authorship": "manual_stage0_followup_no_llm",
        "scope": "private_gitignored_audition",
        "experiment": "isolate_continuous_character_turn_from_sentence_segmentation",
        "canonical_source": canonical_source,
        "canonical_source_sha256": source_plan["canonical_source_sha256"],
        "reference_requirements": source_plan["reference_requirements"],
        "rendering": {
            **source_plan["rendering"],
            "followup_seed_offset": seed_offset,
            "per_segment_seed_rule": (
                "original Stage 0 per-segment seed + follow-up seed offset"
            ),
        },
        "legacy_source": source_plan["legacy_source"],
        "arm_order": ["A", "C", "D"],
        "manual_boundary_notes": {
            "D_character_segments": 1,
            "D_narrator_segments": 1,
            "D_transition_ms": transition_ms,
            "D_pronunciation_alias_count": len(aliases),
            "purpose": (
                "test whether the stable profile works better when the complete "
                "character turn remains in one synthesis call"
            ),
        },
        "arms": {
            "A": arm_a,
            "C": arm_c,
            "D": {
                "description": (
                    "continuous corrected character turn with Arm C profile, then "
                    "neutral narrator after the established transition"
                ),
                "segments": arm_d_segments,
            },
        },
    }
    _write_json_new(output_plan_path, followup_plan)
    print(f"wrote private follow-up plan: {output_plan_path}")
    print(f"canonical sha256: {followup_plan['canonical_source_sha256']}")
    print("arm segment counts: A=2, C=6, D=2")
    return 0


def _prepare_stage1(args: argparse.Namespace) -> int:
    """Build the Stage 1 plan: D anchor, E parameter isolation, D2 seed repeat.

    Stage 0's follow-up ranked D above A above C, but D differed from A in BOTH
    the delivery parameters and the segmentation, so that run cannot say which
    one earned the preference.  Here Arm E is Arm D with the character turn's
    parameters reverted to the current neutral defaults and everything else held
    fixed, including the seeds, the spoken text, the alias and the pauses.  A
    preference between D and E is therefore attributable to the parameters
    alone.

    Arm D2 is Arm D with every seed shifted.  S3Gen is stochastic, so a
    preference between D and D2 measures how much of any ranking is run to run
    variation rather than a real difference between arms.
    """

    source_plan_path = Path(args.source_plan).resolve()
    output_plan_path = Path(args.output_plan).resolve()
    if output_plan_path.exists():
        raise FileExistsError(output_plan_path)
    seed_offset = int(args.seed_offset)
    if seed_offset <= 0:
        raise ValueError("stage 1 seed offset must be positive so Arm D2 differs from Arm D")
    with source_plan_path.open("r", encoding="utf-8") as handle:
        source_plan = json.load(handle)

    if "D" not in source_plan.get("arms", {}):
        raise ValueError("source plan has no Arm D to build Stage 1 from")
    arm_d = json.loads(json.dumps(source_plan["arms"]["D"]))
    dialogue = [s for s in arm_d["segments"] if s["segment_role"] == "dialogue"]
    narration = [s for s in arm_d["segments"] if s["segment_role"] == "narration"]
    if len(dialogue) != 1 or len(narration) != 1:
        raise ValueError(
            "Stage 1 expects Arm D to be exactly one dialogue call plus one narrator call, "
            f"got {len(dialogue)} dialogue and {len(narration)} narration"
        )
    if not dialogue[0]["pronunciation_aliases"]:
        raise ValueError("Arm D dialogue segment lost its pronunciation alias")

    arm_e = json.loads(json.dumps(arm_d))
    for segment in arm_e["segments"]:
        segment["segment_id"] = "E" + segment["segment_id"][1:]
        if segment["segment_role"] == "dialogue":
            segment["chatterbox_parameters"] = dict(DEFAULT_PARAMS)
            segment["delivery_profile_name"] = "current_neutral_defaults"
    arm_e["description"] = (
        "Arm D structure, seeds, alias and pauses with current neutral defaults "
        "on the character turn"
    )

    arm_d2 = json.loads(json.dumps(arm_d))
    for segment in arm_d2["segments"]:
        segment["segment_id"] = "D2" + segment["segment_id"][1:]
        segment["seed"] = int(segment["seed"]) + seed_offset
    arm_d2["description"] = (
        f"Arm D repeated with every seed shifted by {seed_offset} to measure "
        "run to run variation"
    )

    canonical_source = source_plan["canonical_source"]
    arms = {"D": arm_d, "E": arm_e, "D2": arm_d2}
    for name, arm in arms.items():
        reconstructed = " ".join(segment["canonical_text"] for segment in arm["segments"])
        if reconstructed != canonical_source:
            raise ValueError(f"Stage 1 Arm {name} does not preserve canonical source")

    # The whole point of Arm E is that exactly one thing changed.  Prove it here
    # rather than trusting the copy above.
    e_dialogue = [s for s in arm_e["segments"] if s["segment_role"] == "dialogue"][0]
    if e_dialogue["chatterbox_parameters"] == dialogue[0]["chatterbox_parameters"]:
        raise ValueError("Arm E must differ from Arm D on the character turn parameters")
    for left, right in zip(arm_d["segments"], arm_e["segments"], strict=True):
        for field in ("seed", "spoken_text", "pause_before_ms", "pause_after_ms", "source_span"):
            if left[field] != right[field]:
                raise ValueError(f"Arm E diverges from Arm D on {field}; isolation is broken")
    for left, right in zip(arm_d["segments"], arm_d2["segments"], strict=True):
        if left["chatterbox_parameters"] != right["chatterbox_parameters"]:
            raise ValueError("Arm D2 must keep Arm D's parameters; only seeds may change")
        if left["seed"] == right["seed"]:
            raise ValueError("Arm D2 seeds did not change")

    stage1_plan = {
        "schema_version": 3,
        "created_utc": _utc_now(),
        "authorship": "manual_stage1_no_llm",
        "scope": "private_gitignored_audition",
        "experiment": "isolate_delivery_parameters_and_measure_seed_variation",
        "canonical_source": canonical_source,
        "canonical_source_sha256": source_plan["canonical_source_sha256"],
        "reference_requirements": source_plan["reference_requirements"],
        "rendering": {
            **source_plan["rendering"],
            "stage1_seed_offset": seed_offset,
            "per_segment_seed_rule": (
                "Arm D and Arm E reuse the follow-up seeds unchanged; Arm D2 adds "
                "the stage 1 seed offset"
            ),
        },
        "legacy_source": source_plan["legacy_source"],
        "arm_order": ["D", "E", "D2"],
        "manual_boundary_notes": {
            "D_vs_E_differs_only_in": "chatterbox_parameters on the character turn",
            "D_vs_D2_differs_only_in": "per segment seed",
            "purpose": (
                "Stage 0 confounded delivery parameters with segmentation; this run "
                "separates them and bounds the stochastic noise floor"
            ),
        },
        "arms": arms,
    }
    _write_json_new(output_plan_path, stage1_plan)
    print(f"wrote private stage 1 plan: {output_plan_path}")
    print(f"canonical sha256: {stage1_plan['canonical_source_sha256']}")
    print("arm segment counts: D=2, E=2, D2=2")
    print(f"Arm D2 seed offset: {seed_offset}")
    return 0


def _seed_everything(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)


def _fade(wav: np.ndarray, sample_rate: int) -> np.ndarray:
    count = min(round(sample_rate * FADE_MS / 1000), len(wav) // 3)
    if count <= 0:
        return wav
    faded = wav.copy()
    faded[:count] *= np.linspace(0.0, 1.0, count, dtype=np.float32)
    faded[-count:] *= np.linspace(1.0, 0.0, count, dtype=np.float32)
    return faded


def _normalize_common_path(
    wav: np.ndarray,
    sample_rate: int,
    target_lufs: float,
) -> tuple[np.ndarray, dict[str, float]]:
    meter = pyln.Meter(sample_rate)
    input_lufs = float(meter.integrated_loudness(wav))
    normalized = pyln.normalize.loudness(wav, input_lufs, target_lufs).astype(np.float32)
    peak_before_safety = float(np.max(np.abs(normalized))) if len(normalized) else 0.0
    safety_scale = 1.0
    if peak_before_safety > 0.99:
        safety_scale = 0.99 / peak_before_safety
        normalized *= safety_scale
    output_lufs = float(meter.integrated_loudness(normalized))
    return normalized, {
        "input_integrated_lufs": round(input_lufs, 4),
        "target_integrated_lufs": target_lufs,
        "peak_before_safety_scale": round(peak_before_safety, 6),
        "safety_scale": round(safety_scale, 8),
        "output_integrated_lufs": round(output_lufs, 4),
    }


def _render_arm(
    model: ChatterboxTTS,
    arm_name: str,
    arm: dict[str, Any],
    reference: Path,
    canonical_source_sha256: str,
) -> tuple[np.ndarray, dict[str, Any]]:
    sample_rate = int(model.sr)
    assembled: list[np.ndarray] = []
    segment_reports = []
    for index, segment in enumerate(arm["segments"]):
        before_ms = int(segment["pause_before_ms"])
        after_ms = int(segment["pause_after_ms"])
        if before_ms:
            assembled.append(
                np.zeros(round(sample_rate * before_ms / 1000), dtype=np.float32)
            )
        seed = int(segment["seed"])
        _seed_everything(seed)
        params = segment["chatterbox_parameters"]
        print(
            f"arm={arm_name} segment={index + 1}/{len(arm['segments'])} "
            f"role={segment['segment_role']} chars={len(segment['spoken_text'])} seed={seed}",
            flush=True,
        )
        generated = model.generate(
            segment["spoken_text"],
            audio_prompt_path=str(reference),
            exaggeration=float(params["exaggeration"]),
            cfg_weight=float(params["cfg_weight"]),
            temperature=float(params["temperature"]),
            repetition_penalty=float(params["repetition_penalty"]),
            min_p=float(params["min_p"]),
            top_p=float(params["top_p"]),
        )
        wav = generated.squeeze().detach().cpu().numpy().astype(np.float32)
        wav = _fade(wav, sample_rate)
        assembled.append(wav)
        if after_ms:
            assembled.append(
                np.zeros(round(sample_rate * after_ms / 1000), dtype=np.float32)
            )
        segment_reports.append(
            {
                "segment_id": segment["segment_id"],
                "segment_role": segment["segment_role"],
                "speaker_id": segment["speaker_id"],
                "delivery_profile_name": segment["delivery_profile_name"],
                "canonical_text_sha256": _sha256_text(segment["canonical_text"]),
                "spoken_text_sha256": _sha256_text(segment["spoken_text"]),
                "canonical_characters": len(segment["canonical_text"]),
                "spoken_characters": len(segment["spoken_text"]),
                "pause_before_ms": before_ms,
                "pause_after_ms": after_ms,
                "pronunciation_alias_count": len(segment["pronunciation_aliases"]),
                "seed": seed,
                "chatterbox_parameters": dict(params),
                "speech_seconds": round(len(wav) / sample_rate, 4),
            }
        )
    combined = np.concatenate(assembled)
    normalized, loudness = _normalize_common_path(
        combined,
        sample_rate,
        LOUDNESS_TARGET_LUFS,
    )
    report = {
        "arm": arm_name,
        "description": arm["description"],
        "canonical_source_sha256": canonical_source_sha256,
        "sample_rate": sample_rate,
        "channels": 1,
        "subtype": "PCM_16",
        "fade_ms": FADE_MS,
        "duration_seconds": round(len(normalized) / sample_rate, 6),
        "common_loudness_path": loudness,
        "segments": segment_reports,
    }
    return normalized, report


def _render(args: argparse.Namespace) -> int:
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
    plan_path = Path(args.plan).resolve()
    reference = Path(args.reference).resolve()
    output_dir = Path(args.output_dir).resolve()
    if not plan_path.is_file():
        raise FileNotFoundError(plan_path)
    if not reference.is_file():
        raise FileNotFoundError(reference)
    output_dir.mkdir(parents=True, exist_ok=True)
    with plan_path.open("r", encoding="utf-8") as handle:
        plan = json.load(handle)
    arm_order = plan.get("arm_order", ["A", "B", "C"])
    if not isinstance(arm_order, list) or len(arm_order) != 3 or len(set(arm_order)) != 3:
        raise ValueError("plan arm_order must contain exactly three unique arm names")
    for arm_name in arm_order:
        if arm_name not in plan["arms"]:
            raise ValueError(f"plan arm_order references missing arm {arm_name}")
    expected_outputs = [output_dir / f"arm_{name}.wav" for name in arm_order]
    expected_outputs += [output_dir / "render_summary.json"]
    existing = [path for path in expected_outputs if path.exists()]
    if existing:
        raise FileExistsError(f"refusing to overwrite: {existing}")
    reference_hash = _sha256_file(reference)
    expected_reference_hash = plan.get("legacy_source", {}).get("reference_sha256")
    if reference_hash != expected_reference_hash:
        raise ValueError(
            f"reference hash mismatch: expected {expected_reference_hash}, got {reference_hash}"
        )
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is not available in the Chatterbox environment")

    print("loading Chatterbox from the existing offline cache...", flush=True)
    model = ChatterboxTTS.from_pretrained(device="cuda")
    summary: dict[str, Any] = {
        "created_utc": _utc_now(),
        "plan_path": str(plan_path),
        "plan_sha256": _sha256_file(plan_path),
        "reference_name": reference.name,
        "reference_sha256": reference_hash,
        "engine": "chatterbox-tts",
        "engine_version": importlib.metadata.version("chatterbox-tts"),
        "torch_version": torch.__version__,
        "cuda_runtime": torch.version.cuda,
        "gpu_name": torch.cuda.get_device_name(0),
        "offline_model_cache_required": True,
        "arms": {},
    }
    rendered: dict[str, np.ndarray] = {}
    reports: dict[str, dict[str, Any]] = {}
    for arm_name in arm_order:
        wav, report = _render_arm(
            model,
            arm_name,
            plan["arms"][arm_name],
            reference,
            plan["canonical_source_sha256"],
        )
        output_path = output_dir / f"arm_{arm_name}.wav"
        sf.write(str(output_path), wav, int(model.sr), subtype="PCM_16")
        report["output_name"] = output_path.name
        report["output_sha256"] = _sha256_file(output_path)
        rendered[arm_name] = wav
        reports[arm_name] = report
        summary["arms"][arm_name] = report

    if args.repeat_check_arm:
        repeat_arm = args.repeat_check_arm
        if repeat_arm not in arm_order:
            raise ValueError(f"repeat-check arm {repeat_arm} is not in this plan")
        repeat_wav, _repeat_report = _render_arm(
            model,
            f"{repeat_arm}-repeat-check",
            plan["arms"][repeat_arm],
            reference,
            plan["canonical_source_sha256"],
        )
        repeat_path = output_dir / f".arm_{repeat_arm}_repeat_check.wav"
        sf.write(str(repeat_path), repeat_wav, int(model.sr), subtype="PCM_16")
        repeat_hash = _sha256_file(repeat_path)
        summary["repeat_check"] = {
            "arm": repeat_arm,
            "method": (
                "same process, identical plan, per-segment reseeding immediately "
                "before generation"
            ),
            "first_sha256": reports[repeat_arm]["output_sha256"],
            "repeat_sha256": repeat_hash,
            "byte_identical": repeat_hash == reports[repeat_arm]["output_sha256"],
        }
        repeat_path.unlink()
    _write_json_new(output_dir / "render_summary.json", summary)
    print(f"wrote three non-blind arms and summary under: {output_dir}")
    if "repeat_check" in summary:
        print(
            f"repeat check Arm {summary['repeat_check']['arm']} byte-identical: "
            f"{summary['repeat_check']['byte_identical']}"
        )
    return 0


def _blind(args: argparse.Namespace) -> int:
    run_dir = Path(args.run_dir).resolve()
    blind_dir = run_dir / "blind"
    mapping_path = run_dir / "blind_mapping_private.json"
    if blind_dir.exists() or mapping_path.exists():
        raise FileExistsError("refusing to overwrite an existing blind set or mapping")
    plan_path = run_dir / "performance_plan_private.json"
    if not plan_path.is_file():
        raise FileNotFoundError(plan_path)
    with plan_path.open("r", encoding="utf-8") as handle:
        plan = json.load(handle)
    arm_order = plan.get("arm_order", ["A", "B", "C"])
    if not isinstance(arm_order, list) or len(arm_order) != 3 or len(set(arm_order)) != 3:
        raise ValueError("plan arm_order must contain exactly three unique arm names")
    arm_paths = {name: run_dir / f"arm_{name}.wav" for name in arm_order}
    for path in arm_paths.values():
        if not path.is_file():
            raise FileNotFoundError(path)

    shuffled_arms = list(arm_order)
    secrets.SystemRandom().shuffle(shuffled_arms)
    blind_dir.mkdir(parents=False, exist_ok=False)
    mapping_entries = []
    for index, arm_name in enumerate(shuffled_arms, start=1):
        blind_name = f"Stage0_Blind_{index:02d}.wav"
        blind_path = blind_dir / blind_name
        shutil.copy2(arm_paths[arm_name], blind_path)
        mapping_entries.append(
            {
                "blind_file": blind_name,
                "arm": arm_name,
                "sha256": _sha256_file(blind_path),
            }
        )
    mapping = {
        "created_utc": _utc_now(),
        "confidential_until_owner_listens": True,
        "entries": mapping_entries,
    }
    _write_json_new(mapping_path, mapping)
    print(f"wrote neutral blind samples under: {blind_dir}")
    print(f"wrote concealed mapping: {mapping_path}")
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    prepare = subparsers.add_parser("prepare")
    prepare.add_argument("--history-jsonl", required=True)
    prepare.add_argument("--history-line", type=int, required=True)
    prepare.add_argument("--content-index", type=int, required=True)
    prepare.add_argument("--legacy-report", required=True)
    prepare.add_argument("--output-plan", required=True)
    prepare.add_argument(
        "--dialogue-pauses-ms",
        default="250,220,260,240,850",
        help="manual pause after each recovered dialogue sentence",
    )
    prepare.set_defaults(handler=_prepare)

    followup = subparsers.add_parser("prepare-followup")
    followup.add_argument("--source-plan", required=True)
    followup.add_argument("--output-plan", required=True)
    followup.add_argument("--seed-offset", type=int, default=0)
    followup.set_defaults(handler=_prepare_followup)

    stage1 = subparsers.add_parser("prepare-stage1")
    stage1.add_argument("--source-plan", required=True)
    stage1.add_argument("--output-plan", required=True)
    stage1.add_argument("--seed-offset", type=int, required=True)
    stage1.set_defaults(handler=_prepare_stage1)

    render = subparsers.add_parser("render")
    render.add_argument("--plan", required=True)
    render.add_argument("--reference", required=True)
    render.add_argument("--output-dir", required=True)
    render.add_argument("--repeat-check-arm")
    render.set_defaults(handler=_render)

    blind = subparsers.add_parser("blind")
    blind.add_argument("--run-dir", required=True)
    blind.set_defaults(handler=_blind)
    return parser


def main() -> int:
    args = _parser().parse_args()
    return int(args.handler(args))


if __name__ == "__main__":
    raise SystemExit(main())
