"""Generate the pending book, check it on GPU, then repair in bounded rounds.

Each GPU phase owns a separate process. Verified unit receipts and listening
decisions use the same validation and assembly code as the original worker.
"""

import argparse
import json
import shutil
from pathlib import Path
import subprocess
import sys
import time

import vibevoice_worker as w
from process_ownership import WindowsWorkerJob
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
    if unit.get("numbered_heading") and "numbered_heading" not in row["unit"]:
        # Older Drama takes retain their audio but gain the strict heading check.
        row["unit"]["numbered_heading"] = True
    stored_unit = {key: value for key, value in row["unit"].items() if key not in ("render_seed", "render_model")}
    profile = w.delivery.INTACT_PROFILE if row['unit'].get('render_model') and not unit.get('render_heading') and not unit.get('numbered_heading') else None
    if (stored_unit != w._profiled_unit(unit, profile)
            or row.get("basis") != _basis(job / w.SEGMENTS_DIR / w.UNITS_DIR, unit)):
        return None
    audio = Path(row["audio"])
    if row["status"] in {"ready", "checked"}:
        if not audio.is_file() or w.sha256_file(audio) != row.get("audio_sha256"):
            raise RuntimeError(f"Pending clip {unit['index']} changed; restore its saved audio before resuming.")
        if unit.get("sample_rate") == 44100:
            from drama3 import validate_generation
            validate_generation(row.get("generation"), unit)
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
    done = verified = generated = total_words = 0
    for parent in plan["passages"]:
        units = w._units_for_parent(parent, config)
        parent_words = sum(len(u.get('spoken_text', u['text']).split()) for u in units)
        total_words += parent_words
        receipt = w._receipt_path(segments, parent["index"])
        saved = _read(receipt) if receipt.exists() else {}
        # Advisory counts read metadata; the scheduler verifies audio hashes.
        if not parent_words or saved.get("identity") == parent["identity"] and not saved.get("force_regenerate"):
            done += 1
            verified += parent_words
        for unit in units:
            pending = w._receipt_path(segments / PENDING_DIR, unit["index"])
            row = _read(pending) if pending.exists() else {}
            receipt = w._receipt_path(units_dir, unit["index"])
            saved = _read(receipt) if receipt.exists() else {}
            if (saved.get("identity") == unit["identity"] and not saved.get("force_regenerate")
                    or unit["index"] in review_candidates
                    or row.get("audio_sha256")):
                generated += len(unit.get('spoken_text', unit['text']).split())
    w._progress(job, done, len(plan["passages"]), 0, status,
                current["unit"]["parent_index"] if current else None,
                current["attempt"] if current else None, metrics={
                    "verified_words": verified, "generated_words": generated,
                    "total_words": total_words,
                    "review_passages": len(reviews), "eta_sec": None,
                    "workflow": WORKFLOW,
                    "render_workers": 1 if current and current['unit'].get('render_model') else config.get("render_workers", 1),
                })


def _run_phase(job, config, phase):
    _cancel(job)
    workers = config.get("render_workers", 1) if phase == "render" else 1
    drama = config.get("backend") == "drama3"
    if drama and workers != 1:
        raise ValueError("Drama 3 requires exactly one GPU renderer")
    if type(workers) is not int or workers not in (1, 2):
        raise ValueError("Render workers must be one or two")
    if phase in ("render", "repair") and not drama:
        plan, _ = w.load_plan(job)
        # Prepare this shared, immutable reference before either child opens it.
        w._prepare_voice(job, config, plan)
    print(f"Starting {phase} phase with {workers} worker(s); the previous GPU phase has exited.", flush=True)
    python = config["parakeet_python"] if phase == "check" else sys.executable
    command = [python, "-X", "utf8", str(Path(__file__).resolve()), str(job), "--phase", phase]
    processes = []
    owners = []
    try:
        for worker in range(workers):
            _cancel(job)
            processes.append(subprocess.Popen(command + ["--worker", str(worker), "--workers", str(workers)],
                             stdout=sys.stdout, stderr=sys.stderr,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)))
            owner = WindowsWorkerJob()
            owners.append(owner)
            owner.assign(processes[-1])
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
        for owner in owners:
            owner.close()
        for process in processes:
            if process.poll() is None:
                process.terminate()
        for process in processes:
            process.wait()


