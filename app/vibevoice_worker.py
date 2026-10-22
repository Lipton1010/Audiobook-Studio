"""One-GPU, resumable VibeVoice 1.5B narration worker.

This module deliberately imports VibeVoice only after planning and resume checks;
the base server and Chatterbox environment never import its model stack.
"""

import argparse
from collections import deque
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import re
from queue import Empty, Queue
from threading import Lock, Thread
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from pathlib import Path

import numpy as np
import soundfile as sf

from vibevoice_audio import mono_24k, normalize_audio
from vibevoice_plan import load_plan, normalize_text, sha256_file
from vibevoice_assembly import _ffmpeg, assemble
from vibevoice_units import repair_units, repair_limits, parent_quality, choose_repair_unit
from vibevoice_quality import assess_narration as assess, integer_words, numbered_heading_assessment, unit_assessment
import vibevoice_delivery as delivery
from gpu_oom import bisect_cuda_oom
from narration_eta import estimate_word_remaining_seconds, write_progress
import narration_review


SEGMENTS_DIR = "vibevoice_segments"
PROGRESS_FILE = "vibevoice_progress.json"
ERROR_FILE = "vibevoice_error.json"
REJECTED_DIR = "vibevoice_rejected"
UNITS_DIR = "units"
CANCEL_FILE = "cancel_flag.txt"
OVERLAP_TELEMETRY_FILE = "vibevoice_overlap.jsonl"
PREFETCH_MAX_ITEMS = 4
PREFETCH_MAX_SECONDS = 240.0
PREFETCH_MAX_BYTES = 32 * 1024 * 1024
ASCII_APOSTROPHE_PROFILE = "ascii_intra_word_apostrophe_v1"
OUTLINE_PREFIX_CASE_PROFILE = "outline_prefix_case_ascii_apostrophe_v1"
NUMBERED_OUTLINE_HEADING_PROFILE = "numbered_outline_heading_ascii_apostrophe_v1"
NUMBERED_OUTLINE_HEADING_SEED_PROFILE = "numbered_outline_heading_seed_v1"
NUMBERED_OUTLINE_HEADING_SEEDS = (101, 102, 103)
_INTRA_WORD_CURLY_APOSTROPHE = re.compile(r"(?<=[^\W\d_])’(?=[^\W\d_])")


def _overlap_telemetry(job_dir, config, event, parents=(), units=(), **detail):
    """Keep comparison timings private and free of source or transcript text."""
    if config.get("performance_telemetry") is not True:
        return
    payload = {
        "event": event,
        "monotonic": time.monotonic(),
        "parents": list(parents),
        "units": list(units),
        "count": len(units),
        **detail,
    }
    try:
        with (Path(job_dir) / OVERLAP_TELEMETRY_FILE).open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, sort_keys=True) + "\n")
    except OSError:
        pass


def _cross_parent_enabled(config):
    """Use the server's auto-performance opt-in; missing legacy config stays off."""
    return config.get("cross_parent_render_ahead") is True


def _prefetch_within_limits(rendered):
    """Bound retained provisional PCM after rendering, before it can cross a parent boundary."""
    if len(rendered) > PREFETCH_MAX_ITEMS:
        return False, "item_limit"
    seconds = 0.0
    byte_count = 0
    for _unit, _attempt, tmp, error in rendered:
        if error:
            continue
        try:
            info = sf.info(str(tmp))
            seconds += info.frames / info.samplerate
            byte_count += tmp.stat().st_size
        except Exception:
            return False, "unreadable"
    if seconds > PREFETCH_MAX_SECONDS:
        return False, "duration_limit"
    if byte_count > PREFETCH_MAX_BYTES:
        return False, "byte_limit"
    return True, {"seconds": round(seconds, 3), "bytes": byte_count}


def _prefetch_next_parent(job_dir, parent, config, unit_dir, torch, processor, model, voice):
    if narration_review.entry(job_dir, parent):
        return None
    """Render one bounded, unaccepted batch for the immediately following parent."""
    units = _units_for_parent(parent, config)
    candidates = []
    for unit in units:
        if not _valid_unit(unit_dir, unit):
            candidates.append((_profiled_unit(unit), 1))
    if not candidates or _cancelled(job_dir):
        return None
    batch = candidates[:min(PREFETCH_MAX_ITEMS, _batch_size(torch, config))]
    estimates = [unit.get("estimated_audio_seconds") for unit, _attempt in batch]
    if estimates and all(isinstance(value, (int, float)) and not isinstance(value, bool) for value in estimates):
        estimated_seconds = sum(float(value) for value in estimates)
        if estimated_seconds > PREFETCH_MAX_SECONDS:
            _overlap_telemetry(job_dir, config, "prefetch_skipped_estimate", [parent["index"]],
                               [unit["index"] for unit, _ in batch], seconds=round(estimated_seconds, 3))
            return None
    _overlap_telemetry(job_dir, config, "prefetch_render_start", [parent["index"]], [unit["index"] for unit, _ in batch])
    try:
        rendered = _render_items(torch, processor, model, voice, batch, config, unit_dir)
    except Exception as exc:
        _overlap_telemetry(job_dir, config, "prefetch_failed", [parent["index"]],
                           [unit["index"] for unit, _ in batch], error_type=type(exc).__name__)
        return None
    _overlap_telemetry(job_dir, config, "prefetch_render_end", [parent["index"]], [unit["index"] for unit, _ in batch])
    allowed, detail = _prefetch_within_limits(rendered)
    if allowed:
        _overlap_telemetry(job_dir, config, "prefetch_retained", [parent["index"]], [unit["index"] for unit, _ in batch], **detail)
        return {"parent_index": parent["index"], "rendered": rendered}
    for _unit, _attempt, tmp, error in rendered:
        if error is None:
            tmp.unlink(missing_ok=True)
    _overlap_telemetry(job_dir, config, "prefetch_discarded", [parent["index"]], [unit["index"] for unit, _ in batch], reason=detail)
    failed = [row for row in rendered if row[3] is not None]
    return {"parent_index": parent["index"], "rendered": failed} if failed else None


def _render_text(text, profile=None, render_heading=None):
    if profile is None:
        return text
    if profile in (delivery.PROFILE, delivery.INTACT_PROFILE):
        return _INTRA_WORD_CURLY_APOSTROPHE.sub("'", delivery.spoken_text(text))
    if profile == NUMBERED_OUTLINE_HEADING_PROFILE:
        source = _NUMBERED_OUTLINE_RE.fullmatch(text)
        prefix, separator, title = (render_heading or "").partition(": ")
        expected_prefix = " ".join(integer_words(int(source.group(1)))).capitalize() if source else ""
        if (not source or separator != ": " or prefix != expected_prefix
                or source.group(2).casefold() != title.casefold()):
            raise ValueError("numbered outline render heading does not match passage")
        text = render_heading
    elif profile == OUTLINE_PREFIX_CASE_PROFILE:
        if not isinstance(render_heading, str) or not render_heading:
            raise ValueError("outline render profile requires a heading")
        if text[:len(render_heading)].casefold() != render_heading.casefold():
            raise ValueError("outline render heading does not match passage")
        text = render_heading + text[len(render_heading):]
    elif profile != ASCII_APOSTROPHE_PROFILE:
        raise ValueError("unknown VibeVoice render profile")
    return _INTRA_WORD_CURLY_APOSTROPHE.sub("'", text)


def _profiled_unit(unit, profile=None):
    profile = profile or unit.get("render_profile")
    if profile is None:
        parts = delivery.delivery_parts(unit["text"])
        profile = (delivery.PROFILE if len(parts) > 1 or unit.get("spoken_text", delivery.spoken_text(unit["text"])) != unit["text"]
                   else ASCII_APOSTROPHE_PROFILE)
    render_heading = unit.get("render_heading")
    render_text = _render_text(unit.get("spoken_text", unit["text"]), profile, render_heading)
    if unit.get("scene_direction_compiled"):
        from scene_direction import render_unit
        render_text = render_unit(unit, render_text)
    return {**unit, "render_profile": profile, "render_text": render_text,
            "speaker_text": "Speaker 0: " + render_text}


def _numbered_heading_seed(passage, attempt):
    if passage.get("render_profile") != NUMBERED_OUTLINE_HEADING_PROFILE:
        return None
    if not isinstance(attempt, int) or isinstance(attempt, bool) or not 1 <= attempt <= len(NUMBERED_OUTLINE_HEADING_SEEDS):
        return None
    return NUMBERED_OUTLINE_HEADING_SEEDS[attempt - 1]


def _attempt_limit(passage, retries):
    normal_limit = int(retries) + 1
    return min(normal_limit, len(NUMBERED_OUTLINE_HEADING_SEEDS)) if passage.get("render_profile") == NUMBERED_OUTLINE_HEADING_PROFILE else normal_limit


def _render_with_numbered_heading_seed(torch, passage, attempt, render):
    seed = _numbered_heading_seed(passage, attempt)
    if seed is None:
        return render()
    with torch.random.fork_rng(devices=list(range(torch.cuda.device_count()))):
        torch.manual_seed(seed)
        torch.cuda.manual_seed_all(seed)
        return render()


