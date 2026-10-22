"""Pinned native Drama 3 Q3 renderer for the existing phased narration workflow.

The historical vibevoice_* checkpoint names are shared storage, not model labels.
Raw audio and codec envelopes are immutable evidence; only checked PCM is published.
History is an explicit prior-take operation. This module does not implement infill.
"""

import hashlib
import json
import os
from pathlib import Path
import subprocess
import time

try:
    from .generation_settings import normalize_settings
    from .vibevoice_plan import sha256_file, pack_passages, passage_identity, PLAN_FILENAME, CONFIG_FILENAME
    from .process_ownership import WindowsWorkerJob
except ImportError:
    from generation_settings import normalize_settings
    from vibevoice_plan import sha256_file, pack_passages, passage_identity, PLAN_FILENAME, CONFIG_FILENAME
    from process_ownership import WindowsWorkerJob

SOURCE_REVISION = "4e6018fd018499d75e5070ba4eb38db4e48b9b59"
EXE_SHA256 = "7438ba2c37bc42da4b9875ecde6dae3d6eb71148a1148ee0eee9daa86f8436db"
MODEL_SHA256 = "b946a8c9806deba559590b98e37ffc9e0957109263e111513734fa93284db16b"
MODEL_REVISION = "bcb065b8b0b98535a5c002b39bcceeb8bf065513"
SAMPLE_RATE = 44100
BATCH_SIZE = 4
MAX_TEXT_CHARS = 1000
RUN_TIMEOUT = 240
REFERENCE_FILE = "drama3_reference.json"
EMPTY_TAKE_ERROR = "Drama 3 ended before producing an audio frame"


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write(path, value):
    path = Path(path)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def file_stamp(path):
    path = Path(path).resolve(strict=True)
    stat = path.stat()
    return {"path": str(path), "bytes": stat.st_size, "mtime_ns": stat.st_mtime_ns}


def assets(config, verify=False):
    """Hash at registration; bind later loads to the registered files and stats."""
    paths = [Path(config["drama3_executable"]), Path(config["drama3_model"])]
    paths += sorted(Path(config["drama3_cuda_bin"]).glob("*.dll"))
    if len(paths) < 3:
        raise ValueError("Drama 3 CUDA libraries are missing")
    result = []
    for index, path in enumerate(paths):
        entry = file_stamp(path)
        if verify:
            entry["sha256"] = sha256_file(path)
            expected = (EXE_SHA256, MODEL_SHA256)[index] if index < 2 else None
            if expected and entry["sha256"] != expected:
                raise ValueError(f"Drama 3 requires the tested native Q3 asset: {path.name}")
        result.append(entry)
    return result


def runtime_profile(config):
    settings = normalize_settings("drama3", config.get("path", "A"), config.get("generation_settings"))
    limits = config.get("drama3_unit_limits", {"target_words": 55, "max_words": 75})
    boundary = config.get('unit_boundary_policy', 'initials_v2')
    unit_policy = f"intact_{limits['target_words']}_{limits['max_words']}_{boundary}"
    if config.get("drama3_list_max_words"):
        unit_policy += f"_lists{config['drama3_list_max_words']}"
    import scene_direction
    directed = scene_direction.binding(config)
    return {
        **({"scene_direction_sha256": scene_direction.digest(directed)} if directed else {}),
        "backend": "drama3", "model_id": "Jmica/Drama-3-GGUF/Q3_K_S", "model_revision": MODEL_REVISION,
        "model_sha256": MODEL_SHA256, "codec_sha256": MODEL_SHA256, "native_revision": SOURCE_REVISION,
        "assets": config["drama3_assets"], "sample_rate": SAMPLE_RATE, "target_lufs": -21.0,
        "cpu_expert_layers": config.get("drama3_cpu_expert_layers", 0), "threads": 8, "text_chunk_size": MAX_TEXT_CHARS,
        "unit_policy": unit_policy, "reference_text": config["reference_text"],
        "source_voice_sha256": config["source_voice_sha256"],
        "spoken_projection": config.get("spoken_projection", {}),
        "history": config.get("drama3_history", {}),
        **{key: settings[key] for key in ("temperature", "top_p", "top_k", "max_frames", "context_length", "seed")},
    }