def _retain_prior(job, parent, units, unit):
    """Keep a validated prior take visible without approving residual differences."""
    folder = job / w.SEGMENTS_DIR / w.UNITS_DIR
    if not w._valid_unit(folder, unit, allow_needs_repair=True):
        return False
    review = w.narration_review.entry(job, parent) or {}
    candidates = [index for index in review.get('candidates', []) if index != unit['index']]
    w.narration_review.record(job, parent, units, candidates)
    return True


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
        prior_path = w._receipt_path(folder, unit["index"])
        prior = _read(prior_path) if prior_path.exists() else {}
        listening_replacement = config.get("backend") == "drama3" and (prior.get("force_regenerate") or prior.get("listening_approval"))
        if assessment["ok"] and listening_replacement:
            w._publish_unit(candidates_dir, row["unit"], Path(row["audio"]), row["report"], row["attempt"])
            candidate_path = w._receipt_path(candidates_dir, unit["index"])
            candidate = _read(candidate_path)
            candidate["listen_again"] = True
            w._write_json(candidate_path, candidate)
            candidates.append(unit["index"])
            w.narration_review.record(job, parent, units, candidates)
        elif assessment['ok'] and w._valid_unit(folder, unit, allow_needs_repair=True):
            # A stale parent retry cannot silently displace a passing saved take.
            w._publish_unit(candidates_dir, row['unit'], Path(row['audio']), row['report'], row['attempt'])
            _retain_prior(job, parent, units, unit)
        elif assessment["ok"]:
            w._publish_unit(folder, row["unit"], Path(row["audio"]), row["report"], row["attempt"])
            if unit["index"] in candidates:
                candidates.remove(unit["index"])
                w.narration_review.record(job, parent, units, candidates)
        elif ((row["attempt"] >= w._attempt_limit(row["unit"], config.get("quality_max_retries", 2))
               and (not config.get('repair_model') or row['unit'].get('render_model')))
              or (assessment.get('review_required') and config.get('backend') != 'drama3')
              or assessment.get("transcript_review", {}).get("decision") == "uncertain"):
            w._publish_unit(candidates_dir, row["unit"], Path(row["audio"]), row["report"], row["attempt"])
            if _retain_prior(job, parent, units, unit):
                candidates = [index for index in candidates if index != unit['index']]
            else:
                candidates.append(unit["index"])
                w.narration_review.record(job, parent, units, candidates)
        else:
            rejected = job / w.REJECTED_DIR / f"unit_{unit['index']:010d}_phase_{time.time_ns()}.wav"
            Path(row["audio"]).replace(rejected)
            row["last_candidate"] = {"audio": str(rejected), "audio_sha256": row["audio_sha256"],
                                     "report": row["report"], "report_sha256": w.sha256_file(row['report']),
                                     "attempt": row["attempt"], "unit": row["unit"]}
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
        if any(w._valid_unit(folder, unit, allow_needs_repair=True, allow_review=True)
               and not w._valid_unit(folder, unit, allow_needs_repair=True) for unit in units):
            previous_review = w.narration_review.entry(job, parent) or {}
            w.narration_review.record(job, parent, units, previous_review.get('candidates', []))
        review_items = w.narration_review.detail(job, parent['index'])['items'] if w.narration_review.entry(job, parent) else []
        selected_retries = {item['index'] for item in review_items if item['decision'] == 'retry'}
        retry_fingerprints = {item['index']: item['fingerprint'] for item in review_items if item['decision'] == 'retry'}
        if w._recover_parent_from_units(job, parent, units, folder, segments):
            continue
        review = w.narration_review.entry(job, parent)
        flagged = {item["index"] for item in w.narration_review.detail(job, parent["index"])["items"]
                   if item["decision"] != "retry"} if review else set()
        missing = [u for u in units if u["index"] not in flagged and not w._valid_unit(folder, u)]
        if not missing and not review:
            # An aggregate failure does not identify a defective passing clip.
            w.narration_review.record(job, parent, units)
            continue
        for unit in missing:
            row = _pending(job, unit)
            if row and row['status'] == 'failed' and unit['index'] in selected_retries:
                # An explicit retry starts a fresh bounded budget; preserve the
                # exhausted receipt as evidence before replacing its index.
                archive = job / w.REJECTED_DIR / f"unit_{unit['index']:010d}_failed_{time.time_ns()}.json"
                w._write_json(archive, row)
                row = None
            if row and row["status"] == "failed":
                if not config.get('repair_model') or row['unit'].get('render_model'):
                    _retain_prior(job, parent, units, unit)
                    continue
                # A newly enabled repair model gets its own bounded budget for
                # clips that exhausted the primary model before this resume.
                archive = job / w.REJECTED_DIR / f"unit_{unit['index']:010d}_primary_failed_{time.time_ns()}.json"
                w._write_json(archive, row)
                row['status'] = 'retry'
            if (row and row['status'] == 'render' and row['attempt'] > 1
                    and config.get('repair_model') and not row['unit'].get('render_model')):
                archive = job / w.REJECTED_DIR / f"unit_{unit['index']:010d}_primary_retry_{time.time_ns()}.json"
                w._write_json(archive, row)
                row['status'] = 'retry'
            if row and row["status"] in {"render", "ready"}:
                work.append(row)
                continue
            receipt_path = w._receipt_path(folder, unit["index"])
            receipt = _read(receipt_path) if receipt_path.exists() else {}
            previous = row["attempt"] if row else (0 if receipt.get("force_regenerate") else receipt.get("attempt", 0))
            profiled = w._profiled_unit(unit)
            if row and row['status'] == 'rendering':
                row.setdefault('failures', []).append({'attempt': previous, 'error': 'render interrupted before publication'})
            repair = config.get('repair_model') if (previous or receipt.get('needs_repair') or receipt.get('force_regenerate')
                       or unit['identity'] in config.get('repair_unit_ids', [])) else None
            if repair:
                prior_model = row['unit'].get('render_model') if row else receipt.get('render_model')
                if prior_model != repair:
                    previous = 0
                if not unit.get('render_heading') and not unit.get('numbered_heading'):
                    profiled = w._profiled_unit(unit, w.delivery.INTACT_PROFILE)
                profiled['render_model'] = repair
            if previous >= w._attempt_limit(profiled, config.get("quality_max_retries", 2)):
                row = row or {"unit": profiled, "attempt": previous, "basis": _basis(folder, unit),
                              "audio": str(w._wav_path(segments / PENDING_DIR, unit["index"]))}
                row["status"] = "failed"
                _save(job, row)
                if _retain_prior(job, parent, units, unit):
                    continue
                # A later render failure must not discard the last checked take.
                candidate = row.get("last_candidate")
                if candidate:
                    if (w.sha256_file(candidate["audio"]) != candidate["audio_sha256"]
                            or w.sha256_file(candidate['report']) != candidate['report_sha256']):
                        raise RuntimeError("Saved render candidate changed before recovery")
                    temporary = Path(row["audio"]).with_suffix(".recovery.wav")
                    shutil.copy2(candidate["audio"], temporary)
                    report = temporary.with_suffix('.json')
                    shutil.copy2(candidate['report'], report)
                    w._publish_unit(segments / w.narration_review.CANDIDATES_DIR, candidate["unit"],
                                    temporary, report, candidate["attempt"])
                    review = w.narration_review.entry(job, parent) or {}
                    w.narration_review.record(job, parent, units, [*review.get("candidates", []), unit["index"]])
                continue
            history = row.get("failures", []) if row else []
            seed_offset = row.get("seed_offset", 0) if row else 0
            if config.get("backend") == "drama3" and not row:
                fingerprint = retry_fingerprints.get(unit["index"]) or _basis(folder, unit)
                seed_offset = int(fingerprint[:8], 16) if fingerprint else 0
            row = {"unit": profiled, "attempt": previous + 1, "basis": _basis(folder, unit), "status": "render",
                   "failures": history, **({"last_candidate": row["last_candidate"]} if row and row.get("last_candidate") else {}),
                   "audio": str(w._wav_path(segments / PENDING_DIR, unit["index"]))}
            if config.get("backend") == "drama3":
                row["seed_offset"] = seed_offset
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
    if config.get("backend") == "drama3":
        from drama3 import recover
        recover(job, plan, config)
    review_phase(job, plan, config)
    while True:
        work = _schedule(job, plan, config)
        if not work:
            break
        if any(row["status"] == "render" for row in work):
            _progress(job, plan, "generating")
            if any(row['status'] == 'render' and not row['unit'].get('render_model') for row in work):
                _run_phase(job, config, "render")
            if any(row['status'] == 'render' and row['unit'].get('render_model') for row in work):
                _run_phase(job, config, "repair")
        _progress(job, plan, "quality_check")
        _run_phase(job, config, "check")
        review_phase(job, plan, config)
    failures = _phase_rows(job, plan, config, "failed")
    missing_audio = [row for row in failures if not row.get("last_candidate")
                     and not w._valid_unit(job / w.SEGMENTS_DIR / w.UNITS_DIR,
                                           row['unit'], allow_needs_repair=True)]
    if missing_audio:
        _progress(job, plan, "render_failed", missing_audio[0])
        raise RuntimeError(f"{len(missing_audio)} clip(s) exhausted rendering attempts without usable audio; "
                           "independent clips are saved. See pending unit receipts for failures. Assembly is incomplete.")
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