def _render_text_sha256(unit, profile):
    text = _render_text(unit.get("spoken_text", unit["text"]), profile, unit.get("render_heading"))
    if unit.get("scene_direction_compiled"):
        from scene_direction import render_unit
        text = render_unit(unit, text)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _outline_render_heading(parent, config):
    """Return one verified title that repairs an all-caps outline prefix only."""
    block_types = parent.get("block_types")
    if (parent.get("heading") or not parent.get("source_pages")
            or not isinstance(block_types, list) or not block_types
            or any(block_type != "body" for block_type in block_types)):
        return None
    page = parent["source_pages"][0]
    text = parent.get("text", "")
    candidates = []
    for entry in config.get("pdf_outline") or []:
        title = " ".join(str(entry.get("title", "")).split())
        if entry.get("page") != page or not title or title == title.upper():
            continue
        prefix = text[:len(title)]
        if (prefix.casefold() == title.casefold() and prefix == prefix.upper()
                and (len(text) == len(title) or text[len(title)].isspace())):
            candidates.append(title)
    return candidates[0] if len(candidates) == 1 else None


def _units_for_parent(parent, config):
    boundary = config.get('unit_boundary_policies', {}).get(parent.get('identity'), config.get('unit_boundary_policy', 'legacy_v1'))
    limits = repair_limits(parent, config)
    units = delivery.project_units(repair_units(parent, boundary_policy=boundary, **limits), parent, config)
    if _is_numbered_heading(parent):
        units[0] = {**units[0], "numbered_heading": True}
    if config.get("backend") == "drama3":
        if boundary == 'sentences_v4':
            for unit in units:
                if len(unit.get('spoken_text', unit['text'])) > limits['max_chars']:
                    raise ValueError(f"Passage {parent['index'] + 1} has a sentence exceeding Drama 3's "
                                     f"{limits['max_chars']}-character input limit. The text was kept intact; "
                                     "review this sentence before narration.")
        from scene_direction import attach_units
        units = [{**unit, "sample_rate": 44100, "render_profile": delivery.INTACT_PROFILE} for unit in units]
        return attach_units(units, parent, config)
    numbered = _numbered_outline_heading(parent, config)
    if numbered:
        units[0] = {**units[0], "render_profile": NUMBERED_OUTLINE_HEADING_PROFILE,
                    "render_heading": numbered}
        return units
    heading = _outline_render_heading(parent, config)
    if heading and len(units[0]["text"]) >= len(heading) and units[0]["text"][:len(heading)].casefold() == heading.casefold():
        units[0] = {**units[0], "render_profile": OUTLINE_PREFIX_CASE_PROFILE,
                    "render_heading": heading}
    return units


_NUMBERED_OUTLINE_RE = re.compile(r"^0*([1-9]\d{0,2}):\s+(.+)$")


def _numbered_outline_heading(parent, config):
    if (parent.get("heading") != parent.get("text") or parent.get("block_types") != ["heading"]
            or len(parent.get("source_pages", [])) != 1):
        return None
    source = " ".join(str(parent.get("text", "")).split())
    match = _NUMBERED_OUTLINE_RE.fullmatch(source)
    if not match:
        return None
    number = int(match.group(1))
    if number > 999:
        return None
    page = parent["source_pages"][0]
    matches = []
    for entry in config.get("pdf_outline") or []:
        title = " ".join(str(entry.get("title", "")).split())
        title_match = _NUMBERED_OUTLINE_RE.fullmatch(title)
        if (entry.get("page") == page and title_match and int(title_match.group(1)) == number
                and title_match.group(2).casefold() == match.group(2).casefold()):
            matches.append(title)
    if len(matches) != 1:
        return None
    title_match = _NUMBERED_OUTLINE_RE.fullmatch(matches[0])
    return " ".join(integer_words(number)).capitalize() + ": " + title_match.group(2) if title_match else None


