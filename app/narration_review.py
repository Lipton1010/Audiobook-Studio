"""Local listening decisions bound to exact narration text, audio and ASR evidence."""

import hashlib
import json
from pathlib import Path

from vibevoice_plan import sha256_file
from vibevoice_quality import assess_narration as assess, numbered_heading_assessment, unit_assessment
from vibevoice_delivery import (spoken_text, project_units, receipt_matches_projection,
                               PROFILE as DELIVERY_PROFILE, INTACT_PROFILE)
from vibevoice_units import _validate_units, parent_quality, repair_units, repair_limits

FILENAME = "narration_review.json"
CANDIDATES_DIR = "review_units"


class ListeningRequired(RuntimeError):
    pass


def write(path, value):
    path = Path(path)
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)


def fingerprint(receipt):
    fields = [receipt.get(key) for key in ("identity", "text_sha256", "wav_sha256", "report_sha256")]
    if 'spoken_text_sha256' in receipt or 'render_policy_sha256' in receipt:
        fields.extend(receipt.get(key) for key in ('spoken_text_sha256', 'render_policy_sha256', 'render_text_sha256'))
    if 'render_model' in receipt:
        fields.append(receipt['render_model'])
    return hashlib.sha256(json.dumps(fields).encode()).hexdigest()


def approved(receipt, unit):
    return (receipt.get("identity") == unit["identity"]
            and receipt.get("text_sha256") == unit["text_sha256"]
            and receipt.get("listening_approval") == fingerprint(receipt)
            and receipt_matches_projection(receipt, unit)
            and not receipt.get("force_regenerate"))


def entries(job_dir):
    path = Path(job_dir) / FILENAME
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    return data["passages"] if "passages" in data else [data]


def save_entries(job_dir, passages):
    path = Path(job_dir) / FILENAME
    if passages:
        write(path, {"passages": passages})
    else:
        path.unlink(missing_ok=True)


def entry(job_dir, parent):
    return next((data for data in entries(job_dir) if data["parent"] == parent), None)


def record(job_dir, parent, units, candidates=()):
    passages = entries(job_dir)
    previous = next((data for data in passages if data["parent"] == parent), {})
    passages = [data for data in passages if data["parent"]["index"] != parent["index"]]
    passages.append({"parent": parent, "units": units, "candidates": sorted(set(candidates)),
                     "decisions": previous.get("decisions", {})})
    save_entries(job_dir, sorted(passages, key=lambda data: data["parent"]["index"]))


def hold(job_dir, parent, units, candidates=()):
    record(job_dir, parent, units, candidates)
    raise ListeningRequired(
        f"Passage {parent['index'] + 1} needs listening review after automatic retries. "
        "Completed audio is saved. Open Review audio to listen, accept a clip, or regenerate it.")


def clip_stem(job_dir, data, index):
    folder = CANDIDATES_DIR if index in data.get("candidates", []) else "units"
    return Path(job_dir) / "vibevoice_segments" / folder / f"seg_{index:06d}"


def audio_path(job_dir, index):
    data = next(data for data in entries(job_dir) if any(unit["index"] == index for unit in data["units"]))
    return clip_stem(job_dir, data, index).with_suffix(".wav")


def detail(job_dir, parent_index=None):
    job_dir = Path(job_dir)
    plan = json.loads((job_dir / "vibevoice_plan.json").read_text(encoding="utf-8"))
    passages = [data for data in entries(job_dir)
                if parent_index is None or data["parent"]["index"] == parent_index]
    items = [item for data in passages for item in _passage_items(job_dir, data, plan)]
    return {"passage_count": len(passages), "items": items,
            "unresolved_count": sum(item["decision"] is None for item in items)}