def render_phase(job, plan, config, worker=0, workers=1, repair=False):
    if config.get("backend") == "drama3":
        if worker != 0 or workers != 1 or repair:
            raise ValueError("Drama 3 uses one native renderer and whole-unit retries")
        from drama3 import render_phase as render_drama
        return render_drama(job, plan, config)
    rows = _phase_rows(job, plan, config, "render", worker, workers)
    rows = [row for row in rows if bool(row['unit'].get('render_model')) == repair]
    if not rows:
        return
    if repair:
        from vibevoice_plan import model_fingerprint
        model = config['repair_model']
        if workers != 1 or any(row['unit']['render_model'] != model for row in rows):
            raise ValueError('Repair model configuration changed; inspect the saved repair queue')
        if model_fingerprint(model['model_dir']) != model['model_fingerprint']:
            raise ValueError('Repair model weights changed; inspect the configured model')
        config = {**config, **model, 'render_workers': 1, 'native_batch_size': 1}
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
        for row in batch:
            row["status"] = "rendering"
            _save(job, row)
        rendered = w._render_items(torch, processor, model, voice,
                                   [(row["unit"], row["attempt"]) for row in batch], config, folder)
        for row, (unit, attempt, temporary, error) in zip(batch, rendered):
            if error:
                if not w._recoverable_render_error(error):
                    raise error
                row["status"] = "retry"
                row.setdefault("failures", []).append({"attempt": row["attempt"], "error": str(error)})
                _save(job, row)
                continue
            _cancel(job)
            temporary.replace(row["audio"])
            row.update(unit=unit, status="ready", audio_sha256=w.sha256_file(row["audio"]))
            _save(job, row)
        _progress(job, plan, "generating", batch[-1])