def _profile_attempt_key(parent, unit, profile):
    payload = {
        "parent_identity": parent["identity"], "unit_identity": unit["identity"],
        "render_profile": profile, "render_text_sha256": _render_text_sha256(unit, profile),
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest(), payload


def _profile_attempted(receipt, parent, unit, profile):
    key, _ = _profile_attempt_key(parent, unit, profile)
    return key in receipt.get("profile_attempts", {})


def _mark_profile_attempt(unit_dir, parent, unit, profile):
    """Spend one profile-specific recovery attempt before GPU generation."""
    receipt_path = _receipt_path(unit_dir, unit["index"])
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    key, payload = _profile_attempt_key(parent, unit, profile)
    attempts = receipt.setdefault("profile_attempts", {})
    if key in attempts:
        return False
    attempts[key] = payload
    _write_json(receipt_path, receipt)
    return True


def _difference_impact(report):
    return int(report.get("missing_words", 0)) + int(report.get("inserted_words", 0))


def _strict_parent_improvement(baseline, candidate):
    if candidate.get("ok"):
        return True
    before = (int(baseline.get("missing_words", 0)), int(baseline.get("inserted_words", 0)))
    after = (int(candidate.get("missing_words", 0)), int(candidate.get("inserted_words", 0)))
    return after[0] <= before[0] and after[1] <= before[1] and after != before


def _apostrophe_difference(report):
    return any("'" in word for difference in report.get("differences", [])
               for word in difference.get("expected", []) if isinstance(word, str))


def _profile_recovery_candidates(parent, units, reports, unit_dir, retries):
    """Rank exhausted legacy units whose original render contains curly apostrophes."""
    ranked = []
    for unit, report in zip(units, reports):
        try:
            receipt = json.loads(_receipt_path(unit_dir, unit["index"]).read_text(encoding="utf-8"))
        except (OSError, ValueError, KeyError):
            continue
        profile = ASCII_APOSTROPHE_PROFILE
        if (receipt.get("render_profile") is not None
                or not isinstance(receipt.get("profile_attempts", {}), dict)
                or int(receipt.get("attempt", 0)) < retries + 1
                or _render_text(unit["text"], profile) == unit["text"]
                or not _apostrophe_difference(report)
                or _profile_attempted(receipt, parent, unit, profile)):
            continue
        ranked.append((-_difference_impact(report), -len(report.get("differences", [])),
                       unit["unit_index"], unit))
    return [item[-1] for item in sorted(ranked)]


def _write_json(path, value):
    temporary = path.with_suffix(path.suffix + f".tmp{os.getpid()}")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def _progress(job_dir, done, total, shard, status, passage_index=None, attempt=None, metrics=None):
    payload = {"done": int(done), "total": int(total), "shard": int(shard), "status": str(status)}
    if passage_index is not None:
        payload["passage_index"] = int(passage_index)
    if attempt is not None:
        payload["attempt"] = int(attempt)
    if metrics:
        payload.update(metrics)
    # Progress is advisory. A browser/antivirus read must not abort narration.
    write_progress(Path(job_dir) / PROGRESS_FILE, payload)


def _cancelled(job_dir):
    return (Path(job_dir) / CANCEL_FILE).exists()


def _receipt_path(seg_dir, index):
    return seg_dir / f"seg_{index:06d}.json"


def _wav_path(seg_dir, index):
    return seg_dir / f"seg_{index:06d}.wav"


def _archive_replaced_heading_wav(path, rejected):
    """Keep active numbered-heading audio until its replacement commits."""
    if path.exists():
        rejected.mkdir(exist_ok=True)
        shutil.copy2(path, rejected / f"{path.stem}_replaced_numbered_heading_{time.time_ns()}.wav")


def _is_numbered_heading(passage):
    match = _NUMBERED_OUTLINE_RE.fullmatch(" ".join(str(passage.get("text", "")).split()))
    return bool(passage.get("heading") and match and int(match.group(1)) <= 999)


def _valid_numbered_heading_seed(metadata):
    attempt = metadata.get("render_attempt")
    seed = _numbered_heading_seed({"render_profile": NUMBERED_OUTLINE_HEADING_PROFILE}, attempt)
    return bool(seed is not None
                and metadata.get("render_seed_profile") == NUMBERED_OUTLINE_HEADING_SEED_PROFILE
                and metadata.get("render_seed") == seed)


def _valid_segment(seg_dir, passage):
    config = None
    units = None
    if 'unit_index' not in passage and 'text' in passage:
        config_path = seg_dir.parent / 'vibevoice_config.json'
        if config_path.exists():
            try:
                config = json.loads(config_path.read_text(encoding='utf-8'))
                units = _units_for_parent(passage, config)
            except (ValueError, KeyError, OSError, TypeError):
                return False
            if units and all(not u.get('spoken_text', u['text']) for u in units):
                return True  # Source-bound omissions have no audio checkpoint.
    sample_rate = passage.get("sample_rate", 24000)
    wav, receipt = _wav_path(seg_dir, passage["index"]), _receipt_path(seg_dir, passage["index"])
    if not wav.is_file() or not receipt.is_file():
        return False
    try:
        saved = json.loads(receipt.read_text(encoding="utf-8"))
        info = sf.info(str(wav))
        audio, sr = sf.read(str(wav), dtype="float32")
    except Exception:
        return False
    if units is not None:
        try:
            manifest = saved.get('unit_manifest')
            if manifest is not None:
                if [(u['index'], u['identity']) for u in units] != [(u['index'], u['identity']) for u in manifest]:
                    return False
                for unit, entry in zip(units, manifest):
                    if not unit.get('spoken_text', unit['text']):
                        if entry != {'index': unit['index'], 'identity': unit['identity'], 'omitted': True}:
                            return False
                        continue
                    unit_receipt = json.loads(_receipt_path(seg_dir / UNITS_DIR, unit['index']).read_text(encoding='utf-8'))
                    if (not delivery.receipt_matches_projection(unit_receipt, unit)
                            or unit_receipt.get('force_regenerate')
                            or unit_receipt.get('wav_sha256') != entry['wav_sha256']
                            or sha256_file(_wav_path(seg_dir / UNITS_DIR, unit['index'])) != entry['wav_sha256']):
                        return False
                    if config.get("backend") == "drama3":
                        if not _valid_unit(seg_dir / UNITS_DIR, unit):
                            return False
            else:
                legacy = _units_for_parent(passage, {**config, 'unit_boundary_policy': 'legacy_v1'})
                if ([u['identity'] for u in legacy] != [u['identity'] for u in units]
                        or any(u.get('spoken_text', u['text']) != u['text'] or u.get('render_profile') == delivery.INTACT_PROFILE for u in units)):
                    return False
        except (ValueError, KeyError, OSError, TypeError):
            return False
    if _is_numbered_heading(passage):
        reports = saved.get("unit_reports")
        if not isinstance(reports, list):
            return False
        transcript = " ".join(str(report.get("transcript", "")).strip() for report in reports).strip()
        if not numbered_heading_assessment(passage["text"], transcript).get("ok"):
            return False
        manifest = saved.get("unit_manifest")
        if manifest is not None and not isinstance(manifest, list):
            return False
        seed_fields = {"render_seed_profile", "render_seed", "render_attempt"}
        seeded = [entry for entry in (manifest or []) if isinstance(entry, dict) and seed_fields & set(entry)]
        if seeded and (len(seeded) != 1 or not _valid_numbered_heading_seed(seeded[0])):
            return False
        for entry in seeded:
            try:
                unit_receipt = json.loads(_receipt_path(seg_dir / UNITS_DIR, entry["index"]).read_text(encoding="utf-8"))
            except Exception:
                return False
            if (unit_receipt.get("render_profile") != NUMBERED_OUTLINE_HEADING_PROFILE
                    or not isinstance(unit_receipt.get("attempt"), int)
                    or isinstance(unit_receipt.get("attempt"), bool)
                    or unit_receipt.get("attempt") != unit_receipt.get("render_attempt")
                    or any(unit_receipt.get(key) != entry.get(key) for key in seed_fields)):
                return False
        for entry in manifest or []:
            if not isinstance(entry, dict):
                continue
            receipt_path = _receipt_path(seg_dir / UNITS_DIR, entry.get("index"))
            if not receipt_path.is_file():
                continue
            try:
                unit_receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            except Exception:
                return False
            if unit_receipt.get("render_profile") == NUMBERED_OUTLINE_HEADING_PROFILE and not any(
                    seeded_entry.get("index") == entry.get("index") for seeded_entry in seeded):
                return False
    return bool(
        saved.get("identity") == passage["identity"]
        and not saved.get("force_regenerate")
        and saved.get("wav_sha256") == sha256_file(wav)
        and info.samplerate == sample_rate
        and info.channels == 1
        and info.frames > sample_rate / 10
        and sr == sample_rate and audio.ndim == 1
        and np.isfinite(audio).all() and np.max(np.abs(audio)) > 0.001
    )


def _assert_no_ocr():
    try:
        result = subprocess.run(["ollama", "ps"], capture_output=True, text=True, check=False)
    except FileNotFoundError:
        # Ollama is optional. If its executable is absent, this machine cannot
        # be running this project's OCR stage.
        return
    if result.returncode:
        raise RuntimeError("cannot verify OCR is idle because `ollama ps` failed; do not start VibeVoice")
    if len([line for line in result.stdout.splitlines() if line.strip()]) > 1:
        raise RuntimeError("OCR is active; VibeVoice narration must wait for exclusive GPU access")


def _load_model(config):
    cache_dir = config.get("cache_dir")
    if cache_dir:
        # The processor resolves Qwen's tokenizer through Hugging Face even
        # when the VibeVoice weights are a local directory. Set this before
        # either VibeVoice or transformers imports anything.
        os.environ["HF_HOME"] = str(cache_dir)
        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["TRANSFORMERS_OFFLINE"] = "1"
    import torch

    if not torch.cuda.is_available():
        raise RuntimeError("VibeVoice requires an NVIDIA CUDA GPU")
    torch.set_num_threads(4)
    render_workers = config.get("render_workers", 1)
    if type(render_workers) is not int or render_workers not in (1, 2):
        raise ValueError("Render workers must be one or two")
    memory_fraction = 0.85 if render_workers == 1 else 0.40
    torch.cuda.set_per_process_memory_fraction(memory_fraction)
    model_path = config.get("model_dir")
    if not model_path:
        raise RuntimeError("VibeVoice model_dir is not configured")
    print(
        "VibeVoice runtime: "
        f"model={config['model_id']} revision={config['model_revision']} "
        f"tokenizer={config['tokenizer_revision']} dtype={config['dtype']} "
        f"cfg={config['cfg_scale']} steps={config['ddpm_steps']} "
        f"attention={config['attention']} allocator={memory_fraction:.0%} cpu_threads=4 "
        f"fingerprint={config['model_fingerprint']}",
        flush=True,
    )
    if config.get("inference_backend") == "compiled":
        import vibevoice_hf
        os.environ.setdefault("TORCHINDUCTOR_CACHE_DIR", str(Path(model_path).parent / "inductor_cache"))
        processor, model = vibevoice_hf.load(torch, config)
        return torch, processor, model
    from vibevoice.modular.modeling_vibevoice_inference import VibeVoiceForConditionalGenerationInference
    from vibevoice.processor.vibevoice_processor import VibeVoiceProcessor
    processor = VibeVoiceProcessor.from_pretrained(
        model_path, revision=config["tokenizer_revision"], local_files_only=True
    )
    model = VibeVoiceForConditionalGenerationInference.from_pretrained(
        model_path, torch_dtype=torch.bfloat16, device_map="cuda", attn_implementation="sdpa"
    ).eval()
    model.set_ddpm_inference_steps(int(config["ddpm_steps"]))
    return torch, processor, model


class _QualityChecker:
    def __init__(self, job_dir, config):
        python, model = config.get("quality_python"), config.get("quality_model")
        if not python or not model:
            raise RuntimeError("VibeVoice quality verification requires quality_python and quality_model")
        self.job_dir, self.config = Path(job_dir), config
        self.responses, self.stderr, self.stderr_lock, self.process_lock, self.drain_threads = Queue(), deque(maxlen=100), Lock(), Lock(), []
        command = [python, "-X", "utf8", str(Path(__file__).with_name("vibevoice_quality.py")), "--serve", "--model", str(model)]
        env = dict(os.environ, PYTHONIOENCODING="utf-8")
        self.process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                        stderr=subprocess.PIPE, text=True, encoding="utf-8", bufsize=1, env=env)
        try:
            self._drain(self.process.stdout, self.responses)
            self._drain(self.process.stderr, self.stderr)
            if not self._wait_response("quality verifier startup timed out").get("ready"):
                raise RuntimeError("quality verifier did not confirm startup")
        except BaseException:
            self.close()
            raise

    @staticmethod
    def _read(stream, target, lock=None):
        for line in iter(stream.readline, ""):
            if hasattr(target, "put"):
                target.put(line)
            else:
                with lock:
                    target.append(line[-2048:])

    def _drain(self, stream, target):
        lock = self.stderr_lock if target is self.stderr else None
        thread = Thread(target=self._read, args=(stream, target, lock), daemon=True)
        self.drain_threads.append(thread)
        thread.start()

    def _detail(self):
        with self.stderr_lock:
            lines = [line.strip() for line in self.stderr]
            self.stderr.clear()
        return "\n".join(line for line in lines if line)

    def _wait_response(self, timeout_error):
        process = self.process
        if process is None:
            raise RuntimeError("quality verifier is closed")
        deadline = time.monotonic() + int(self.config.get("quality_timeout_seconds", 300))
        while True:
            if _cancelled(self.job_dir):
                self.close()
                raise SystemExit(2)
            if time.monotonic() >= deadline:
                self.close()
                raise RuntimeError(timeout_error)
            try:
                line = self.responses.get(timeout=0.1)
            except Empty:
                if process.poll() is not None:
                    detail = self._detail()
                    raise RuntimeError(f"quality verifier failed (exit {process.returncode}): {detail}")
                continue
            try:
                response = json.loads(line)
            except json.JSONDecodeError:
                raise RuntimeError("quality verifier returned invalid JSON")
            if response.get("error"):
                raise RuntimeError(f"quality verifier failed: {response['error']}")
            return response

    def check(self, wav_path, passage, attempt_label):
        started = time.monotonic() if self.config.get("performance_telemetry") is True else None
        report = self.job_dir / REJECTED_DIR / f"seg_{passage['index']:06d}_{attempt_label}.quality.json"
        request = {"audio": str(wav_path), "expected": passage.get("spoken_text", passage["text"]), "report": str(report),
                   "major_words": int(self.config.get("quality_major_words", 5))}
        process = self.process
        if process is None:
            raise RuntimeError("quality verifier is closed")
        try:
            process.stdin.write(json.dumps(request) + "\n")
            process.stdin.flush()
        except (BrokenPipeError, OSError) as exc:
            raise RuntimeError(f"quality verifier failed: {exc}") from exc
        response = self._wait_response("quality verifier timed out")
        if Path(response.get("report", "")) != report:
            raise RuntimeError("quality verifier returned an unexpected report path")
        if started is not None:
            _overlap_telemetry(self.job_dir, self.config, "quality_complete",
                               units=[passage["index"]], elapsed_seconds=time.monotonic() - started)
        return bool(response.get("ok")), report

    def close(self):
        with self.process_lock:
            process, self.process = self.process, None
        if process is None:
            return
        try:
            if process.poll() is None:
                process.kill()
            process.wait(timeout=10)
        except Exception:
            pass
        for stream in (process.stdin, process.stdout, process.stderr):
            try:
                if stream:
                    stream.close()
            except Exception:
                pass
        for thread in self.drain_threads:
            thread.join(timeout=1)


