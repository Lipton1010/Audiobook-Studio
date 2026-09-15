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
from pathlib import Path

import numpy as np
import soundfile as sf

from vibevoice_audio import mono_24k
from vibevoice_plan import load_plan, normalize_text, sha256_file
from vibevoice_assembly import _ffmpeg, assemble
from vibevoice_units import repair_units, parent_quality, choose_repair_unit
from vibevoice_quality import assess, integer_words, numbered_heading_assessment
from gpu_oom import bisect_cuda_oom


SEGMENTS_DIR = "vibevoice_segments"
PROGRESS_FILE = "vibevoice_progress.json"
ERROR_FILE = "vibevoice_error.json"
REJECTED_DIR = "vibevoice_rejected"
UNITS_DIR = "units"
CANCEL_FILE = "cancel_flag.txt"
OVERLAP_TELEMETRY_FILE = "vibevoice_overlap.jsonl"
PREFETCH_MAX_ITEMS = 2
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
    profile = profile or unit.get("render_profile", ASCII_APOSTROPHE_PROFILE)
    render_heading = unit.get("render_heading")
    render_text = _render_text(unit["text"], profile, render_heading)
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
    return hashlib.sha256(_render_text(unit["text"], profile, unit.get("render_heading")).encode("utf-8")).hexdigest()


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
    units = repair_units(parent)
    if _is_numbered_heading(parent):
        units[0] = {**units[0], "numbered_heading": True}
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