def load_transcriber(config):
    """Load one GPU checker; caller owns its process lifetime."""
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

    return transcribe


def check_phase(job, plan, config):
    rows = _phase_rows(job, plan, config, "ready")
    if not rows:
        return
    _cancel(job)
    w._assert_no_ocr()
    import torch
    transcribe = load_transcriber(config)

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
            if row.get("generation"):
                report["generation"] = row["generation"]
            path = job / w.SEGMENTS_DIR / PENDING_DIR / f"check_{unit['index']:06d}_{time.time_ns()}.json"
            w._write_json(path, report)
            row.update(status="checked", report=str(path))
            _save(job, row)
        _progress(job, plan, "quality_check", batch[-1])


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("job_dir", type=Path)
    parser.add_argument("--phase", required=True, choices=("render", "repair", "check"))
    parser.add_argument("--worker", type=int, default=0)
    parser.add_argument("--workers", type=int, default=1)
    arguments = parser.parse_args()
    try:
        plan, config = w.load_plan(arguments.job_dir)
        if arguments.phase in ("render", "repair"):
            render_phase(arguments.job_dir, plan, config, arguments.worker, arguments.workers, arguments.phase == 'repair')
        elif arguments.worker != 0 or arguments.workers != 1:
            raise ValueError("Parakeet checking uses one GPU process")
        else:
            check_phase(arguments.job_dir, plan, config)
    except Exception as exc:
        w._write_json(arguments.job_dir / w.ERROR_FILE, {"reason": arguments.phase + "_failed", "message": str(exc)})
        raise