def _quality_check(checker, wav_path, passage, attempt_label):
    return checker.check(wav_path, passage, attempt_label)


def _wait_render(future, job_dir):
    """Keep cancellation responsive while the single GPU owner finishes a batch."""
    while True:
        if _cancelled(job_dir):
            raise SystemExit(2)
        try:
            return future.result(timeout=0.1)
        except FutureTimeout:
            if future.done():
                raise


class _QualityCheck:
    def __init__(self, checker, wav_path, passage, attempt_label):
        self.result, self.error = None, None
        def run():
            try:
                self.result = _quality_check(checker, wav_path, passage, attempt_label)
            except BaseException as exc:
                self.error = exc
        self.thread = Thread(target=run, daemon=True)
        self.thread.start()

    def wait(self, job_dir, checker):
        while self.thread.is_alive():
            if _cancelled(job_dir):
                checker.close()
                self.thread.join(timeout=10)
                raise SystemExit(2)
            self.thread.join(timeout=0.1)
        if self.error:
            raise self.error
        return self.result


def _render_one(torch, processor, model, voice, passage, config, tmp_path):
    started = time.perf_counter()
    _assert_no_ocr()
    if config.get("inference_backend") == "compiled":
        import vibevoice_hf
        with torch.inference_mode():
            outputs, capped = vibevoice_hf.generate(torch, processor, model, voice, [passage], config)
    else:
        parsed = processor._parse_script(passage["speaker_text"])
        if len(parsed) != 1 or normalize_text(parsed[0][1]) != passage.get("render_text", passage["text"]):
            raise RuntimeError("VibeVoice processor did not preserve the complete passage text")
        inputs = processor(text=[passage["speaker_text"]], voice_samples=[[voice]], padding=True, return_tensors="pt", return_attention_mask=True)
        if inputs["input_ids"].shape[-1] > int(config["max_input_tokens"]):
            raise RuntimeError("passage exceeds VibeVoice input-token ceiling; rebuild the plan with smaller passages")
        inputs = {key: value.to("cuda") if torch.is_tensor(value) else value for key, value in inputs.items()}
        with torch.inference_mode():
            result = model.generate(**inputs, cfg_scale=float(config["cfg_scale"]), tokenizer=processor.tokenizer, max_new_tokens=int(config["max_new_tokens"]), do_sample=False)
        outputs, capped = result.speech_outputs, result.reach_max_step_sample
    torch.cuda.synchronize()
    if bool(capped.any()):
        raise RuntimeError("generation reached the 4000-token cap")
    sf.write(str(tmp_path), _normalize_wav(outputs[0], config), 24000, subtype="PCM_16")
    return {"text": passage.get("render_text", passage["text"]), "frames": sf.info(str(tmp_path)).frames,
            "sample_rate": 24000, "seconds": sf.info(str(tmp_path)).duration,
            "elapsed_seconds": time.perf_counter() - started, "cap_hit": False,
            "stop_reason": "non_cap_completion", "max_new_tokens": int(config["max_new_tokens"])}


def _prepare_voice(job_dir, config, plan):
    source = Path(config["reference_wav"])
    target = Path(job_dir) / f"vibevoice_voice_{plan['voice_sha256'][:16]}.wav"
    if not target.exists():
        temp = target.with_suffix(f".tmp{os.getpid()}.wav")
        try:
            raw, source_sr = sf.read(str(source), dtype="float32", always_2d=True)
            converted = mono_24k(raw, source_sr)
            sf.write(str(temp), converted, 24000, subtype="PCM_16")
        except Exception:
            command = [_ffmpeg(), "-nostdin", "-y", "-v", "error", "-i", str(source), "-ac", "1", "-ar", "24000", str(temp)]
            subprocess.run(command, check=True, capture_output=True, text=True)
        temp.replace(target)
    voice, sr = sf.read(str(target), dtype="float32")
    if sr != 24000 or voice.ndim != 1 or voice.size == 0 or not np.isfinite(voice).all():
        raise RuntimeError("could not prepare a finite mono 24 kHz VibeVoice reference")
    return voice


def _recoverable_render_error(exc):
    return str(exc).startswith(("generation reached", "generated audio was", "loudness normalization"))


def _batch_size(torch, config=None):
    """Batch only on the measured 24 GiB class; smaller cards remain serial."""
    if (config or {}).get("batch_preference") == "conservative":
        return 1
    size = (config or {}).get("native_batch_size", 2)
    if type(size) is not int or not 1 <= size <= 4:
        size = 2
    try:
        return size if int(torch.cuda.get_device_properties(0).total_memory) >= 23 * 1024 ** 3 else 1
    except Exception:
        return 1


def _normalize_wav(wav_tensor, config):
    if wav_tensor is None:
        raise RuntimeError("generated audio was empty, nonfinite, or silent")
    wav = wav_tensor.detach().float().cpu().numpy().squeeze()
    return normalize_audio(wav, 24000, config.get("target_lufs", -21.0))


def _render_batch(torch, processor, model, voice, items, config, unit_dir):
    """Render a bounded native batch and retain each row's own outcome."""
    _assert_no_ocr()
    started = time.perf_counter()
    items = list(items)
    passages = [item[0] for item in items]
    if len(items) != 1 and any(passage.get("render_profile") == NUMBERED_OUTLINE_HEADING_PROFILE for passage in passages):
        raise RuntimeError("numbered outline headings must render as one seeded row")
    if config.get("inference_backend") == "compiled":
        import vibevoice_hf
        def generate():
            with torch.inference_mode():
                return vibevoice_hf.generate(torch, processor, model, voice, passages, config)
        outputs, capped = (_render_with_numbered_heading_seed(torch, passages[0], items[0][1], generate)
                           if len(items) == 1 else generate())
        torch.cuda.synchronize()
        capped = capped.detach().cpu().tolist()
    else:
        for passage in passages:
            parsed = processor._parse_script(passage["speaker_text"])
            if len(parsed) != 1 or normalize_text(parsed[0][1]) != passage.get("render_text", passage["text"]):
                raise RuntimeError("VibeVoice processor did not preserve the complete passage text")
        inputs = processor(text=[p["speaker_text"] for p in passages], voice_samples=[[voice] for _ in passages],
                           padding=True, return_tensors="pt", return_attention_mask=True)
        counts = inputs["attention_mask"].sum(dim=-1).tolist()
        if any(count > int(config["max_input_tokens"]) for count in counts):
            raise RuntimeError("passage exceeds VibeVoice input-token ceiling; rebuild the plan with smaller passages")
        inputs = {key: value.to("cuda") if torch.is_tensor(value) else value for key, value in inputs.items()}
        def generate():
            with torch.inference_mode():
                return model.generate(**inputs, cfg_scale=float(config["cfg_scale"]), tokenizer=processor.tokenizer,
                                      max_new_tokens=int(config["max_new_tokens"]), do_sample=False)
        result = (_render_with_numbered_heading_seed(torch, passages[0], items[0][1], generate)
                  if len(items) == 1 else generate())
        torch.cuda.synchronize()
        outputs = result.speech_outputs
        capped = result.reach_max_step_sample.detach().cpu().tolist()
    if outputs is None or len(outputs) != len(items) or len(capped) != len(items):
        raise RuntimeError("VibeVoice native batch returned an unexpected number of rows")
    rendered = []
    for (passage, attempt), output, cap_hit in zip(items, outputs, capped):
        tmp = _wav_path(unit_dir, passage["index"]).with_suffix(f".tmp{os.getpid()}.wav")
        error = None
        try:
            if cap_hit:
                raise RuntimeError("generation reached the 4000-token cap")
            sf.write(str(tmp), _normalize_wav(output, config), 24000, subtype="PCM_16")
        except Exception as exc:
            tmp.unlink(missing_ok=True)
            error = exc
        rendered_passage = dict(passage)
        if config.get("record_fragments"):
            rendered_passage["generation"] = [{"text": passage.get("render_text", passage["text"]),
                "frames": sf.info(str(tmp)).frames if error is None else None,
                "seconds": sf.info(str(tmp)).duration if error is None else None,
                "sample_rate": 24000, "cap_hit": bool(cap_hit),
                "stop_reason": "cap" if cap_hit else "non_cap_completion",
                "max_new_tokens": int(config["max_new_tokens"]),
                "elapsed_seconds": time.perf_counter() - started,
                "timing_scope": "batch", "error": str(error) if error else None}]
        seed = _numbered_heading_seed(passage, attempt)
        if seed is not None:
            rendered_passage["render_seed"] = seed
        rendered.append((rendered_passage, attempt, tmp, error))
    return rendered