def _progress(job_dir, done, total, shard, status, passage_index=None, attempt=None):
    payload = {"done": int(done), "total": int(total), "shard": int(shard), "status": str(status)}
    if passage_index is not None:
        payload["passage_index"] = int(passage_index)
    if attempt is not None:
        payload["attempt"] = int(attempt)
    _write_json(Path(job_dir) / PROGRESS_FILE, payload)


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
    wav, receipt = _wav_path(seg_dir, passage["index"]), _receipt_path(seg_dir, passage["index"])
    if not wav.is_file() or not receipt.is_file():
        return False
    try:
        saved = json.loads(receipt.read_text(encoding="utf-8"))
        info = sf.info(str(wav))
        audio, sr = sf.read(str(wav), dtype="float32")
    except Exception:
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
        and saved.get("wav_sha256") == sha256_file(wav)
        and info.samplerate == 24000
        and info.channels == 1
        and info.frames > 2400
        and sr == 24000 and audio.ndim == 1
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
    from vibevoice.modular.modeling_vibevoice_inference import VibeVoiceForConditionalGenerationInference
    from vibevoice.processor.vibevoice_processor import VibeVoiceProcessor

    if not torch.cuda.is_available():
        raise RuntimeError("VibeVoice requires an NVIDIA CUDA GPU")
    torch.set_num_threads(4)
    torch.cuda.set_per_process_memory_fraction(0.85)
    model_path = config.get("model_dir")
    if not model_path:
        raise RuntimeError("VibeVoice model_dir is not configured")
    print(
        "VibeVoice runtime: "
        f"model={config['model_id']} revision={config['model_revision']} "
        f"tokenizer={config['tokenizer_revision']} dtype={config['dtype']} "
        f"cfg={config['cfg_scale']} steps={config['ddpm_steps']} "
        f"attention={config['attention']} allocator=85% cpu_threads=4 "
        f"fingerprint={config['model_fingerprint']}",
        flush=True,
    )
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
        report = self.job_dir / REJECTED_DIR / f"seg_{passage['index']:06d}_{attempt_label}.quality.json"
        request = {"audio": str(wav_path), "expected": passage["text"], "report": str(report),
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
    _assert_no_ocr()
    parsed = processor._parse_script(passage["speaker_text"])
    if len(parsed) != 1 or normalize_text(parsed[0][1]) != passage.get("render_text", passage["text"]):
        raise RuntimeError("VibeVoice processor did not preserve the complete passage text")
    inputs = processor(text=[passage["speaker_text"]], voice_samples=[[voice]], padding=True, return_tensors="pt", return_attention_mask=True)
    if inputs["input_ids"].shape[-1] > int(config["max_input_tokens"]):
        raise RuntimeError("passage exceeds VibeVoice input-token ceiling; rebuild the plan with smaller passages")
    inputs = {key: value.to("cuda") if torch.is_tensor(value) else value for key, value in inputs.items()}
    with torch.inference_mode():
        result = model.generate(**inputs, cfg_scale=float(config["cfg_scale"]), tokenizer=processor.tokenizer, max_new_tokens=int(config["max_new_tokens"]), do_sample=False)
    torch.cuda.synchronize()
    if bool(result.reach_max_step_sample.any()):
        raise RuntimeError("generation reached the 4000-token cap")
    wav = result.speech_outputs[0].detach().float().cpu().numpy().squeeze()
    if wav.ndim != 1 or len(wav) <= 2400 or not np.isfinite(wav).all() or np.max(np.abs(wav)) <= 0.001:
        raise RuntimeError("generated audio was empty, nonfinite, or silent")
    import pyloudnorm as pyln
    loudness = pyln.Meter(24000).integrated_loudness(wav)
    target = min(float(config.get("target_lufs", -21.0)), loudness + 20 * np.log10(0.95 / np.max(np.abs(wav))))
    wav = pyln.normalize.loudness(wav, loudness, target)
    if not np.isfinite(wav).all() or np.max(np.abs(wav)) > 1.0:
        raise RuntimeError("loudness normalization produced invalid audio")
    sf.write(str(tmp_path), wav, 24000, subtype="PCM_16")


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
    try:
        return 2 if int(torch.cuda.get_device_properties(0).total_memory) >= 23 * 1024 ** 3 else 1
    except Exception:
        return 1


def _normalize_wav(wav_tensor, config):
    if wav_tensor is None:
        raise RuntimeError("generated audio was empty, nonfinite, or silent")
    wav = wav_tensor.detach().float().cpu().numpy().squeeze()
    if wav.ndim != 1 or len(wav) <= 2400 or not np.isfinite(wav).all() or np.max(np.abs(wav)) <= 0.001:
        raise RuntimeError("generated audio was empty, nonfinite, or silent")
    import pyloudnorm as pyln
    loudness = pyln.Meter(24000).integrated_loudness(wav)
    target = min(float(config.get("target_lufs", -21.0)), loudness + 20 * np.log10(0.95 / np.max(np.abs(wav))))
    wav = pyln.normalize.loudness(wav, loudness, target)
    if not np.isfinite(wav).all() or np.max(np.abs(wav)) > 1.0:
        raise RuntimeError("loudness normalization produced invalid audio")
    return wav


def _render_batch(torch, processor, model, voice, items, config, unit_dir):
    """Render up to two independent scripts and retain each row's own outcome."""
    _assert_no_ocr()
    items = list(items)
    passages = [item[0] for item in items]
    if len(items) != 1 and any(passage.get("render_profile") == NUMBERED_OUTLINE_HEADING_PROFILE for passage in passages):
        raise RuntimeError("numbered outline headings must render as one seeded row")
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
        seed = _numbered_heading_seed(passage, attempt)
        if seed is not None:
            rendered_passage["render_seed"] = seed
        rendered.append((rendered_passage, attempt, tmp, error))
    return rendered


def _valid_unit(unit_dir, unit, allow_needs_repair=False):
    if not _valid_segment(unit_dir, unit):
        return False
    try:
        receipt = json.loads(_receipt_path(unit_dir, unit["index"]).read_text(encoding="utf-8"))
        report = Path(receipt["quality_report"])
        payload = report.read_bytes()
        parsed = json.loads(payload)
        assessment = (numbered_heading_assessment(unit["text"], parsed.get("transcript", ""))
                      if unit.get("numbered_heading") else assess(unit["text"], parsed.get("transcript", "")))
        profile = receipt.get("render_profile")
        if (unit.get("render_profile") == NUMBERED_OUTLINE_HEADING_PROFILE
                and profile not in (None, ASCII_APOSTROPHE_PROFILE, NUMBERED_OUTLINE_HEADING_PROFILE)):
            return False
        if (unit.get("render_profile") != NUMBERED_OUTLINE_HEADING_PROFILE
                and unit.get("render_profile") and profile is not None and profile != unit["render_profile"]):
            return False
        if profile not in (None, ASCII_APOSTROPHE_PROFILE, OUTLINE_PREFIX_CASE_PROFILE, NUMBERED_OUTLINE_HEADING_PROFILE):
            return False
        if profile in (OUTLINE_PREFIX_CASE_PROFILE, NUMBERED_OUTLINE_HEADING_PROFILE) and receipt.get("render_heading") != unit.get("render_heading"):
            return False
        if not isinstance(receipt.get("profile_attempts", {}), dict):
            return False
        valid_profile = (profile is None or receipt.get("render_text_sha256") == _render_text_sha256(unit, profile))
        valid_seed = True
        if profile == NUMBERED_OUTLINE_HEADING_PROFILE:
            valid_seed = _valid_numbered_heading_seed(receipt)
            valid_seed = bool(valid_seed and isinstance(receipt.get("attempt"), int)
                              and not isinstance(receipt.get("attempt"), bool)
                              and receipt.get("attempt") == receipt.get("render_attempt"))
    except Exception:
        return False
    return bool(valid_profile and valid_seed and (allow_needs_repair or not receipt.get("needs_repair"))
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
                and isinstance(parsed.get("transcript"), str) and assessment.get("ok"))


def _recover_parent_from_units(job_dir, parent, units, unit_dir, seg_dir):
    """Reuse a fully validated unit checkpoint after a checker-only correction."""
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
        receipt_path = _receipt_path(unit_dir, unit["index"])
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        if receipt.get("needs_repair"):
            receipt["needs_repair"] = False
            _write_json(receipt_path, receipt)
    return True


def _unit_report(unit_dir, unit):
    receipt = json.loads(_receipt_path(unit_dir, unit["index"]).read_text(encoding="utf-8"))
    saved = json.loads(Path(receipt["quality_report"]).read_text(encoding="utf-8"))
    report = (numbered_heading_assessment(unit["text"], saved.get("transcript", ""))
              if unit.get("numbered_heading") else assess(unit["text"], saved.get("transcript", "")))
    report["transcript"] = saved.get("transcript", "")
    report["unit_index"] = unit["unit_index"]
    return report


def _reported_unit(unit, report_path):
    saved = json.loads(Path(report_path).read_text(encoding="utf-8"))
    report = (numbered_heading_assessment(unit["text"], saved.get("transcript", ""))
              if unit.get("numbered_heading") else assess(unit["text"], saved.get("transcript", "")))
    report["transcript"] = saved.get("transcript", "")
    report["unit_index"] = unit["unit_index"]
    return report


def _publish_unit(unit_dir, passage, tmp, report, attempt):
    final = _wav_path(unit_dir, passage["index"])
    wav_sha256 = sha256_file(tmp)
    report_payload = json.loads(Path(report).read_text(encoding="utf-8"))
    report_payload.update({"unit_identity": passage["identity"],
                           "unit_text_sha256": passage["text_sha256"],
                           "audio_sha256": wav_sha256})
    _write_json(Path(report), report_payload)
    if _cancelled(unit_dir.parent.parent):
        raise SystemExit(2)
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
    }
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
    try:
        for position, unit in enumerate(units):
            wav, sr = sf.read(str(_wav_path(unit_dir, unit["index"])), dtype="float32")
            if sr != 24000 or wav.ndim != 1:
                raise RuntimeError("accepted VibeVoice unit is not mono 24 kHz")
            ramp = np.linspace(0.0, 1.0, 120, dtype=np.float32)
            if position:
                wav[:120] *= ramp
            if position + 1 < len(units):
                wav[-120:] *= ramp[::-1]
            audio.append(wav)
        sf.write(str(temp), np.concatenate(audio), 24000, subtype="PCM_16")
        if not aggregate.get("ok"):
            raise RuntimeError("cannot publish a parent that failed quality")
        if _cancelled(seg_dir.parent):
            raise SystemExit(2)
        if _is_numbered_heading(parent):
            _archive_replaced_heading_wav(final, seg_dir.parent / REJECTED_DIR)
        if _cancelled(seg_dir.parent):
            raise SystemExit(2)
        temp.replace(final)
    finally:
        temp.unlink(missing_ok=True)
    manifest = []
    for unit in units:
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
    return bisect_cuda_oom(
        items,
        lambda rows: _render_batch(torch, processor, model, voice, rows, config, unit_dir),
        torch,
    )


