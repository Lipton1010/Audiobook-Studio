"""Generate the pending book, check it on GPU, then repair in bounded rounds.

Each GPU phase owns a separate process. Verified unit receipts and listening
decisions use the same validation and assembly code as the original worker.
"""

import argparse
import json
from pathlib import Path
import subprocess
import sys
import time

import vibevoice_worker as w
from vibevoice_quality import (PARAKEET_WORKFLOW as WORKFLOW, PARAKEET_MODEL_ID as MODEL_ID,
                               PARAKEET_REVISION as MODEL_REVISION, parakeet_setup_error)

PENDING_DIR = "pending_units"


def _read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _cancel(job):
    if w._cancelled(job):
        raise SystemExit(2)


def _basis(folder, unit):
    receipt = w._receipt_path(folder, unit["index"])
    return w.sha256_file(receipt) if receipt.exists() else None


def _pending(job, unit):
    folder = job / w.SEGMENTS_DIR / PENDING_DIR
    path = w._receipt_path(folder, unit["index"])
    if not path.exists():
        return None
    row = _read(path)
    stored_unit = {key: value for key, value in row["unit"].items() if key != "render_seed"}
    if (stored_unit != w._profiled_unit(unit)
            or row.get("basis") != _basis(job / w.SEGMENTS_DIR / w.UNITS_DIR, unit)):
        return None
    audio = Path(row["audio"])
    if row["status"] in {"ready", "checked"}:
        if not audio.is_file() or w.sha256_file(audio) != row.get("audio_sha256"):
            raise RuntimeError(f"Pending clip {unit['index']} changed; restore its saved audio before resuming.")
    return row


def _save(job, row):
    path = w._receipt_path(job / w.SEGMENTS_DIR / PENDING_DIR, row["unit"]["index"])
    w._write_json(path, row)


def _progress(job, plan, status, current=None):
    segments = job / w.SEGMENTS_DIR
    units_dir = segments / w.UNITS_DIR
    config = _read(job / "vibevoice_config.json")
    reviews = w.narration_review.entries(job)
    review_candidates = {index for review in reviews for index in review.get("candidates", [])}
    done = verified = generated = 0
    for parent in plan["passages"]:
        receipt = w._receipt_path(segments, parent["index"])
        saved = _read(receipt) if receipt.exists() else {}
        # Advisory counts read metadata; the scheduler verifies audio hashes.
        if saved.get("identity") == parent["identity"] and not saved.get("force_regenerate"):
            done += 1
            verified += len(parent["text"].split())
        for unit in w._units_for_parent(parent, config):
            pending = w._receipt_path(segments / PENDING_DIR, unit["index"])
            row = _read(pending) if pending.exists() else {}
            receipt = w._receipt_path(units_dir, unit["index"])
            saved = _read(receipt) if receipt.exists() else {}
            if (saved.get("identity") == unit["identity"] and not saved.get("force_regenerate")
                    or unit["index"] in review_candidates
                    or row.get("audio_sha256")):
                generated += len(unit["text"].split())
    w._progress(job, done, len(plan["passages"]), 0, status,
                current["unit"]["parent_index"] if current else None,
                current["attempt"] if current else None, metrics={
                    "verified_words": verified, "generated_words": generated,
                    "total_words": sum(len(p["text"].split()) for p in plan["passages"]),
                    "review_passages": len(reviews), "eta_sec": None,
                    "workflow": WORKFLOW,
                    "render_workers": config.get("render_workers", 1),
                })


def _run_phase(job, config, phase):
    _cancel(job)
    workers = config.get("render_workers", 1) if phase == "render" else 1
    if type(workers) is not int or workers not in (1, 2):
        raise ValueError("Render workers must be one or two")
    if phase == "render":
        plan, _ = w.load_plan(job)
        # Prepare this shared, immutable reference before either child opens it.
        w._prepare_voice(job, config, plan)
    print(f"Starting {phase} phase with {workers} worker(s); the previous GPU phase has exited.", flush=True)
    python = config["parakeet_python"] if phase == "check" else sys.executable
    command = [python, "-X", "utf8", str(Path(__file__).resolve()), str(job), "--phase", phase]
    processes = []
    try:
        for worker in range(workers):
            _cancel(job)
            processes.append(subprocess.Popen(command + ["--worker", str(worker), "--workers", str(workers)],
                             stdout=sys.stdout, stderr=sys.stderr,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)))
        while True:
            _cancel(job)
            codes = [process.poll() for process in processes]
            if 2 in codes:
                raise SystemExit(2)
            if any(code not in (None, 0) for code in codes):
                raise RuntimeError(f"The {phase} phase failed ({codes}); completed clips are saved. See the narration log.")
            if all(code == 0 for code in codes):
                break
            time.sleep(0.2)
    finally:
        for process in processes:
            if process.poll() is None:
                process.terminate()
        for process in processes:
            process.wait()