def _valid_unit(unit_dir, unit, allow_needs_repair=False, allow_review=False):
    if not unit.get('spoken_text', unit['text']):
        return True
    if not _valid_segment(unit_dir, unit):
        return False
    try:
        receipt = json.loads(_receipt_path(unit_dir, unit["index"]).read_text(encoding="utf-8"))
        if unit.get("sample_rate") == 44100:
            from drama3 import validate_generation
            validate_generation(receipt.get("generation"), unit)
        report = Path(receipt["quality_report"])
        payload = report.read_bytes()
        parsed = json.loads(payload)
        if unit.get("sample_rate") == 44100 and parsed.get("generation") != receipt.get("generation"):
            return False
        assessment = unit_assessment(unit, parsed)
        profile = receipt.get("render_profile")
        if (unit.get("render_profile") == NUMBERED_OUTLINE_HEADING_PROFILE
                and profile not in (None, ASCII_APOSTROPHE_PROFILE, NUMBERED_OUTLINE_HEADING_PROFILE)):
            return False
        if (unit.get("render_profile") != NUMBERED_OUTLINE_HEADING_PROFILE
                and unit.get("render_profile") and profile is not None and profile != unit["render_profile"]):
            return False
        if profile not in (None, ASCII_APOSTROPHE_PROFILE, OUTLINE_PREFIX_CASE_PROFILE, NUMBERED_OUTLINE_HEADING_PROFILE, delivery.PROFILE, delivery.INTACT_PROFILE):
            return False
        if profile in (OUTLINE_PREFIX_CASE_PROFILE, NUMBERED_OUTLINE_HEADING_PROFILE) and receipt.get("render_heading") != unit.get("render_heading"):
            return False
        if not isinstance(receipt.get("profile_attempts", {}), dict):
            return False
        valid_profile = delivery.receipt_matches_projection(receipt, unit)
        if profile is not None:
            valid_profile = valid_profile and receipt.get("render_text_sha256") == _render_text_sha256(unit, profile)
        valid_seed = True
        if profile == NUMBERED_OUTLINE_HEADING_PROFILE:
            valid_seed = _valid_numbered_heading_seed(receipt)
            valid_seed = bool(valid_seed and isinstance(receipt.get("attempt"), int)
                              and not isinstance(receipt.get("attempt"), bool)
                              and receipt.get("attempt") == receipt.get("render_attempt"))
    except Exception:
        return False
    return bool(valid_profile and valid_seed and not receipt.get("force_regenerate") and not receipt.get("listen_again")
                and (allow_needs_repair or not receipt.get("needs_repair"))
                and receipt.get("report_sha256") == sha256_file(report)
                and receipt.get("unit_index") == unit["unit_index"]
                and receipt.get("parent_index") == unit["parent_index"]
                and receipt.get("identity") == unit["identity"]
                and receipt.get("text_sha256") == unit["text_sha256"]
                and receipt.get("report_identity") == unit["identity"]
                and receipt.get("report_wav_sha256") == receipt.get("wav_sha256")
                and parsed.get("unit_identity") == unit["identity"]
                and parsed.get("unit_text_sha256") == unit["text_sha256"]
                and parsed.get("audio_sha256") == receipt.get("wav_sha256")
                and isinstance(parsed.get("transcript"), str)
                and (assessment.get("ok") or (allow_review and assessment.get('review_required'))
                     or narration_review.approved(receipt, unit)))


def _recover_parent_from_units(job_dir, parent, units, unit_dir, seg_dir):
    """Reuse a fully validated unit checkpoint after a checker-only correction."""
    if not _apply_listening_decisions(job_dir, parent, units, unit_dir):
        return False
    if not all(_valid_unit(unit_dir, unit, allow_needs_repair=True) for unit in units):
        return False
    reports = [_unit_report(unit_dir, unit) for unit in units]
    aggregate = parent_quality(parent, reports, units=units)
    if not aggregate["ok"]:
        return False
    if _cancelled(job_dir):
        raise SystemExit(2)
    _assemble_parent_from_units(parent, units, unit_dir, seg_dir, aggregate)
    for unit in units:
        if _cancelled(job_dir):
            raise SystemExit(2)
        if not unit.get('spoken_text', unit['text']):
            continue
        receipt_path = _receipt_path(unit_dir, unit["index"])
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        if receipt.get("needs_repair"):
            receipt["needs_repair"] = False
            _write_json(receipt_path, receipt)
    return True


def _apply_listening_decisions(job_dir, parent, units, unit_dir):
    data = narration_review.entry(job_dir, parent)
    if data is None:
        return True
    detail = narration_review.detail(job_dir, parent["index"])
    if detail["unresolved_count"]:
        return False
    pending = unit_dir.parent / narration_review.CANDIDATES_DIR
    for unit in units:
        if not unit.get('spoken_text', unit['text']):
            continue
        if unit["index"] not in data.get("candidates", []):
            continue
        receipt = json.loads(_receipt_path(pending, unit["index"]).read_text(encoding="utf-8"))
        if receipt.get("force_regenerate"):
            continue
        if not _valid_unit(pending, unit):
            raise RuntimeError("The reviewed clip no longer passes audio validation. Reopen audio review.")
        if _cancelled(job_dir):
            raise SystemExit(2)
        archive = job_dir / REJECTED_DIR
        archive.mkdir(exist_ok=True)
        label = time.time_ns()
        for existing in (_wav_path(unit_dir, unit["index"]), _receipt_path(unit_dir, unit["index"])):
            if existing.exists():
                shutil.copy2(existing, archive / f"{existing.stem}_before_review_{label}{existing.suffix}")
        target = _wav_path(unit_dir, unit["index"])
        temp = target.with_suffix(".review.tmp.wav")
        shutil.copy2(_wav_path(pending, unit["index"]), temp)
        temp.replace(target)
        _write_json(_receipt_path(unit_dir, unit["index"]), receipt)
    # Decisions now live in the exact unit receipts; a later failed attempt
    # creates a fresh review instead of reviving an obsolete review screen.
    narration_review.save_entries(job_dir, [record for record in narration_review.entries(job_dir)
                                            if record["parent"] != parent])
    return True


def _unit_report(unit_dir, unit):
    if not unit.get('spoken_text', unit['text']):
        return {**assess('', ''), 'unit_index': unit['unit_index'], 'transcript': '', 'omitted': True}
    receipt = json.loads(_receipt_path(unit_dir, unit["index"]).read_text(encoding="utf-8"))
    saved = json.loads(Path(receipt["quality_report"]).read_text(encoding="utf-8"))
    report = unit_assessment(unit, saved)
    report["transcript"] = saved.get("transcript", "")
    report["unit_index"] = unit["unit_index"]
    if narration_review.approved(receipt, unit):
        report["raw_assessment"] = dict(report)
        report.pop("comparison_transcript", None)
        report["transcript"] = unit.get("spoken_text", unit["text"])
        report["listening_approval"] = receipt["listening_approval"]
        report["ok"] = True
        report.update(differences=[], major=[], missing_words=0, inserted_words=0)
    return report


def _reported_unit(unit, report_path):
    saved = json.loads(Path(report_path).read_text(encoding="utf-8"))
    report = unit_assessment(unit, saved)
    report["transcript"] = saved.get("transcript", "")
    report["unit_index"] = unit["unit_index"]
    return report


def _publish_unit(unit_dir, passage, tmp, report, attempt):
    final = _wav_path(unit_dir, passage["index"])
    wav_sha256 = sha256_file(tmp)
    report_payload = json.loads(Path(report).read_text(encoding="utf-8"))
    report_payload['comparison_policy'] = unit_assessment(passage, report_payload).get('comparison_policy', 'numbered_heading_v1')
    report_payload.update({"unit_identity": passage["identity"],
                           "unit_text_sha256": passage["text_sha256"],
                           "expected_spoken_sha256": delivery.text_hash(passage.get("spoken_text", passage["text"])),
                           "audio_sha256": wav_sha256})
    if passage.get('render_model'):
        report_payload['render_model'] = passage['render_model']
    _write_json(Path(report), report_payload)
    if _cancelled(unit_dir.parent.parent):
        raise SystemExit(2)
    prior_receipt = _receipt_path(unit_dir, passage["index"])
    if final.exists() and prior_receipt.exists():
        previous = json.loads(prior_receipt.read_text(encoding="utf-8"))
        if previous.get('wav_sha256') != wav_sha256 or previous.get('force_regenerate') or previous.get('listening_approval'):
            archive = unit_dir.parent.parent / REJECTED_DIR
            archive.mkdir(exist_ok=True)
            reason = 'listening_retry' if previous.get('force_regenerate') or previous.get('listening_approval') else 'replacement'
            stem = f"{final.stem}_before_{reason}_{time.time_ns()}"
            shutil.copy2(final, archive / f"{stem}.wav")
            shutil.copy2(prior_receipt, archive / f"{stem}.json")
    if passage.get("numbered_heading"):
        _archive_replaced_heading_wav(final, unit_dir.parent.parent / REJECTED_DIR)
    if _cancelled(unit_dir.parent.parent):
        raise SystemExit(2)
    tmp.replace(final)
    receipt = {
        "identity": passage["identity"], "text_sha256": passage["text_sha256"],
        "wav_sha256": wav_sha256, "quality_report": str(report),
        "report_sha256": sha256_file(report), "parent_index": passage["parent_index"],
        "unit_index": passage["unit_index"], "attempt": attempt,
        "report_identity": passage["identity"], "report_wav_sha256": wav_sha256,
        "spoken_text_sha256": delivery.text_hash(passage.get("spoken_text", passage["text"])),
        "render_policy_sha256": delivery.policy_hash(passage.get("render_profile")),
    }
    if report_payload.get("generation"):
        receipt["generation"] = report_payload["generation"]
    if passage.get('render_model'):
        receipt['render_model'] = passage['render_model']
    if passage.get("render_profile"):
        previous = _receipt_path(unit_dir, passage["index"])
        if previous.exists():
            prior_payload = json.loads(previous.read_text(encoding="utf-8"))
            if prior_payload.get("profile_attempts"):
                receipt["profile_attempts"] = prior_payload["profile_attempts"]
        receipt.update(render_profile=passage["render_profile"],
                       render_text_sha256=_render_text_sha256(passage, passage["render_profile"]))
        if passage.get("render_heading"):
            receipt["render_heading"] = passage["render_heading"]
        if passage["render_profile"] == NUMBERED_OUTLINE_HEADING_PROFILE:
            seed = _numbered_heading_seed(passage, attempt)
            if seed is None or passage.get("render_seed") != seed:
                raise ValueError("numbered outline heading has no scheduled render seed")
            receipt.update(render_seed_profile=NUMBERED_OUTLINE_HEADING_SEED_PROFILE,
                           render_seed=seed, render_attempt=attempt)
    _write_json(_receipt_path(unit_dir, passage["index"]), receipt)


