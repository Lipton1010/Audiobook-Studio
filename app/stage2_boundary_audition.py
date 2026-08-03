"""Stage 2 audition: do the recovered paragraph boundaries actually sound
better, and does the Stage 1 dialogue profile survive on SHORT turns?

Runs in the BASE env (needs fitz; the chatterbox env has no PyMuPDF). It only
writes the private plan JSON. Rendering and blinding stay with the validated
stage0_narration_audition.py harness in the chatterbox env, which consumes this
plan unchanged.

WHY THREE ARMS, and what each comparison isolates:

  P   production today. The passage packed by the real narrate_worker.pack_text
      exactly as it is packed now, when these paragraphs are fused into one
      page-sized block, with neutral parameters throughout.
  B   the extraction fix only. Split at the recovered paragraph boundaries,
      parameters still neutral everywhere.
  BD  the extraction fix plus Stage 1's finding. Identical to B in
      segmentation, seeds, spoken text and pauses; the ONLY difference is that
      a segment which is a clean dialogue turn gets exaggeration 0.7 /
      cfg_weight 0.35 instead of the neutral defaults.

  P vs B   isolates segmentation, parameters held neutral in both.
  B vs BD  isolates delivery parameters, segmentation held identical.
  P vs BD  the whole proposed change against what the owner has heard.

Stage 0 and Stage 1 both used a 480-character turn, which sits in the top 0.4%
of turns in this book. Stage 2 deliberately targets the COMMON case: a run of
short exchanges, which is the case no experiment has touched.

No book text is stored in this file or printed to the console. The passage
lives only in the gitignored private plan.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
APP = REPO / "app"

BASE_SEED = 20260730
FADE_MS = 30
LOUDNESS_TARGET_LUFS = -21.0

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

QO, QC = "“", "”"


class _Stub:
    """narrate_worker imports torch/chatterbox at module level; pack_text and
    build_plan are pure stdlib, so stub the heavy modules to reach them from
    the base env without pulling in the TTS stack."""

    def __getattr__(self, name):
        return _Stub()

    def __call__(self, *a, **k):
        return _Stub()


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_json_new(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
        fh.write("\n")


def _is_clean_turn(text: str) -> bool:
    """Exactly one complete quoted turn and nothing outside it."""
    s = text.strip()
    return (
        s.startswith(QO)
        and s.endswith(QC)
        and s.count(QO) == 1
        and s.count(QC) == 1
    )


def _locate_parts(source: str, parts: list[str]) -> list[tuple[int, int]]:
    """Same contract as the Stage 0 harness: spans must tile the source and
    rejoin to it exactly, so a segmentation cannot silently drop text."""
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
    source_start: int,
    source_end: int,
    segment_role: str,
    speaker_id: str,
    profile_name: str,
    pause_after_ms: int,
    params: dict[str, float],
) -> dict[str, Any]:
    return {
        "segment_id": segment_id,
        "source_span": {"start": source_start, "end": source_end},
        "canonical_text": canonical_text,
        # Stage 2 applies NO pronunciation alias in any arm, so an alias cannot
        # explain a preference the way it confounded Stage 0's A against C.
        "spoken_text": canonical_text,
        "segment_role": segment_role,
        "speaker_id": speaker_id,
        "delivery_profile_name": profile_name,
        "pause_before_ms": 0,
        "pause_after_ms": pause_after_ms,
        "pronunciation_aliases": [],
        "seed": BASE_SEED + source_start,
        "chatterbox_parameters": dict(params),
    }


def _select_passage(new_body, old_body, pack, args):
    """Pick a contiguous run of recovered paragraphs that is dialogue-dense,
    short-turn heavy, inside a SINGLE old block (so today's production really
    does fuse it), and about the requested length."""
    old_texts = [b["text"] for b in old_body]

    def inside_one_old_block(joined: str) -> bool:
        return any(joined in t for t in old_texts)

    if args.start_block is not None:
        start = args.start_block
        count = args.block_count
        run = [b["text"] for b in new_body[start:start + count]]
        joined = " ".join(run)
        if not inside_one_old_block(joined):
            raise ValueError(
                "the requested block run is not contained in a single old block, "
                "so Arm P would not be a faithful picture of production today"
            )
        return start, run, joined

    best = None
    for start in range(len(new_body)):
        run: list[str] = []
        for count in range(1, args.max_blocks + 1):
            if start + count > len(new_body):
                break
            run = [b["text"] for b in new_body[start:start + count]]
            joined = " ".join(run)
            if len(joined) > args.max_chars:
                break
            if len(joined) < args.min_chars:
                continue
            turns = [t for t in run if _is_clean_turn(t)]
            short_turns = [t for t in turns if len(t) <= 60]
            if len(turns) < args.min_turns:
                continue
            if not inside_one_old_block(joined):
                continue
            # prefer many clean turns, and specifically many SHORT ones, since
            # the short turn is the untested case
            score = (len(short_turns) * 2) + len(turns)
            if best is None or score > best[0]:
                best = (score, start, list(run), joined)
    if best is None:
        raise ValueError(
            "no candidate passage met the criteria; relax --min-turns or widen "
            "--min-chars/--max-chars"
        )
    return best[1], best[2], best[3]


def build(args) -> int:
    out_plan = Path(args.output_plan).resolve()
    if out_plan.exists():
        raise FileExistsError(out_plan)
    reference = Path(args.reference).resolve()
    if not reference.is_file():
        raise FileNotFoundError(reference)
    pdf = Path(args.pdf).resolve()
    if not pdf.is_file():
        raise FileNotFoundError(pdf)

    sys.path.insert(0, str(APP))
    for name in ("numpy", "soundfile", "perth", "chatterbox", "chatterbox.tts"):
        sys.modules.setdefault(name, _Stub())
    pt = _load(APP / "pipeline_text.py", "pt_stage2")
    nw = _load(APP / "narrate_worker.py", "nw_stage2")
    pack = nw.pack_text
    profile = nw.PAUSE_PROFILES["A"]
    gap_ms = int(profile["gap_ms"])
    block_gap_ms = int(profile["block_gap_ms"])

    # The OLD module is what production ran; the NEW one is the working tree.
    import subprocess
    import tempfile

    head_src = subprocess.check_output(
        ["git", "-C", str(REPO), "show", "HEAD:app/pipeline_text.py"])
    fd, head_path = tempfile.mkstemp(suffix="_head_pt.py")
    with os.fdopen(fd, "wb") as fh:
        fh.write(head_src)
    try:
        old_pt = _load(Path(head_path), "pt_stage2_head")
        old_blocks, _ = old_pt.extract_path_a(str(pdf), args.page_from, args.page_to)
        new_blocks, _ = pt.extract_path_a(str(pdf), args.page_from, args.page_to)
    finally:
        os.unlink(head_path)

    old_body = [b for b in old_blocks if b["type"] == "body"]
    new_body = [b for b in new_blocks if b["type"] == "body"]
    if len(new_body) <= len(old_body):
        raise ValueError(
            "the working tree did not recover more paragraphs than HEAD on this "
            "book, so there is no boundary difference to audition"
        )

    start, run, canonical_source = _select_passage(new_body, old_body, pack, args)

    # ---- Arm P: production today -------------------------------------------
    # These paragraphs are fused into one old block, so every gap inside the
    # passage is the intra-block 150 ms, never the 400 ms paragraph gap.
    p_parts = pack(canonical_source)
    p_spans = _locate_parts(canonical_source, p_parts)
    p_segments = []
    for i, (part, span) in enumerate(zip(p_parts, p_spans)):
        p_segments.append(
            _segment(
                segment_id=f"P-{i + 1:02d}",
                canonical_text=part,
                source_start=span[0],
                source_end=span[1],
                segment_role="mixed_body",
                speaker_id="unattributed",
                profile_name="current_neutral_defaults",
                pause_after_ms=gap_ms if i < len(p_parts) - 1 else 0,
                params=DEFAULT_PARAMS,
            )
        )

    # ---- Arms B and BD: recovered paragraph boundaries ----------------------
    # Same segmentation for both. Build the part list once so B and BD cannot
    # drift apart.
    struct_parts: list[str] = []
    struct_is_last_of_para: list[bool] = []
    struct_is_turn: list[bool] = []
    for para in run:
        sub = pack(para)
        if not sub:
            continue
        for j, chunk in enumerate(sub):
            struct_parts.append(chunk)
            struct_is_last_of_para.append(j == len(sub) - 1)
            # a paragraph that is one clean turn stays one dialogue call
            struct_is_turn.append(_is_clean_turn(para) and len(sub) == 1)
    struct_spans = _locate_parts(canonical_source, struct_parts)

    def build_structured(arm: str, expressive: bool):
        segs = []
        for i, (part, span) in enumerate(zip(struct_parts, struct_spans)):
            last_overall = i == len(struct_parts) - 1
            is_turn = struct_is_turn[i]
            if last_overall:
                after = 0
            elif struct_is_last_of_para[i]:
                after = block_gap_ms
            else:
                after = gap_ms
            if expressive and is_turn:
                params = CHARACTER_PARAMS
                pname = "restrained_expressive_dialogue_stage1"
            else:
                params = DEFAULT_PARAMS
                pname = "current_neutral_defaults"
            segs.append(
                _segment(
                    segment_id=f"{arm}-{i + 1:02d}",
                    canonical_text=part,
                    source_start=span[0],
                    source_end=span[1],
                    segment_role="dialogue" if is_turn else "narration",
                    speaker_id="character" if is_turn else "narrator",
                    profile_name=pname,
                    pause_after_ms=after,
                    params=params,
                )
            )
        return segs

    b_segments = build_structured("B", expressive=False)
    bd_segments = build_structured("BD", expressive=True)

    arms = {
        "P": {
            "description": (
                "production today: recovered paragraphs fused into one block, "
                "packed by the real narrate_worker.pack_text, neutral parameters"
            ),
            "segments": p_segments,
        },
        "B": {
            "description": (
                "recovered paragraph boundaries, neutral parameters everywhere "
                "(isolates the extraction fix)"
            ),
            "segments": b_segments,
        },
        "BD": {
            "description": (
                "Arm B segmentation, seeds and pauses with the Stage 1 restrained "
                "expressive profile on clean dialogue turns only"
            ),
            "segments": bd_segments,
        },
    }

    # ---- isolation proofs, not assumptions ---------------------------------
    for name, arm in arms.items():
        rebuilt = " ".join(s["canonical_text"] for s in arm["segments"])
        if rebuilt != canonical_source:
            raise ValueError(f"Arm {name} does not preserve canonical source")
    for left, right in zip(b_segments, bd_segments, strict=True):
        for field in ("seed", "spoken_text", "pause_before_ms", "pause_after_ms",
                      "source_span", "canonical_text"):
            if left[field] != right[field]:
                raise ValueError(
                    f"Arm BD diverges from Arm B on {field}; the parameter "
                    "isolation is broken"
                )
    changed = [
        i for i, (l, r) in enumerate(zip(b_segments, bd_segments))
        if l["chatterbox_parameters"] != r["chatterbox_parameters"]
    ]
    if not changed:
        raise ValueError(
            "Arm BD is identical to Arm B: the passage has no clean dialogue "
            "turn, so this passage cannot test the Stage 1 profile"
        )
    for s in p_segments + b_segments + bd_segments:
        if s["pronunciation_aliases"]:
            raise ValueError("Stage 2 must apply no pronunciation alias in any arm")
    all_neutral_p = all(
        s["chatterbox_parameters"] == DEFAULT_PARAMS for s in p_segments)
    all_neutral_b = all(
        s["chatterbox_parameters"] == DEFAULT_PARAMS for s in b_segments)
    if not (all_neutral_p and all_neutral_b):
        raise ValueError("Arms P and B must both be fully neutral to isolate boundaries")

    turn_lengths = sorted(len(s["canonical_text"]) for s in bd_segments
                          if s["segment_role"] == "dialogue")
    plan = {
        "schema_version": 4,
        "created_utc": _utc_now(),
        "authorship": "manual_stage2_no_llm",
        "scope": "private_gitignored_audition",
        "experiment": "isolate_paragraph_boundaries_then_dialogue_parameters_on_short_turns",
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
            "reference_name": reference.name,
            "reference_sha256": _sha256_file(reference),
        },
        "arm_order": ["P", "B", "BD"],
        "passage_provenance": {
            "pdf_name": pdf.name,
            "page_from": args.page_from,
            "page_to": args.page_to,
            "new_body_block_start_index": start,
            "new_body_block_count": len(run),
            "reproduce_with": f"--start-block {start} --block-count {len(run)}",
            "contained_in_a_single_old_block": True,
            "canonical_characters": len(canonical_source),
        },
        "manual_boundary_notes": {
            "P_vs_B_differs_only_in": "segmentation and the pauses it implies",
            "B_vs_BD_differs_only_in": "chatterbox_parameters on clean dialogue turns",
            "arm_P_caveat": (
                "P packs this span standalone. Production's exact cut points also "
                "depend on where the surrounding page-sized block began, so P is a "
                "faithful picture of production's BEHAVIOUR on this text, not a "
                "byte-exact replay of one job's chunk offsets."
            ),
            "targets_the_common_case": (
                "Stage 0 and Stage 1 both used a 480-character turn, top 0.4% of "
                "this book. This passage is short exchanges."
            ),
            "dialogue_segment_count": len(changed),
            "dialogue_turn_lengths": turn_lengths,
        },
        "arms": arms,
    }
    _write_json_new(out_plan, plan)

    print(f"wrote private stage 2 plan: {out_plan}")
    print(f"canonical sha256   : {plan['canonical_source_sha256']}")
    print(f"canonical chars    : {len(canonical_source)}")
    print(f"passage            : new body blocks [{start}..{start + len(run) - 1}] "
          f"({len(run)} paragraphs)")
    print(f"reproduce with     : --start-block {start} --block-count {len(run)}")
    print(f"reference sha256   : {plan['legacy_source']['reference_sha256']}")
    print(f"arm segment counts : P={len(p_segments)}  B={len(b_segments)}  "
          f"BD={len(bd_segments)}")
    print(f"clean dialogue turns in B/BD: {len(changed)}  "
          f"lengths {turn_lengths}")
    print(f"Arm P chunk lengths : {[len(s['canonical_text']) for s in p_segments]}")
    print(f"Arm B chunk lengths : {[len(s['canonical_text']) for s in b_segments]}")
    return 0


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--pdf", default=str(
        REPO / "source_pdfs" / "The Power of the Dog - Don Winslow.pdf"))
    p.add_argument("--page-from", type=int, default=5)
    p.add_argument("--page-to", type=int, default=818)
    p.add_argument("--reference", default=str(
        REPO / "samples" / "Voice_Sample" / "male_ref.wav"))
    p.add_argument("--output-plan", required=True)
    p.add_argument("--start-block", type=int, default=None,
                   help="explicit new-body block index; omit to auto-select")
    p.add_argument("--block-count", type=int, default=12)
    p.add_argument("--max-blocks", type=int, default=18)
    p.add_argument("--min-chars", type=int, default=550)
    p.add_argument("--max-chars", type=int, default=850)
    p.add_argument("--min-turns", type=int, default=5)
    p.set_defaults(handler=build)
    return p


def main() -> int:
    args = _parser().parse_args()
    return int(args.handler(args))


if __name__ == "__main__":
    raise SystemExit(main())