def _resolve(job, parent, units, config):
    """Commit checked candidates, retaining failed audio and exact review evidence."""
    folder = job / w.SEGMENTS_DIR / w.UNITS_DIR
    candidates_dir = folder.parent / w.narration_review.CANDIDATES_DIR
    review = w.narration_review.entry(job, parent)
    candidates = list(review.get("candidates", [])) if review else []
    for unit in units:
        row = _pending(job, unit)
        if not row or row["status"] != "checked":
            continue
        _cancel(job)
        assessment = w._reported_unit(row["unit"], row["report"])
        if assessment["ok"]:
            w._publish_unit(folder, row["unit"], Path(row["audio"]), row["report"], row["attempt"])
            if unit["index"] in candidates:
                candidates.remove(unit["index"])
                w.narration_review.record(job, parent, units, candidates)
        elif (row["attempt"] >= w._attempt_limit(row["unit"], config.get("quality_max_retries", 2))
              or assessment.get("transcript_review", {}).get("decision") == "uncertain"):
            w._publish_unit(candidates_dir, row["unit"], Path(row["audio"]), row["report"], row["attempt"])
            candidates.append(unit["index"])
            w.narration_review.record(job, parent, units, candidates)
        else:
            rejected = job / w.REJECTED_DIR / f"unit_{unit['index']:010d}_phase_{time.time_ns()}.wav"
            Path(row["audio"]).replace(rejected)
            row["status"] = "retry"
            _save(job, row)
            continue
        w._receipt_path(folder.parent / PENDING_DIR, unit["index"]).unlink(missing_ok=True)


def _schedule(job, plan, config):
    segments = job / w.SEGMENTS_DIR
    folder = segments / w.UNITS_DIR
    work = []
    for parent in plan["passages"]:
        _cancel(job)
        if w._valid_segment(segments, parent):
            continue
        units = w._units_for_parent(parent, config)
        _resolve(job, parent, units, config)
        if w._recover_parent_from_units(job, parent, units, folder, segments):
            continue
        review = w.narration_review.entry(job, parent)
        flagged = {item["index"] for item in w.narration_review.detail(job, parent["index"])["items"]
                   if item["decision"] != "retry"} if review else set()
        missing = [u for u in units if u["index"] not in flagged and not w._valid_unit(folder, u)]
        if not missing and not review:
            reports = [w._unit_report(folder, u) for u in units]
            exhausted = set()
            for unit in units:
                receipt = _read(w._receipt_path(folder, unit["index"]))
                if (w.narration_review.approved(receipt, unit)
                        or receipt.get("attempt", 0) >= w._attempt_limit(w._profiled_unit(unit), config.get("quality_max_retries", 2))):
                    exhausted.add(unit["unit_index"])
            try:
                repair = w.choose_repair_unit(units, reports, exclude=exhausted)
            except ValueError:
                w.narration_review.record(job, parent, units)
                continue
            receipt_path = w._receipt_path(folder, repair["index"])
            receipt = _read(receipt_path)
            receipt["needs_repair"] = True
            w._write_json(receipt_path, receipt)
            missing = [repair]
        for unit in missing:
            row = _pending(job, unit)
            if row and row["status"] in {"render", "ready"}:
                work.append(row)
                continue
            receipt_path = w._receipt_path(folder, unit["index"])
            receipt = _read(receipt_path) if receipt_path.exists() else {}
            previous = row["attempt"] if row else (0 if receipt.get("force_regenerate") else receipt.get("attempt", 0))
            profiled = w._profiled_unit(unit)
            if previous >= w._attempt_limit(profiled, config.get("quality_max_retries", 2)):
                raise RuntimeError(f"Clip {unit['index']} exhausted rendering attempts without reviewable audio. See the narration log.")
            row = {"unit": profiled, "attempt": previous + 1, "basis": _basis(folder, unit), "status": "render",
                   "audio": str(w._wav_path(segments / PENDING_DIR, unit["index"]))}
            _save(job, row)
            work.append(row)
    return work