def _assemble_parent_from_units(parent, units, unit_dir, seg_dir, aggregate):
    """Preserve unit timing and soften only five milliseconds at each internal join."""
    temp = _wav_path(seg_dir, parent["index"]).with_suffix(f".tmp{os.getpid()}.wav")
    final = _wav_path(seg_dir, parent["index"])
    audio = []
    sample_rate = parent.get("sample_rate", 24000)
    try:
        audible = [u for u in units if u.get('spoken_text', u['text'])]
        for position, unit in enumerate(audible):
            wav, sr = sf.read(str(_wav_path(unit_dir, unit["index"])), dtype="float32")
            if sr != sample_rate or wav.ndim != 1:
                raise RuntimeError(f"accepted narration unit is not mono {sample_rate} Hz")
            fade = round(sample_rate * 0.005)
            ramp = np.linspace(0.0, 1.0, fade, dtype=np.float32)
            if position:
                wav[:fade] *= ramp
            if position + 1 < len(audible):
                wav[-fade:] *= ramp[::-1]
            audio.append(wav)
        sf.write(str(temp), np.concatenate(audio), sample_rate, subtype="PCM_16")
        if not aggregate.get("ok"):
            raise RuntimeError("cannot publish a parent that failed quality")
        if _cancelled(seg_dir.parent):
            raise SystemExit(2)
        if _is_numbered_heading(parent):
            _archive_replaced_heading_wav(final, seg_dir.parent / REJECTED_DIR)
        receipt_path = _receipt_path(seg_dir, parent["index"])
        if final.exists() and receipt_path.exists():
            previous = json.loads(receipt_path.read_text(encoding="utf-8"))
            if previous.get("force_regenerate"):
                archive = seg_dir.parent / REJECTED_DIR
                archive.mkdir(exist_ok=True)
                stem = f"{final.stem}_before_requested_update_{time.time_ns()}"
                shutil.copy2(final, archive / f"{stem}.wav")
                shutil.copy2(receipt_path, archive / f"{stem}.json")
        if _cancelled(seg_dir.parent):
            raise SystemExit(2)
        temp.replace(final)
    finally:
        temp.unlink(missing_ok=True)
    manifest = []
    for unit in units:
        if not unit.get('spoken_text', unit['text']):
            manifest.append({'index': unit['index'], 'identity': unit['identity'], 'omitted': True})
            continue
        entry = {"index": unit["index"], "identity": unit["identity"],
                 "wav_sha256": sha256_file(_wav_path(unit_dir, unit["index"]))}
        if _is_numbered_heading(parent):
            receipt = json.loads(_receipt_path(unit_dir, unit["index"]).read_text(encoding="utf-8"))
            if receipt.get("render_profile") == NUMBERED_OUTLINE_HEADING_PROFILE:
                entry.update(render_seed_profile=receipt.get("render_seed_profile"),
                             render_seed=receipt.get("render_seed"), render_attempt=receipt.get("render_attempt"))
        manifest.append(entry)
    reports = [_unit_report(unit_dir, unit) for unit in units]
    _write_json(_receipt_path(seg_dir, parent["index"]), {
        "identity": parent["identity"], "text_sha256": parent["text_sha256"],
        "wav_sha256": sha256_file(final), "unit_manifest": manifest,
        "unit_reports": reports, "parent_quality": aggregate, "unit_join_fade_ms": 5,
    })


def _render_items(torch, processor, model, voice, items, config, unit_dir):
    if any(unit.get("render_profile") == delivery.PROFILE for unit, _ in items):
        rendered = []
        for unit, attempt in items:
            if unit.get("render_profile") != delivery.PROFILE:
                rendered.extend(_render_items(torch, processor, model, voice, [(unit, attempt)], config, unit_dir))
                continue
            tmp = _wav_path(unit_dir, unit["index"]).with_suffix(f".tmp{os.getpid()}.wav")
            parts = delivery.delivery_parts(unit["render_text"])
            clips = []
            diagnostics = []
            error = None
            try:
                for index, part in enumerate(parts):
                    if _cancelled(unit_dir.parent.parent):
                        raise SystemExit(2)
                    try:
                        os.utime(unit_dir.parent.parent / PROGRESS_FILE, None)
                    except OSError:
                        pass
                    fragment = {**unit, "text": part["text"], "render_text": part["text"],
                                "speaker_text": "Speaker 0: " + part["text"]}
                    started = time.perf_counter()
                    diagnostic = _render_one(torch, processor, model, voice, fragment, config, tmp)
                    if config.get("record_fragments"):
                        diagnostics.append({**(diagnostic or {}), "fragment": index,
                                            "aside": part["aside"], "start_frame": sum(len(clip) for clip in clips) + (4800 if index else 0)})
                    audio, sr = sf.read(str(tmp), dtype="float32")
                    ramp = np.linspace(0.0, 1.0, 120, dtype=np.float32)
                    if index:
                        audio[:120] *= ramp
                    if index + 1 < len(parts):
                        audio[-120:] *= ramp[::-1]
                    if index:
                        clips.append(np.zeros(int(0.20 * sr), dtype="float32"))
                    # A quiet aside retains the voice and words, with its own
                    # sentence contour and explicit pauses on both sides.
                    clips.append(audio * (0.84 if part["aside"] else 1.0))
                if not clips:
                    raise RuntimeError("generated audio was empty after spoken-text cleanup")
                sf.write(str(tmp), np.concatenate(clips), 24000, subtype="PCM_16")
            except Exception as exc:
                tmp.unlink(missing_ok=True)
                error = exc
                if config.get('record_fragments') and parts and len(diagnostics) == index:
                    diagnostics.append({'text': part['text'], 'fragment': index, 'aside': part['aside'],
                                        'seconds': None, 'frames': None, 'error': str(exc),
                                        'cap_hit': str(exc).startswith('generation reached'),
                                        'stop_reason': 'cap' if str(exc).startswith('generation reached') else 'error',
                                        'max_new_tokens': config.get('max_new_tokens'),
                                        'elapsed_seconds': time.perf_counter() - started})
            if config.get("record_fragments"):
                unit = {**unit, "generation": diagnostics}
            rendered.append((unit, attempt, tmp, error))
        return rendered
    return bisect_cuda_oom(
        items,
        lambda rows: _render_batch(torch, processor, model, voice, rows, config, unit_dir),
        torch,
    )


def _recover_with_render_profile(job_dir, parent, units, reports, unit_dir, rejected,
                                 torch, processor, model, voice, config, checker, retries,
                                 done=0, total=0, shard=0, report_progress=None, render=None):
    """Try each spent legacy unit once, retaining its checkpoint unless the parent improves."""
    if report_progress is None:
        report_progress = lambda status, index, attempt: _progress(job_dir, done, total, shard, status, index, attempt)
    baseline = parent_quality(parent, reports, units=units)
    for unit in _profile_recovery_candidates(parent, units, reports, unit_dir, retries):
        if _cancelled(job_dir):
            raise SystemExit(2)
        profile = ASCII_APOSTROPHE_PROFILE
        if not _mark_profile_attempt(unit_dir, parent, unit, profile):
            continue
        profiled = _profiled_unit(unit, profile)
        label = f"profile_{profile}_{time.time_ns()}"
        attempt = int(json.loads(_receipt_path(unit_dir, unit["index"]).read_text(encoding="utf-8")).get("attempt", 0)) + 1
        report_progress("generating", parent["index"], attempt)
        rendered = (render([(profiled, attempt)]) if render else
                    _render_items(torch, processor, model, voice, [(profiled, attempt)], config, unit_dir))
        _, _, tmp, render_error = rendered[0]
        if _cancelled(job_dir):
            tmp.unlink(missing_ok=True)
            raise SystemExit(2)
        if render_error:
            tmp.unlink(missing_ok=True)
            continue
        report_progress("quality_check", parent["index"], attempt)
        pending = _QualityCheck(checker, tmp, profiled, label)
        ok, report_path = pending.wait(job_dir, checker)
        if _cancelled(job_dir):
            tmp.unlink(missing_ok=True)
            raise SystemExit(2)
        if not ok:
            tmp.replace(rejected / f"unit_{unit['index']:010d}_{label}.wav")
            continue
        candidate_reports = list(reports)
        candidate_reports[unit["unit_index"]] = _reported_unit(unit, report_path)
        candidate = parent_quality(parent, candidate_reports, units=units)
        if candidate["ok"] and _strict_parent_improvement(baseline, candidate):
            _publish_unit(unit_dir, profiled, tmp, report_path, attempt)
            return candidate_reports, candidate
        tmp.replace(rejected / f"unit_{unit['index']:010d}_{label}.wav")
    return None