def write_plan(job_dir, blocks, config):
    job = Path(job_dir)
    config = dict(config)
    import scene_direction
    sidecar = job / "scene_direction.json"
    if sidecar.exists():
        requested = read(sidecar)
        if "scene_direction" in config and config["scene_direction"] != requested:
            raise ValueError("Direction changed. Create a new audition job; existing audio is preserved.")
        config["scene_direction"] = requested
    directed = scene_direction.binding(config)
    settings = normalize_settings("drama3", config.get("path", "A"), config.get("generation_settings"))
    config.update(backend="drama3", generation_settings=settings, sample_rate=SAMPLE_RATE,
                  workflow="generate_first_parakeet_v1", render_workers=1, transcript_review=False,
                  quality_max_retries=2, target_lufs=-21.0)
    config.update({key: settings[key] for key in ("passage_gap_ms", "heading_lead_ms")})
    previous = job / PLAN_FILENAME
    if not previous.exists():
        config.setdefault("unit_boundary_policy", "sentences_v4")
        config.setdefault("drama3_cpu_expert_layers", 12)
        config.setdefault("drama3_unit_limits", {"target_words": 75, "max_words": 100})
        try:
            from .vibevoice_delivery import PROJECTION_VERSION
        except ImportError:
            from vibevoice_delivery import PROJECTION_VERSION
        config.setdefault("spoken_projection", {"version": PROJECTION_VERSION})
    if previous.exists():
        saved, prior = read(previous), read(job / CONFIG_FILENAME)
        if prior.get("backend") != "drama3":
            raise ValueError("Existing audio belongs to another narrator. Create a new job to migrate it.")
        config.setdefault("unit_boundary_policy", prior.get("unit_boundary_policy", "initials_v2"))
        config["drama3_assets"] = prior["drama3_assets"]
        validate_plan(saved, config)
    else:
        config["drama3_assets"] = assets(config, verify=True)
    runtime = saved['runtime'] if previous.exists() else runtime_profile(config)
    voice_sha = sha256_file(config["reference_wav"])
    passages = pack_passages(blocks, preserve_sentences=config["unit_boundary_policy"] == "sentences_v4")
    if directed and [p["text"] for p in passages] != [p["text"] for p in directed["source"]["passages"]]:
        raise ValueError("Direction does not match the exact planned text; re-analyze before narration")
    for index, passage in enumerate(passages):
        passage.update(index=index, sample_rate=SAMPLE_RATE,
                       before_ms=settings["heading_lead_ms"] if passage.get("heading") else 0,
                       after_ms=settings["passage_gap_ms"] if index < len(passages) - 1 else 0,
                       speaker_text="Speaker 0: " + passage["text"],
                       text_sha256=hashlib.sha256(passage["text"].encode("utf-8")).hexdigest(),
                       identity=passage_identity(passage["text"], voice_sha, runtime))
    plan = {"schema": 1, "runtime": runtime, "voice_sha256": voice_sha, "passages": passages}
    if previous.exists() and plan != read(previous):
        raise ValueError("Drama 3 text, voice or settings changed. Create a new job; saved audio is preserved.")
    write(job / CONFIG_FILENAME, config)
    write(previous, plan)
    return plan