def _passage_items(job_dir, data, plan):
    parent = next((p for p in plan["passages"] if p["index"] == data["parent"]["index"]), None)
    if parent is None or parent != data["parent"]:
        raise ValueError("The narration plan changed. Resume to check the current text.")
    config_path = job_dir / 'vibevoice_config.json'
    config = json.loads(config_path.read_text(encoding='utf-8')) if config_path.exists() else {}
    recorded = _validate_units(parent, data['units'])
    boundary_policy = config.get('unit_boundary_policies', {}).get(parent['identity'], config.get('unit_boundary_policy', 'legacy_v1'))
    if boundary_policy in ('initials_v2', 'captions_v3', 'sentences_v4') or parent['identity'] in config.get('drama3_passage_unit_limits', {}):
        limits = repair_limits(parent, config)
        current = repair_units(parent, boundary_policy=boundary_policy, **limits)
        if [u['identity'] for u in recorded] != [u['identity'] for u in current]:
            raise ValueError('The unit boundaries changed. Prepare a selective migration before review.')
    units = project_units(recorded, parent, config)
    items = []
    # Only count individually passing, unapproved clips toward the residual
    # parent gate. Failed/missing clips have their own review/generation work.
    reports = {unit["unit_index"]: {"unit_index": unit["unit_index"], "transcript": unit.get("spoken_text", unit["text"])}
               for unit in units}
    failed = set()
    for unit in units:
        if not unit.get('spoken_text', unit['text']):
            continue
        stem = clip_stem(job_dir, data, unit["index"])
        receipt_path, wav = stem.with_suffix(".json"), stem.with_suffix(".wav")
        if not receipt_path.exists():
            if unit["index"] in data.get("candidates", []):
                raise ValueError("The saved review clip is missing.")
            continue  # Units not yet generated will be handled on resume.
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        if not receipt_matches_projection(receipt, unit):
            raise ValueError('The intended spoken text or delivery policy changed. Prepare a selective migration before review.')
        report_path = Path(receipt["quality_report"])
        if not report_path.resolve().is_relative_to(job_dir.resolve()):
            raise ValueError("The saved speech report is outside this job.")
        if (receipt.get("identity") != unit["identity"] or receipt.get("text_sha256") != unit["text_sha256"]
                or sha256_file(wav) != receipt.get("wav_sha256")
                or sha256_file(report_path) != receipt.get("report_sha256")):
            raise ValueError("Saved audio or text changed. Resume to check it again.")
        report = json.loads(report_path.read_text(encoding="utf-8"))
        if (report.get("unit_identity") != unit["identity"]
                or report.get("unit_text_sha256") != unit["text_sha256"]
                or report.get("audio_sha256") != receipt.get("wav_sha256")):
            raise ValueError("The speech report does not match this clip.")
        assessment = unit_assessment(unit, report)
        differences = [d for d in assessment["differences"] if not d.get("orthographic_equivalent")]
        token = fingerprint(receipt)
        decision = data.get("decisions", {}).get(str(unit["index"]), {})
        action = decision.get("action") if decision.get("fingerprint") == token else None
        if action is None and approved(receipt, unit):
            action = "accept"
        if action == "accept" and not approved(receipt, unit):
            action = None
        if action == "retry" and not receipt.get("force_regenerate"):
            action = None
        if not assessment["ok"] or receipt.get("listen_again"):
            failed.add(unit["index"])
        elif action not in ("accept", "retry"):
            reports[unit["unit_index"]]["transcript"] = assessment.get("comparison_transcript", report["transcript"])
        if not differences and assessment["ok"] and action is None and not receipt.get("listen_again"):
            continue
        items.append({"index": unit["index"], "number": unit["unit_index"] + 1,
                      "passage": parent["index"] + 1,
                      "expected": unit["text"], "heard": report["transcript"],
                      "spoken_expected": unit.get("spoken_text", spoken_text(unit["text"])),
                      "delivery_updated": receipt.get("render_profile") in (DELIVERY_PROFILE, INTACT_PROFILE),
                      "transcript_review": assessment.get("transcript_review"),
                      "differences": differences, "fingerprint": token, "decision": action})
    cumulative_failure = not parent_quality(parent, list(reports.values()), units=units)["ok"]
    return [dict(item, reason="clip" if item["index"] in failed else "passage")
            for item in items if item["decision"] is not None or item["index"] in failed or cumulative_failure]


def decide(job_dir, index, token, action):
    if action not in ("accept", "retry", "listen"):
        raise ValueError("Choose accept, retry, or listen again.")
    job_dir = Path(job_dir)
    item = next((item for item in detail(job_dir)["items"] if item["index"] == index), None)
    if item is None or item["fingerprint"] != token:
        raise ValueError("This clip changed. Reopen the review before deciding.")
    passages = entries(job_dir)
    data = next(data for data in passages if any(unit["index"] == index for unit in data["units"]))
    path = clip_stem(job_dir, data, index).with_suffix(".json")
    receipt = json.loads(path.read_text(encoding="utf-8"))
    receipt.pop("listening_approval", None)
    receipt.pop("force_regenerate", None)
    receipt.pop("listen_again", None)
    if action == "accept":
        receipt["listening_approval"] = token
        receipt.pop("needs_repair", None)
    elif action == "retry":
        receipt["force_regenerate"] = True
    else:
        receipt["listen_again"] = True
    if action in ("retry", "listen"):
        active = job_dir / "vibevoice_segments" / "units" / path.name
        if active != path and active.exists():
            saved = json.loads(active.read_text(encoding="utf-8"))
            if action == "retry":
                saved["force_regenerate"] = True
            else:
                saved.pop("force_regenerate", None)
            write(active, saved)
    write(path, receipt)
    decisions = data.setdefault("decisions", {})
    if action == "listen":
        decisions.pop(str(index), None)
    else:
        decisions[str(index)] = {"action": action, "fingerprint": token}
    save_entries(job_dir, passages)
    return detail(job_dir)