def run_generate(job_dir, shard=0, num_shards=1):
    if shard != 0 or num_shards != 1:
        raise RuntimeError("VibeVoice uses exactly one GPU worker; shard 0 of 1 is required")
    job_dir = Path(job_dir)
    plan, config = load_plan(job_dir)
    if config.get("workflow") == "generate_first_parakeet_v1":
        import vibevoice_phases
        return vibevoice_phases.run_generate(job_dir)
    if config.get("workflow", "overlap_cpu") != "overlap_cpu":
        raise ValueError("Unknown narration workflow")
    passages = plan["passages"]
    narration_review.save_entries(job_dir, [data for data in narration_review.entries(job_dir)
                                            if data["parent"] in passages])
    seg_dir = job_dir / SEGMENTS_DIR
    rejected = job_dir / REJECTED_DIR
    unit_dir = seg_dir / UNITS_DIR
    seg_dir.mkdir(exist_ok=True)
    rejected.mkdir(exist_ok=True)
    unit_dir.mkdir(exist_ok=True)
    (job_dir / ERROR_FILE).unlink(missing_ok=True)
    done = sum(_valid_segment(seg_dir, passage) for passage in passages)
    _progress(job_dir, done, len(passages), shard, "loading_model")
    todo = [passage for passage in passages if not _valid_segment(seg_dir, passage)]
    remaining = []
    for parent in todo:
        if _cancelled(job_dir):
            _progress(job_dir, done, len(passages), shard, "cancelled")
            raise SystemExit(2)
        units = _units_for_parent(parent, config)
        if any(_valid_unit(unit_dir, unit, allow_needs_repair=True, allow_review=True)
               and not _valid_unit(unit_dir, unit, allow_needs_repair=True) for unit in units):
            review = narration_review.entry(job_dir, parent) or {}
            narration_review.record(job_dir, parent, units, review.get('candidates', []))
        if _recover_parent_from_units(job_dir, parent, units, unit_dir, seg_dir):
            done += 1
            _progress(job_dir, done, len(passages), shard, "generating")
        else:
            remaining.append(parent)
    todo = remaining
    # Previously flagged passages with no missing clips need no GPU work.
    deferred = []
    for parent in todo:
        review = narration_review.entry(job_dir, parent)
        if review:
            flagged = {item["index"] for item in narration_review.detail(job_dir, parent["index"])["items"]}
            if all(unit["index"] in flagged or _valid_unit(unit_dir, unit)
                   for unit in _units_for_parent(parent, config)):
                deferred.append(parent)
    todo = [parent for parent in todo if parent not in deferred]
    if not todo:
        if narration_review.entries(job_dir):
            _progress(job_dir, done, len(passages), shard, "awaiting_review",
                      metrics={"review_passages": len(narration_review.entries(job_dir)),
                               "generated_words": sum(len(p["text"].split()) for p in passages),
                               "total_words": sum(len(p["text"].split()) for p in passages)})
            raise narration_review.ListeningRequired("Narration has finished. Review the flagged clips before assembling the audiobook.")
        _progress(job_dir, done, len(passages), shard, "complete")
        return
    # Only missing unit work calibrates a resumed run; existing receipts must
    # not make its measured speed look artificially fast.
    word_counts = {p["index"]: len(p["text"].split()) for p in passages}
    pending_words = {
        p["index"]: max(1, sum(len(unit["text"].split()) for unit in _units_for_parent(p, config)
                              if not _valid_unit(unit_dir, unit)))
        for p in todo
    }
    verified_words = sum(word_counts.values()) - sum(word_counts[p["index"]] for p in todo + deferred)
    generated_words = verified_words + sum(word_counts[p["index"]] for p in deferred)
    remaining_words = sum(pending_words.values())
    measured_words = prose_samples = 0
    _assert_no_ocr()
    voice = _prepare_voice(job_dir, config, plan)
    if _cancelled(job_dir):
        _progress(job_dir, done, len(passages), shard, "cancelled")
        raise SystemExit(2)
    torch, processor, model = _load_model(config)
    retries = int(config.get("quality_max_retries", 2))
    checker = _QualityChecker(job_dir, config)
    checkers = [checker]

    def report_progress(status, passage_index=None, attempt=None):
        eta = estimate_word_remaining_seconds(
            time.monotonic() - timing_started, measured_words, remaining_words, prose_samples,
        )
        if status == "awaiting_review":
            eta = None
        _progress(job_dir, done, len(passages), shard, status, passage_index, attempt, metrics={
            "verified_words": verified_words, "total_words": sum(word_counts.values()),
            "generated_words": generated_words,
            "eta_sec": eta, "eta_samples": prose_samples,
            "review_passages": len(narration_review.entries(job_dir)),
        })

    active_quality = None
    active_checks = {}
    cross_parent_prefetch = None
    renderer = ThreadPoolExecutor(max_workers=1, thread_name_prefix="vibevoice-render")

    def render_batch(batch):
        if _cancelled(job_dir):
            raise SystemExit(2)
        parents = sorted({unit["parent_index"] for unit, _ in batch})
        indices = [unit["index"] for unit, _ in batch]
        _overlap_telemetry(job_dir, config, "render_start", parents, indices)
        result = _render_items(torch, processor, model, voice, batch, config, unit_dir)
        _overlap_telemetry(job_dir, config, "render_end", parents, indices)
        return result

    def render(batch):
        return _wait_render(renderer.submit(render_batch, batch), job_dir)

    def prefetch(parent):
        try:
            return _prefetch_next_parent(job_dir, parent, config, unit_dir,
                                         torch, processor, model, voice)
        except Exception as exc:
            _overlap_telemetry(job_dir, config, "prefetch_deferred", [parent["index"]],
                               error_type=type(exc).__name__)
            return None

    def start_check(row, rendered):
        if row >= len(rendered):
            return
        unit, attempt, tmp, error = rendered[row]
        if error:
            return
        helper = checkers[row % len(checkers)]
        label = f"attempt{attempt}_{time.time_ns()}"
        report_progress("quality_check", unit["parent_index"], attempt)
        active_checks[row] = (_QualityCheck(helper, tmp, unit, label), helper, label)
        _overlap_telemetry(job_dir, config, "quality_start", [unit["parent_index"]], [unit["index"]])

    try:
        # Keep additional CPU model memory opt-in for measured machines.
        if config.get("quality_workers") == 2 and _batch_size(torch, config) > 1:
            checkers.append(_QualityChecker(job_dir, config))
        timing_started = time.monotonic()
        for parent_position, parent in enumerate(todo):
            try:
                units = _units_for_parent(parent, config)
                prior_review = narration_review.entry(job_dir, parent)
                flagged = {item["index"] for item in narration_review.detail(job_dir, parent["index"])["items"]} if prior_review else set()
                review_candidates = list(prior_review.get("candidates", [])) if prior_review else []
                attempts, queued = {}, []
                prefetched = None
                prefetched_count = 0
                for unit in units:
                    receipt = _receipt_path(unit_dir, unit["index"])
                    valid = _valid_unit(unit_dir, unit)
                    if valid:
                        attempts[unit["index"]] = int(json.loads(receipt.read_text(encoding="utf-8")).get("attempt", 0))
                    elif unit["index"] not in flagged:
                        attempts[unit["index"]] = 0
                        queued.append(_profiled_unit(unit))
                if cross_parent_prefetch is not None:
                    cross_parent_prefetch = _wait_render(cross_parent_prefetch, job_dir)
                if cross_parent_prefetch:
                    prefetched = cross_parent_prefetch["rendered"]
                    prefetched_count = len(prefetched)
                    prefetched_indices = {unit["index"] for unit, _attempt, _tmp, _error in prefetched}
                    queued = [unit for unit in queued if unit["index"] not in prefetched_indices]
                    for unit, attempt, _tmp, _error in prefetched:
                        attempts[unit["index"]] = attempt
                    _overlap_telemetry(job_dir, config, "prefetch_consumed", [parent["index"]], sorted(prefetched_indices))
                    cross_parent_prefetch = None
                while queued or prefetched is not None:
                    if _cancelled(job_dir):
                        report_progress("cancelled")
                        raise SystemExit(2)
                    if prefetched is None:
                        batch = [(unit, attempts[unit["index"]] + 1) for unit in queued[:_batch_size(torch, config)]]
                        del queued[:len(batch)]
                        for unit, attempt in batch:
                            report_progress("generating", parent["index"], attempt)
                        rendered = render(batch)
                    else:
                        rendered = (_wait_render(prefetched, job_dir) if hasattr(prefetched, "result") else prefetched)
                        prefetched = None
                        prefetched_count = 0
                    terminal_error = None
                    for row in range(min(len(checkers), len(rendered))):
                        start_check(row, rendered)
                    for row, (unit, attempt, tmp, render_error) in enumerate(rendered):
                        if _cancelled(job_dir):
                            tmp.unlink(missing_ok=True)
                            raise SystemExit(2)
                        if render_error:
                            attempts[unit["index"]] = attempt
                            if _recoverable_render_error(render_error) and attempt < _attempt_limit(unit, retries):
                                queued.append(unit)
                                start_check(row + len(checkers), rendered)
                                continue
                            terminal_error = render_error
                            start_check(row + len(checkers), rendered)
                            continue
                        pending, helper, label = active_checks.pop(row)
                        active_quality = pending
                        # Render ahead without blocking subsequent checks. Keep
                        # at most two configured batches, including a partial
                        # batch retained at the end of the current parent.
                        if queued and prefetched is None and cross_parent_prefetch is None:
                            next_batch = [(candidate, attempts[candidate["index"]] + 1)
                                          for candidate in queued[:_batch_size(torch, config)]]
                            del queued[:len(next_batch)]
                            for candidate, next_attempt in next_batch:
                                report_progress("generating", parent["index"], next_attempt)
                            if _cancelled(job_dir):
                                raise SystemExit(2)
                            prefetched = renderer.submit(render_batch, next_batch)
                            prefetched_count = len(next_batch)
                        elif (not queued
                              and _cross_parent_enabled(config) and cross_parent_prefetch is None
                              and parent_position + 1 < len(todo)
                              and len(rendered) - row + prefetched_count
                                  + min(PREFETCH_MAX_ITEMS, _batch_size(torch, config))
                                  <= 2 * _batch_size(torch, config)):
                            cross_parent_prefetch = renderer.submit(prefetch, todo[parent_position + 1])
                            report_progress("quality_check", parent["index"], attempt)
                        _overlap_telemetry(job_dir, config, "quality_wait_start", [parent["index"]], [unit["index"]])
                        ok, report = pending.wait(job_dir, helper)
                        _overlap_telemetry(job_dir, config, "quality_wait_end", [parent["index"]], [unit["index"]])
                        active_quality = None
                        candidate_report = _reported_unit(unit, report) if ok else None
                        if ok and candidate_report["ok"]:
                            if _cancelled(job_dir):
                                tmp.unlink(missing_ok=True)
                                raise SystemExit(2)
                            _publish_unit(unit_dir, unit, tmp, report, attempt)
                            attempts[unit["index"]] = attempt
                        else:
                            attempts[unit["index"]] = attempt
                            if attempt < _attempt_limit(unit, retries) and not (candidate_report or {}).get('review_required'):
                                tmp.replace(rejected / f"unit_{unit['index']:010d}_{label}.wav")
                                queued.append(unit)
                            else:
                                pending_dir = seg_dir / narration_review.CANDIDATES_DIR
                                pending_dir.mkdir(exist_ok=True)
                                _publish_unit(pending_dir, unit, tmp, report, attempt)
                                review_candidates.append(unit["index"])
                                narration_review.record(job_dir, parent, units, review_candidates)
                                terminal_error = terminal_error or narration_review.ListeningRequired("Clip needs listening review")
                        start_check(row + len(checkers), rendered)
                    if terminal_error:
                        if isinstance(terminal_error, narration_review.ListeningRequired):
                            continue
                        raise terminal_error
                if review_candidates or prior_review:
                    narration_review.hold(job_dir, parent, units, review_candidates)
                reports = [_unit_report(unit_dir, unit) for unit in units]
                aggregate = parent_quality(parent, reports, units=units)
                if not aggregate['ok'] and all(report.get('ok') for report in reports):
                    narration_review.hold(job_dir, parent, units)
                while not aggregate["ok"]:
                    exhausted = {unit["unit_index"] for unit in units
                                 if attempts[unit["index"]] >= _attempt_limit(unit, retries)}
                    try:
                        unit = choose_repair_unit(units, reports, exclude=exhausted)
                    except ValueError as exc:
                        recovered = _recover_with_render_profile(
                            job_dir, parent, units, reports, unit_dir, rejected, torch, processor,
                            model, voice, config, checker, retries, done, len(passages), shard, report_progress,
                            render=render,
                        )
                        if recovered:
                            reports, aggregate = recovered
                            continue
                        narration_review.hold(job_dir, parent, units)
                    receipt_path = _receipt_path(unit_dir, unit["index"])
                    saved = json.loads(receipt_path.read_text(encoding="utf-8"))
                    saved["needs_repair"] = True
                    _write_json(receipt_path, saved)
                    accepted = False
                    while attempts[unit["index"]] < _attempt_limit(unit, retries):
                        if _cancelled(job_dir):
                            report_progress("cancelled")
                            raise SystemExit(2)
                        attempt = attempts[unit["index"]] + 1
                        report_progress("generating", parent["index"], attempt)
                        rendered_unit = _profiled_unit(unit)
                        rendered = render([(rendered_unit, attempt)])
                        _, _, tmp, render_error = rendered[0]
                        attempts[unit["index"]] = attempt
                        if render_error:
                            tmp.unlink(missing_ok=True)
                            if _recoverable_render_error(render_error):
                                continue
                            raise render_error
                        label = f"attempt{attempt}_{time.time_ns()}"
                        report_progress("quality_check", parent["index"], attempt)
                        pending = active_quality = _QualityCheck(checker, tmp, rendered_unit, label)
                        ok, report = pending.wait(job_dir, checker)
                        active_quality = None
                        if _cancelled(job_dir):
                            tmp.unlink(missing_ok=True)
                            raise SystemExit(2)
                        candidate_report = _reported_unit(unit, report) if ok else None
                        if not ok or not candidate_report["ok"]:
                            tmp.replace(rejected / f"unit_{unit['index']:010d}_{label}.wav")
                            continue
                        _publish_unit(unit_dir, rendered_unit, tmp, report, attempt)
                        accepted = True
                        break
                    if not accepted:
                        narration_review.hold(job_dir, parent, units)
                    reports = [_unit_report(unit_dir, candidate) for candidate in units]
                    aggregate = parent_quality(parent, reports, units=units)
                if _cancelled(job_dir):
                    report_progress("cancelled")
                    raise SystemExit(2)
                _assemble_parent_from_units(parent, units, unit_dir, seg_dir, aggregate)
                done += 1
                verified_words += word_counts[parent["index"]]
                generated_words += word_counts[parent["index"]]
                measured_words += pending_words[parent["index"]]
                remaining_words -= pending_words[parent["index"]]
                if not parent.get("heading") and pending_words[parent["index"]] >= 40:
                    prose_samples += 1
                report_progress("generating")
            except narration_review.ListeningRequired:
                remaining_words -= pending_words[parent["index"]]
                generated_words += word_counts[parent["index"]]
                report_progress("generating", parent["index"])
                continue
    finally:
        for helper in checkers:
            helper.close()
        for pending in [active_quality] + [item[0] for item in active_checks.values()]:
            thread = getattr(pending, "thread", None)
            if thread is not None:
                thread.join(timeout=10)
        # A render may still be writing a provisional WAV after cancellation.
        # Join its owner before cleaning files; the server can terminate the
        # entire owned worker if generation does not stop promptly.
        renderer.shutdown(wait=True, cancel_futures=True)
        for tmp in unit_dir.glob("*.tmp*.wav"):
            tmp.unlink(missing_ok=True)
    if narration_review.entries(job_dir):
        report_progress("awaiting_review")
        raise narration_review.ListeningRequired("Narration has finished. Review the flagged clips before assembling the audiobook.")
    report_progress("complete")