def validate_plan(plan, config):
    if (config.get("backend") != "drama3" or config.get("render_workers") != 1
            or config.get("workflow") != "generate_first_parakeet_v1" or config.get("sample_rate") != SAMPLE_RATE
            or config.get("unit_boundary_policy") not in ("initials_v2", "sentences_v4") or config.get("repair_model")):
        raise ValueError("Drama 3 requires its single-renderer, GPU-exclusive workflow")
    registered = [{k: v for k, v in entry.items() if k != "sha256"} for entry in config["drama3_assets"]]
    if assets(config) != registered:
        raise ValueError("Drama 3 native assets changed; restore the registered runtime before resuming")
    runtime = runtime_profile(config)
    resource_migration = config.get('drama3_resource_migration')
    if resource_migration:
        # Explicit capacity/offload changes can retain completed, checked takes.
        # The frozen model, sampling, voice and text identity still have to match.
        original = plan.get('runtime', {})
        keys = ('max_frames', 'context_length', 'cpu_expert_layers')
        previous = {key: original[key] for key in keys}
        current = {key: runtime[key] for key in keys}
        expected = {'source_runtime_identity': hashlib.sha256(json.dumps(original, sort_keys=True).encode()).hexdigest(),
                    'previous_limits': previous, 'limits': current}
        if resource_migration != expected:
            raise ValueError('Drama 3 resource migration does not match the saved runtime and requested limits')
        runtime.update(previous)
    original_projection = plan.get('runtime', {}).get('spoken_projection', {})
    # Exact source corrections are checked per unit. Keep the original parent
    # identity so an unrelated correction cannot invalidate the whole book.
    projection = config.get('spoken_projection', {})
    if ({k:v for k,v in projection.items() if k != 'corrections'}
            == {k:v for k,v in original_projection.items() if k != 'corrections'}):
        runtime['spoken_projection'] = original_projection
    if plan.get("schema") != 1 or plan.get("runtime") != runtime:
        raise ValueError("Drama 3 conditioning or generation settings changed; saved audio cannot be reused")
    if sha256_file(config["reference_wav"]) != plan.get("voice_sha256"):
        raise ValueError("Drama 3 voice reference changed")
    for index, passage in enumerate(plan["passages"]):
        if (passage.get("index") != index or passage.get("sample_rate") != SAMPLE_RATE
                or passage.get("identity") != passage_identity(passage["text"], plan["voice_sha256"], plan["runtime"])):
            raise ValueError("Drama 3 passage identity or sample rate changed")
    corrections = projection.get('corrections', [])
    if corrections:
        import vibevoice_worker as worker
        parents = {p['identity']:p for p in plan['passages']}
        for correction in corrections:
            if correction.get('parent_identity') not in parents:
                raise ValueError('Source correction does not match a planned passage')
        for identity in {c['parent_identity'] for c in corrections}:
            worker._units_for_parent(parents[identity], config)
    for generation in config.get("drama3_history", {}).values():
        validate_generation(generation)


def decode_take(path, expected_text=None):
    envelope = read(path)
    if (envelope.get("kind") != "acoustic_tokens" or envelope.get("meta", {}).get("family") != "fish_drama3"
            or envelope.get("meta", {}).get("schema") != "drama3_take_v1"):
        raise ValueError("Not a Drama 3 take envelope")
    payload = bytes.fromhex(envelope["payload_hex"])
    if len(payload) != envelope.get("bytes"):
        raise ValueError("Incomplete Drama 3 codec envelope")
    take = json.loads(payload)
    books = take.get("vq_codes")
    if (not isinstance(take.get("text"), str) or not take["text"]
            or expected_text is not None and take["text"] != expected_text
            or not isinstance(books, list) or len(books) != 10 or not isinstance(books[0], list) or not books[0]
            or any(not isinstance(row, list) or len(row) != len(books[0])
                   or any(type(value) is not int or not 0 <= value < 4096 for value in row) for row in books)):
        raise ValueError("Drama 3 take has mismatched text or invalid codebooks")
    return take


def validate_generation(generation, unit=None):
    if (not isinstance(generation, dict) or generation.get("backend") != "drama3"
            or generation.get("model_sha256") != MODEL_SHA256 or generation.get("codec_sha256") != MODEL_SHA256):
        raise ValueError("Missing or incompatible Drama 3 generation provenance")
    for key in ("raw_wav", "codes"):
        if sha256_file(generation[key]) != generation[key + "_sha256"]:
            raise ValueError(f"Saved Drama 3 {key} changed")
    take = decode_take(generation["codes"], generation["text"])
    if not 0 < len(take["vq_codes"][0]) < generation["max_frames"]:
        raise ValueError("A frame-capped Drama 3 take cannot be reused")
    if unit is not None:
        import vibevoice_worker as worker
        if (generation["unit_identity"] != unit["identity"]
                or generation["text"] != worker._profiled_unit(unit)["render_text"]):
            raise ValueError("Drama 3 take does not match its narration unit")
    return take