def run_generate(job):
    job = Path(job).resolve()
    plan, config = w.load_plan(job)
    if config.get("workflow") != WORKFLOW:
        raise ValueError("The book is not configured for the Parakeet workflow")
    error = parakeet_setup_error(config.get("parakeet_python"), config.get("parakeet_model"))
    if error:
        raise RuntimeError(error)
    for folder in (job / w.SEGMENTS_DIR, job / w.REJECTED_DIR,
                   job / w.SEGMENTS_DIR / w.UNITS_DIR, job / w.SEGMENTS_DIR / PENDING_DIR,
                   job / w.SEGMENTS_DIR / w.narration_review.CANDIDATES_DIR):
        folder.mkdir(exist_ok=True)
    (job / w.ERROR_FILE).unlink(missing_ok=True)
    w.narration_review.save_entries(job, [r for r in w.narration_review.entries(job) if r["parent"] in plan["passages"]])
    review_phase(job, plan, config)
    while True:
        work = _schedule(job, plan, config)
        if not work:
            break
        if any(row["status"] == "render" for row in work):
            _progress(job, plan, "generating")
            _run_phase(job, config, "render")
        _progress(job, plan, "quality_check")
        _run_phase(job, config, "check")
        review_phase(job, plan, config)
    if w.narration_review.entries(job):
        _progress(job, plan, "awaiting_review")
        raise w.narration_review.ListeningRequired("Narration has finished. Review the flagged clips before assembling the audiobook.")
    _progress(job, plan, "complete")


def review_phase(job, plan, config):
    """Adjudicate saved checks after GPU processes exit, before any retry."""
    if not config.get("transcript_review"):
        return
    from transcript_review import Reviewer, needs_review
    rows = []
    for row in _phase_rows(job, plan, config, "checked"):
        unit = row["unit"]
        report = _read(row["report"])
        expected = unit.get("spoken_text", unit["text"])
        assessment = w.unit_assessment(unit, report)
        if (not unit.get("numbered_heading") and not report.get("transcript_review")
                and needs_review(expected, report["transcript"], assessment)):
            rows.append((row, report, expected))
    if not rows:
        return
    _cancel(job)
    w._assert_no_ocr()
    _progress(job, plan, "transcript_review", rows[0][0])
    with Reviewer() as reviewer:
        for row, report, expected in rows:
            _cancel(job)
            _progress(job, plan, "transcript_review", row)
            report["transcript_review"] = reviewer.review(expected, report["transcript"])
            _cancel(job)
            assessment = w.unit_assessment(row["unit"], report)
            if report["transcript_review"]["decision"] == "equivalent" and not assessment["ok"]:
                report["transcript_review"].update(
                    decision="uncertain", reason="The model suggested equivalence, but an added or missing span requires audio review.")
            # Preserve the original ASR report as well as its raw transcript.
            path = job / w.SEGMENTS_DIR / PENDING_DIR / f"review_{row['unit']['index']:06d}_{time.time_ns()}.json"
            w._write_json(path, report)
            row["report"] = str(path)
            _save(job, row)


def _phase_rows(job, plan, config, status, worker=0, workers=1):
    if type(workers) is not int or workers not in (1, 2) or not 0 <= worker < workers:
        raise ValueError("Invalid render worker assignment")
    units = [unit for parent in plan["passages"] for unit in w._units_for_parent(parent, config)]
    # Partition the fixed plan, never the shrinking list of unfinished clips.
    # A peer finishing a clip cannot shift another worker's ownership.
    return [row for position, unit in enumerate(units) if position % workers == worker
            and (row := _pending(job, unit)) and row["status"] == status]