def run_assemble(job_dir):
    job_dir = Path(job_dir)
    if narration_review.entries(job_dir):
        raise narration_review.ListeningRequired("Review the flagged clips before assembling the audiobook.")
    plan, config = load_plan(job_dir)
    seg_dir = job_dir / SEGMENTS_DIR
    passages = [p for p in plan['passages']
                if any(u.get('spoken_text', u['text']) for u in _units_for_parent(p, config))]
    missing = [p["index"] for p in passages if not _valid_segment(seg_dir, p)]
    if missing:
        raise RuntimeError(f"cannot assemble: {len(missing)} VibeVoice passages missing (first {missing[0]})")
    output = assemble(job_dir, passages, config, lambda index: _wav_path(seg_dir, index), lambda: _cancelled(job_dir))
    print(f"wrote {output}", flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("job_dir")
    parser.add_argument("--shard", type=int, default=None)
    parser.add_argument("--num-shards", type=int, default=1)
    parser.add_argument("--assemble", action="store_true")
    args = parser.parse_args()
    try:
        if args.assemble:
            run_assemble(args.job_dir)
            return
        run_generate(args.job_dir, 0 if args.shard is None else args.shard, args.num_shards)
        if args.shard is None and args.num_shards == 1:
            run_assemble(args.job_dir)
    except SystemExit:
        raise
    except narration_review.ListeningRequired as exc:
        _write_json(Path(args.job_dir) / ERROR_FILE, {"reason": "listening_required", "message": str(exc)})
        print(str(exc), flush=True)
        raise SystemExit(3)
    except Exception as exc:
        error = Path(args.job_dir) / ERROR_FILE
        if not error.exists():
            _write_json(error, {"reason": "worker_failed", "message": str(exc)})
        raise


if __name__ == "__main__":
    main()