def command(config, requests, output):
    settings = config["generation_settings"]
    return [config["drama3_executable"], "--task", "clon", "--family", "fish_drama3",
            "--backend", "cuda", "--mode", "offline", "--model", config["drama3_model"], "--threads", "8",
            "--session-option", f"fish_drama3.cpu_expert_layers={config.get('drama3_cpu_expert_layers', 0)}",
            "--session-option", f"fish_drama3.context_length={settings['context_length']}",
            "--request-sequence", str(requests), "--out-dir", str(output / "audio"),
            "--batch-manifest-out", str(output / "batch.json"), "--metrics", "--log"]


def _request(row, config, folder):
    unit = row["unit"]
    text = unit["render_text"]
    if not text.strip() or len(text) > MAX_TEXT_CHARS:
        raise ValueError("Drama 3 unit exceeds the tested 1000-character context bound")
    settings = config["generation_settings"]
    request = {"id": f"unit_{unit['index']}_{row['attempt']}", "text": text,
               "voice_ref": config["reference_wav"], "reference_text": config["reference_text"],
               "seed": (settings["seed"] + unit["index"] + row["attempt"] - 1 + row.get("seed_offset", 0)) % 2**32,
               "max_tokens": settings["max_frames"], "text_chunk_size": MAX_TEXT_CHARS,
               **{key: settings[key] for key in ("temperature", "top_p", "top_k")}}
    history = config.get("drama3_history", {}).get(str(unit["index"]))
    if history:
        take = validate_generation(history)
        if history.get("reference_sha256") != sha256_file(config["reference_wav"]):
            raise ValueError("Prior-take conditioning requires the same narrator reference")
        history_path = folder / f"{request['id']}_history.json"
        write(history_path, [take])
        request["previous_takes_file"] = str(history_path)
    return request


def _harvest(job, row, config):
    """Only a complete single-chunk raw WAV plus complete uncapped codes can commit."""
    import numpy as np
    import soundfile as sf
    import vibevoice_phases as phases
    from vibevoice_audio import normalize_audio
    run = row.get("native_run")
    if not run:
        return False
    folder, request = Path(run["folder"]), run["request"]
    raw = folder / "audio" / (request["id"] + ".wav")
    codes = folder / "audio" / request["id"] / "drama3_take.json"
    try:
        take = decode_take(codes, request["text"])
        pcm, rate = sf.read(str(raw), dtype="float32")
    except (OSError, ValueError, KeyError, RuntimeError):
        return False  # The native writer may still be completing these files.
    frames = len(take["vq_codes"][0])
    if frames >= request["max_tokens"]:
        row.update(status="retry")
        row.setdefault("failures", []).append({"attempt": row["attempt"], "error": "Drama 3 reached its frame cap", "native_run": run})
        phases._save(job, row)
        return True
    if rate != SAMPLE_RATE or pcm.ndim != 1 or len(pcm) != frames * 2048 or not np.isfinite(pcm).all():
        return False
    try:
        normalized = normalize_audio(pcm, rate)
    except RuntimeError as exc:
        row["status"] = "retry"
        row.setdefault("failures", []).append({"attempt": row["attempt"], "error": str(exc), "native_run": run})
        phases._save(job, row)
        return True
    target = Path(row["audio"])
    temporary = target.with_suffix(".native.tmp.wav")
    sf.write(str(temporary), normalized, rate, subtype="PCM_16")
    generation = {"backend": "drama3", "model_sha256": MODEL_SHA256, "codec_sha256": MODEL_SHA256,
                  "native_revision": SOURCE_REVISION, "unit_identity": row["unit"]["identity"],
                  "text": request["text"], "request": request, "max_frames": request["max_tokens"],
                  "frames": frames, "sample_rate": rate, "raw_wav": str(raw), "raw_wav_sha256": sha256_file(raw),
                  "reference_sha256": sha256_file(config["reference_wav"]),
                  "codes": str(codes), "codes_sha256": sha256_file(codes),
                  "runtime_identity": hashlib.sha256(json.dumps(runtime_profile(config), sort_keys=True).encode()).hexdigest()}
    write(folder / (request["id"] + "_generation.json"), generation)
    temporary.replace(target)
    row.update(status="ready", audio_sha256=sha256_file(target), generation=generation)
    phases._save(job, row)
    return True