def render_phase(job, plan, config, worker=0, workers=1):
    rows = _phase_rows(job, plan, config, "render", worker, workers)
    if not rows:
        return
    _cancel(job)
    w._assert_no_ocr()
    voice = w._prepare_voice(job, config, plan)
    torch, processor, model = w._load_model({**config, "render_workers": workers})
    size = w._batch_size(torch, config)
    folder = job / w.SEGMENTS_DIR / PENDING_DIR
    for offset in range(0, len(rows), size):
        _cancel(job)
        batch = rows[offset:offset + size]
        _progress(job, plan, "generating", batch[0])
        rendered = w._render_items(torch, processor, model, voice,
                                   [(row["unit"], row["attempt"]) for row in batch], config, folder)
        for row, (unit, attempt, temporary, error) in zip(batch, rendered):
            if error:
                if not w._recoverable_render_error(error):
                    raise error
                row["status"] = "retry"
                _save(job, row)
                continue
            _cancel(job)
            temporary.replace(row["audio"])
            row.update(unit=unit, status="ready", audio_sha256=w.sha256_file(row["audio"]))
            _save(job, row)
        _progress(job, plan, "generating", batch[-1])


def check_phase(job, plan, config):
    rows = _phase_rows(job, plan, config, "ready")
    if not rows:
        return
    _cancel(job)
    w._assert_no_ocr()
    import numpy as np
    import soundfile as sf
    import torch
    from math import gcd
    from scipy.signal import resample_poly
    from transformers import AutoModelForTDT, AutoProcessor

    torch.set_num_threads(4)
    torch.cuda.set_per_process_memory_fraction(0.85)
    processor = AutoProcessor.from_pretrained(config["parakeet_model"], local_files_only=True)
    model = AutoModelForTDT.from_pretrained(config["parakeet_model"], dtype=torch.float32, local_files_only=True).to("cuda").eval()

    def transcribe(batch):
        audio = []
        for row in batch:
            pcm, rate = sf.read(row["audio"], dtype="float32")
            if pcm.ndim == 2:
                pcm = pcm.mean(axis=1)
            if not len(pcm) or not np.isfinite(pcm).all():
                raise RuntimeError("Parakeet received empty or non-finite audio")
            if rate != 16000:
                factor = gcd(rate, 16000)
                pcm = resample_poly(pcm, 16000 // factor, rate // factor)
            audio.append(np.asarray(pcm, dtype=np.float32))
        inputs = processor(audio, sampling_rate=16000, return_tensors="pt", padding=True).to(model.device, dtype=model.dtype)
        with torch.inference_mode():
            generated = model.generate(**inputs)
        return processor.batch_decode(getattr(generated, "sequences", generated), skip_special_tokens=True)

    for offset in range(0, len(rows), 4):
        _cancel(job)
        batch = rows[offset:offset + 4]
        _progress(job, plan, "quality_check", batch[0])
        transcripts = w.bisect_cuda_oom(batch, transcribe, torch)
        if len(transcripts) != len(batch):
            raise RuntimeError("Parakeet did not return one transcript per clip")
        for row, transcript in zip(batch, transcripts):
            _cancel(job)
            unit = row["unit"]
            report = w.assess(unit.get("spoken_text", unit["text"]), transcript)
            report.update(transcript=transcript, checker=MODEL_ID, checker_revision=MODEL_REVISION)
            path = job / w.SEGMENTS_DIR / PENDING_DIR / f"check_{unit['index']:06d}_{time.time_ns()}.json"
            w._write_json(path, report)
            row.update(status="checked", report=str(path))
            _save(job, row)
        _progress(job, plan, "quality_check", batch[-1])


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("job_dir", type=Path)
    parser.add_argument("--phase", required=True, choices=("render", "check"))
    parser.add_argument("--worker", type=int, default=0)
    parser.add_argument("--workers", type=int, default=1)
    arguments = parser.parse_args()
    plan, config = w.load_plan(arguments.job_dir)
    if arguments.phase == "render":
        render_phase(arguments.job_dir, plan, config, arguments.worker, arguments.workers)
    elif arguments.worker != 0 or arguments.workers != 1:
        raise ValueError("Parakeet checking uses one GPU process")
    else:
        check_phase(arguments.job_dir, plan, config)