def _recover_with_render_profile(job_dir, parent, units, reports, unit_dir, rejected,
                                 torch, processor, model, voice, config, checker, retries,
                                 done=0, total=0, shard=0):
    """Try each spent legacy unit once, retaining its checkpoint unless the parent improves."""
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
        _progress(job_dir, done, total, shard, "generating", parent["index"], attempt)
        rendered = _render_items(torch, processor, model, voice, [(profiled, attempt)], config, unit_dir)
        _, _, tmp, render_error = rendered[0]
        if _cancelled(job_dir):
            tmp.unlink(missing_ok=True)
            raise SystemExit(2)
        if render_error:
            tmp.unlink(missing_ok=True)
            continue
        _progress(job_dir, done, total, shard, "quality_check", parent["index"], attempt)
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
    passages = plan["passages"]
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
        if _recover_parent_from_units(job_dir, parent, units, unit_dir, seg_dir):
            done += 1
            _progress(job_dir, done, len(passages), shard, "generating")
        else:
            remaining.append(parent)
    todo = remaining
    if not todo:
        _progress(job_dir, done, len(passages), shard, "complete")
        return
    _assert_no_ocr()
    voice = _prepare_voice(job_dir, config, plan)
    if _cancelled(job_dir):
        _progress(job_dir, done, len(passages), shard, "cancelled")
        raise SystemExit(2)
    torch, processor, model = _load_model(config)
    retries = int(config.get("quality_max_retries", 2))
    checker = _QualityChecker(job_dir, config)
    active_quality = None
    cross_parent_prefetch = None
    try:
        for parent_position, parent in enumerate(todo):
            units = _units_for_parent(parent, config)
            attempts, queued = {}, []
            prefetched = None
            for unit in units:
                receipt = _receipt_path(unit_dir, unit["index"])
                valid = _valid_unit(unit_dir, unit)
                if valid:
                    attempts[unit["index"]] = int(json.loads(receipt.read_text(encoding="utf-8")).get("attempt", 0))
                else:
                    attempts[unit["index"]] = 0
                    queued.append(_profiled_unit(unit))
            if cross_parent_prefetch and cross_parent_prefetch["parent_index"] == parent["index"]:
                prefetched = cross_parent_prefetch["rendered"]
                prefetched_indices = {unit["index"] for unit, _attempt, _tmp, _error in prefetched}
                queued = [unit for unit in queued if unit["index"] not in prefetched_indices]
                for unit, attempt, _tmp, _error in prefetched:
                    attempts[unit["index"]] = attempt
                _overlap_telemetry(job_dir, config, "prefetch_consumed", [parent["index"]], sorted(prefetched_indices))
                cross_parent_prefetch = None
            while queued or prefetched is not None:
                if _cancelled(job_dir):
                    _progress(job_dir, done, len(passages), shard, "cancelled")
                    raise SystemExit(2)
                if prefetched is None:
                    batch = [(unit, attempts[unit["index"]] + 1) for unit in queued[:_batch_size(torch, config)]]
                    del queued[:len(batch)]
                    for unit, attempt in batch:
                        _progress(job_dir, done, len(passages), shard, "generating", parent["index"], attempt)
                    _overlap_telemetry(job_dir, config, "render_start", [parent["index"]], [unit["index"] for unit, _ in batch])
                    rendered = _render_items(torch, processor, model, voice, batch, config, unit_dir)
                    _overlap_telemetry(job_dir, config, "render_end", [parent["index"]], [unit["index"] for unit, _ in batch])
                else:
                    rendered, prefetched = prefetched, None
                terminal_error = None
                for row, (unit, attempt, tmp, render_error) in enumerate(rendered):
                    if _cancelled(job_dir):
                        tmp.unlink(missing_ok=True)
                        raise SystemExit(2)
                    if render_error:
                        attempts[unit["index"]] = attempt
                        if _recoverable_render_error(render_error) and attempt < _attempt_limit(unit, retries):
                            queued.append(unit)
                            continue
                        terminal_error = render_error
                        continue
                    label = f"attempt{attempt}_{time.time_ns()}"
                    _progress(job_dir, done, len(passages), shard, "quality_check", parent["index"], attempt)
                    pending = active_quality = _QualityCheck(checker, tmp, unit, label)
                    _overlap_telemetry(job_dir, config, "quality_start", [parent["index"]], [unit["index"]])
                    # One CPU verification may overlap one following GPU batch.
                    # The verifier remains a single persistent process and we do
                    # not submit another request until this one has completed.
                    if row == 0 and queued:
                        next_batch = [(candidate, attempts[candidate["index"]] + 1)
                                      for candidate in queued[:_batch_size(torch, config)]]
                        del queued[:len(next_batch)]
                        for candidate, next_attempt in next_batch:
                            _progress(job_dir, done, len(passages), shard, "generating", parent["index"], next_attempt)
                        try:
                            if _cancelled(job_dir):
                                raise SystemExit(2)
                            _overlap_telemetry(job_dir, config, "render_start", [parent["index"]], [unit["index"] for unit, _ in next_batch])
                            prefetched = _render_items(torch, processor, model, voice, next_batch, config, unit_dir)
                            _overlap_telemetry(job_dir, config, "render_end", [parent["index"]], [unit["index"] for unit, _ in next_batch])
                        except Exception as exc:
                            # Finish the already-running CPU verdict before
                            # surfacing a following GPU failure.
                            terminal_error = exc
                    elif (row == len(rendered) - 1 and not queued and prefetched is None
                          and _cross_parent_enabled(config) and cross_parent_prefetch is None
                          and parent_position + 1 < len(todo)):
                        try:
                            cross_parent_prefetch = _prefetch_next_parent(
                                job_dir, todo[parent_position + 1], config, unit_dir,
                                torch, processor, model, voice,
                            )
                        except Exception as exc:
                            _overlap_telemetry(job_dir, config, "prefetch_deferred", [todo[parent_position + 1]["index"]],
                                               error_type=type(exc).__name__)
                            cross_parent_prefetch = None
                        _progress(job_dir, done, len(passages), shard, "quality_check", parent["index"], attempt)
                    _overlap_telemetry(job_dir, config, "quality_wait_start", [parent["index"]], [unit["index"]])
                    ok, report = pending.wait(job_dir, checker)
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
                        tmp.replace(rejected / f"unit_{unit['index']:010d}_{label}.wav")
                        attempts[unit["index"]] = attempt
                        if attempt < _attempt_limit(unit, retries):
                            queued.append(unit)
                        else:
                            terminal_error = RuntimeError(f"major ASR coverage error; report {report.name}")
                if terminal_error:
                    raise terminal_error
            reports = [_unit_report(unit_dir, unit) for unit in units]
            aggregate = parent_quality(parent, reports, units=units)
            while not aggregate["ok"]:
                exhausted = {unit["unit_index"] for unit in units
                             if attempts[unit["index"]] >= _attempt_limit(unit, retries)}
                try:
                    unit = choose_repair_unit(units, reports, exclude=exhausted)
                except ValueError as exc:
                    recovered = _recover_with_render_profile(
                        job_dir, parent, units, reports, unit_dir, rejected, torch, processor,
                        model, voice, config, checker, retries, done, len(passages), shard,
                    )
                    if recovered:
                        reports, aggregate = recovered
                        continue
                    raise RuntimeError("parent quality failed after exhausting repair attempts") from exc
                receipt_path = _receipt_path(unit_dir, unit["index"])
                saved = json.loads(receipt_path.read_text(encoding="utf-8"))
                saved["needs_repair"] = True
                _write_json(receipt_path, saved)
                accepted = False
                while attempts[unit["index"]] < _attempt_limit(unit, retries):
                    if _cancelled(job_dir):
                        _progress(job_dir, done, len(passages), shard, "cancelled")
                        raise SystemExit(2)
                    attempt = attempts[unit["index"]] + 1
                    _progress(job_dir, done, len(passages), shard, "generating", parent["index"], attempt)
                    rendered_unit = _profiled_unit(unit)
                    rendered = _render_items(torch, processor, model, voice, [(rendered_unit, attempt)], config, unit_dir)
                    _, _, tmp, render_error = rendered[0]
                    attempts[unit["index"]] = attempt
                    if render_error:
                        tmp.unlink(missing_ok=True)
                        if _recoverable_render_error(render_error):
                            continue
                        raise render_error
                    label = f"attempt{attempt}_{time.time_ns()}"
                    _progress(job_dir, done, len(passages), shard, "quality_check", parent["index"], attempt)
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
                    raise RuntimeError(f"parent quality failed after repairing unit {unit['unit_index']}")
                reports = [_unit_report(unit_dir, candidate) for candidate in units]
                aggregate = parent_quality(parent, reports, units=units)
            if _cancelled(job_dir):
                _progress(job_dir, done, len(passages), shard, "cancelled")
                raise SystemExit(2)
            _assemble_parent_from_units(parent, units, unit_dir, seg_dir, aggregate)
            done += 1
            _progress(job_dir, done, len(passages), shard, "generating")
    finally:
        checker.close()
        if active_quality:
            active_quality.thread.join(timeout=10)
        for tmp in unit_dir.glob("*.tmp*.wav"):
            tmp.unlink(missing_ok=True)
    _progress(job_dir, done, len(passages), shard, "complete")


def run_assemble(job_dir):
    job_dir = Path(job_dir)
    plan, config = load_plan(job_dir)
    seg_dir = job_dir / SEGMENTS_DIR
    missing = [p["index"] for p in plan["passages"] if not _valid_segment(seg_dir, p)]
    if missing:
        raise RuntimeError(f"cannot assemble: {len(missing)} VibeVoice passages missing (first {missing[0]})")
    output = assemble(job_dir, plan["passages"], config, lambda index: _wav_path(seg_dir, index), lambda: _cancelled(job_dir))
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
    except Exception as exc:
        error = Path(args.job_dir) / ERROR_FILE
        if not error.exists():
            _write_json(error, {"reason": "worker_failed", "message": str(exc)})
        raise


if __name__ == "__main__":
    main()