def recover(job, plan, config):
    """Recover completed native requests even if cancellation interrupted the batch."""
    import vibevoice_phases as phases
    for row in phases._phase_rows(job, plan, config, "rendering"):
        if not _harvest(job, row, config):
            # Unfinished requests keep their seed and retry budget on resume.
            row["status"] = "render"
            phases._save(job, row)


def render_phase(job, plan, config):
    import vibevoice_phases as phases
    import vibevoice_worker as worker
    rows = phases._phase_rows(job, plan, config, "render")
    size = 1 if config["generation_settings"]["performance_mode"] == "conservative" else BATCH_SIZE
    worker._assert_no_ocr()
    offset = 0
    while offset < len(rows):
        phases._cancel(job)
        batch = rows[offset:offset + size]
        offset += len(batch)
        folder = job / "drama3_runs" / str(time.time_ns())
        folder.mkdir(parents=True)
        requests = [_request(row, config, folder) for row in batch]
        write(folder / "requests.json", requests)
        cmd = command(config, folder / "requests.json", folder)
        write(folder / "run.json", {"command": cmd, "started": time.time()})
        for row, request in zip(batch, requests):
            row.update(status="rendering", native_run={"folder": str(folder), "request": request})
            phases._save(job, row)
        env = dict(os.environ)
        env["PATH"] = config["drama3_cuda_bin"] + os.pathsep + env.get("PATH", "")
        env["CUDA_VISIBLE_DEVICES"] = "0"
        started = time.monotonic()
        owner = WindowsWorkerJob()
        process = None
        try:
            with (folder / "native.log").open("w", encoding="utf-8") as log:
                process = subprocess.Popen(cmd, env=env, stdout=log, stderr=subprocess.STDOUT,
                                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                owner.assign(process)
                while True:
                    for row in batch:
                        if row["status"] == "rendering" and _harvest(job, row, config):
                            phases._progress(job, plan, "generating", row)
                    phases._cancel(job)
                    code = process.poll()
                    if code is not None:
                        break
                    if time.monotonic() - started > RUN_TIMEOUT:
                        raise RuntimeError(f"Drama 3 exceeded {RUN_TIMEOUT}s for a bounded batch; completed clips are saved. See {folder / 'native.log'}")
                    time.sleep(0.2)
            for row in batch:
                if row["status"] == "rendering":
                    _harvest(job, row, config)
            unfinished = [row for row in batch if row["status"] == "rendering"]
            if (code == 1 and unfinished and batch[-len(unfinished):] == unfinished
                    and (folder / "native.log").read_text(encoding="utf-8", errors="replace").splitlines()[-1:]
                    == [f"audiocpp_cli failed: {EMPTY_TAKE_ERROR}"]
                    and all(not (folder / "audio" / (row["native_run"]["request"]["id"] + ".wav")).exists()
                            and not (folder / "audio" / row["native_run"]["request"]["id"] / "drama3_take.json").exists()
                            for row in unfinished)):
                # The CLI stops its sequential batch at the empty take. Only that
                # request used an attempt; the remaining requests keep their seeds.
                failed = unfinished[0]
                failed["status"] = "retry"
                failed.setdefault("failures", []).append({"attempt": failed["attempt"],
                    "error": EMPTY_TAKE_ERROR, "native_run": failed["native_run"]})
                phases._save(job, failed)
                for row in unfinished[1:]:
                    row["status"] = "render"
                    phases._save(job, row)
                offset -= len(unfinished) - 1
                print(f"Drama 3 clip {failed['unit']['index']} produced an empty take; "
                      "queued a bounded retry and continuing saved work.", flush=True)
                continue
            if code != 0 or any(row["status"] == "rendering" for row in batch):
                raise RuntimeError(f"Drama 3 native process failed ({code}) or left incomplete artifacts; completed clips are saved. See {folder / 'native.log'}")
        except Exception as exc:
            for row in batch:
                if row["status"] == "rendering":
                    row["status"] = "retry"
                    row.setdefault("failures", []).append({"attempt": row["attempt"], "error": str(exc), "native_run": row["native_run"]})
                    phases._save(job, row)
            raise
        finally:
            owner.close()
            if process is not None:
                if process.poll() is None:
                    process.kill()
                process.wait()
            write(folder / "exit.json", {"exit_code": process.returncode if process else None,
                                        "wall_seconds": time.monotonic() - started,
                                        "completed": [row["unit"]["index"] for row in batch if row["status"] == "ready"]})


def prepare_reference(job, config):
    """Use an exact registered audition reference, or transcribe the selected voice on GPU."""
    import numpy as np
    import soundfile as sf
    from math import gcd
    from scipy.signal import resample_poly
    import vibevoice_phases as phases
    import vibevoice_worker as worker
    job = Path(job)
    source = Path(config["source_reference_wav"])
    source_hash = sha256_file(source)
    receipt = job / REFERENCE_FILE
    if receipt.exists():
        prepared = read(receipt)
        if prepared["source_voice_sha256"] != source_hash or sha256_file(prepared["reference_wav"]) != prepared["reference_sha256"]:
            raise ValueError("Drama 3 saved voice changed; preserve this job and create a new one")
        return prepared
    profiles = read(config["drama3_reference_profiles"]) if config.get("drama3_reference_profiles") else {}
    known = profiles.get(source_hash)
    path = Path(known["path"]) if known else source
    if known and sha256_file(path) != known["sha256"]:
        raise ValueError("Registered Drama 3 audition voice changed")
    pcm, rate = sf.read(str(path), dtype="float32", always_2d=True)
    pcm = pcm[:20 * rate].mean(axis=1)
    if len(pcm) < rate or not np.isfinite(pcm).all() or np.max(np.abs(pcm)) <= 0.001:
        raise ValueError("Drama 3 needs a finite, audible voice sample of at least one second")
    if rate != SAMPLE_RATE:
        divisor = gcd(rate, SAMPLE_RATE)
        pcm = resample_poly(pcm, SAMPLE_RATE // divisor, rate // divisor)
    target = job / "drama3_reference.wav"
    temporary = target.with_suffix(".tmp.wav")
    if known:
        import shutil
        shutil.copy2(path, temporary)  # Keep the audition's exact reference bytes.
    else:
        sf.write(str(temporary), pcm, SAMPLE_RATE, subtype="PCM_16")
    phases._cancel(job)
    if known:
        transcript = known["text"]
        provenance = "registered_audition"
    else:
        worker._assert_no_ocr()
        transcribe = phases.load_transcriber(config)
        transcript = transcribe([{"audio": str(temporary)}])[0].strip()
        provenance = "parakeet_gpu_" + phases.MODEL_REVISION
    if not transcript.strip():
        raise ValueError("The selected voice has no recognizable speech; choose a clear narrator sample")
    phases._cancel(job)
    temporary.replace(target)
    prepared = {"source_voice_sha256": source_hash, "reference_wav": str(target.resolve()),
                "reference_sha256": sha256_file(target), "reference_text": transcript, "transcript_source": provenance}
    write(receipt, prepared)
    return prepared


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("job", type=Path)
    parser.add_argument("--prepare-reference", action="store_true", required=True)
    args = parser.parse_args()
    try:
        prepare_reference(args.job, read(args.job / "drama3_reference_request.json"))
    except Exception as exc:
        write(args.job / "vibevoice_error.json", {"reason": "drama3_reference_failed", "message": str(exc)})
        raise
