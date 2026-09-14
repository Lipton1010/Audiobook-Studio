"""One-GPU, resumable VibeVoice 1.5B narration worker.

This module deliberately imports VibeVoice only after planning and resume checks;
the base server and Chatterbox environment never import its model stack.
"""

import argparse
from collections import deque
import json
import os
import shutil
import subprocess
import sys
import time
from queue import Empty, Queue
from threading import Lock, Thread
from pathlib import Path

import numpy as np
import soundfile as sf

from vibevoice_audio import mono_24k
from vibevoice_plan import load_plan, normalize_text, sha256_file
from vibevoice_assembly import _ffmpeg, assemble
from vibevoice_units import repair_units, parent_quality, choose_repair_unit
from vibevoice_quality import assess
from gpu_oom import bisect_cuda_oom


SEGMENTS_DIR = "vibevoice_segments"
PROGRESS_FILE = "vibevoice_progress.json"
ERROR_FILE = "vibevoice_error.json"
REJECTED_DIR = "vibevoice_rejected"
UNITS_DIR = "units"
CANCEL_FILE = "cancel_flag.txt"


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
    if len(parsed) != 1 or normalize_text(parsed[0][1]) != passage["text"]:
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


def _batch_size(torch):
    """Batch only on the measured 24 GiB class; smaller cards remain serial."""
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
    for passage in passages:
        parsed = processor._parse_script(passage["speaker_text"])
        if len(parsed) != 1 or normalize_text(parsed[0][1]) != passage["text"]:
            raise RuntimeError("VibeVoice processor did not preserve the complete passage text")
    inputs = processor(text=[p["speaker_text"] for p in passages], voice_samples=[[voice] for _ in passages],
                       padding=True, return_tensors="pt", return_attention_mask=True)
    counts = inputs["attention_mask"].sum(dim=-1).tolist()
    if any(count > int(config["max_input_tokens"]) for count in counts):
        raise RuntimeError("passage exceeds VibeVoice input-token ceiling; rebuild the plan with smaller passages")
    inputs = {key: value.to("cuda") if torch.is_tensor(value) else value for key, value in inputs.items()}
    with torch.inference_mode():
        result = model.generate(**inputs, cfg_scale=float(config["cfg_scale"]), tokenizer=processor.tokenizer,
                                max_new_tokens=int(config["max_new_tokens"]), do_sample=False)
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
        rendered.append((passage, attempt, tmp, error))
    return rendered


def _valid_unit(unit_dir, unit):
    if not _valid_segment(unit_dir, unit):
        return False
    try:
        receipt = json.loads(_receipt_path(unit_dir, unit["index"]).read_text(encoding="utf-8"))
        report = Path(receipt["quality_report"])
        payload = report.read_bytes()
        parsed = json.loads(payload)
        recomputed = assess(unit["text"], parsed.get("transcript", ""))
    except Exception:
        return False
    return bool(not receipt.get("needs_repair")
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
                and isinstance(parsed.get("transcript"), str) and recomputed.get("ok"))


def _unit_report(unit_dir, unit):
    receipt = json.loads(_receipt_path(unit_dir, unit["index"]).read_text(encoding="utf-8"))
    saved = json.loads(Path(receipt["quality_report"]).read_text(encoding="utf-8"))
    report = assess(unit["text"], saved.get("transcript", ""))
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
    tmp.replace(final)
    _write_json(_receipt_path(unit_dir, passage["index"]), {
        "identity": passage["identity"], "text_sha256": passage["text_sha256"],
        "wav_sha256": wav_sha256, "quality_report": str(report),
        "report_sha256": sha256_file(report), "parent_index": passage["parent_index"],
        "unit_index": passage["unit_index"], "attempt": attempt,
        "report_identity": passage["identity"], "report_wav_sha256": wav_sha256,
    })


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
        temp.replace(final)
    finally:
        temp.unlink(missing_ok=True)
    manifest = [{"index": unit["index"], "identity": unit["identity"],
                 "wav_sha256": sha256_file(_wav_path(unit_dir, unit["index"]))} for unit in units]
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
    try:
        for parent in todo:
            units = repair_units(parent)
            attempts, queued = {}, []
            prefetched = None
            for unit in units:
                receipt = _receipt_path(unit_dir, unit["index"])
                valid = _valid_unit(unit_dir, unit)
                if valid:
                    attempts[unit["index"]] = int(json.loads(receipt.read_text(encoding="utf-8")).get("attempt", 0))
                else:
                    attempts[unit["index"]] = 0
                    queued.append(unit)
            while queued or prefetched is not None:
                if _cancelled(job_dir):
                    _progress(job_dir, done, len(passages), shard, "cancelled")
                    raise SystemExit(2)
                if prefetched is None:
                    batch = [(unit, attempts[unit["index"]] + 1) for unit in queued[:_batch_size(torch)]]
                    del queued[:len(batch)]
                    for unit, attempt in batch:
                        _progress(job_dir, done, len(passages), shard, "generating", parent["index"], attempt)
                    rendered = _render_items(torch, processor, model, voice, batch, config, unit_dir)
                else:
                    rendered, prefetched = prefetched, None
                terminal_error = None
                for row, (unit, attempt, tmp, render_error) in enumerate(rendered):
                    if _cancelled(job_dir):
                        tmp.unlink(missing_ok=True)
                        raise SystemExit(2)
                    if render_error:
                        attempts[unit["index"]] = attempt
                        if _recoverable_render_error(render_error) and attempt <= retries:
                            queued.append(unit)
                            continue
                        terminal_error = render_error
                        continue
                    label = f"attempt{attempt}_{time.time_ns()}"
                    _progress(job_dir, done, len(passages), shard, "quality_check", parent["index"], attempt)
                    pending = active_quality = _QualityCheck(checker, tmp, unit, label)
                    # One CPU verification may overlap one following GPU batch.
                    # The verifier remains a single persistent process and we do
                    # not submit another request until this one has completed.
                    if row == 0 and queued:
                        next_batch = [(candidate, attempts[candidate["index"]] + 1)
                                      for candidate in queued[:_batch_size(torch)]]
                        del queued[:len(next_batch)]
                        for candidate, next_attempt in next_batch:
                            _progress(job_dir, done, len(passages), shard, "generating", parent["index"], next_attempt)
                        try:
                            prefetched = _render_items(torch, processor, model, voice, next_batch, config, unit_dir)
                        except Exception as exc:
                            # Finish the already-running CPU verdict before
                            # surfacing a following GPU failure.
                            terminal_error = exc
                        _progress(job_dir, done, len(passages), shard, "quality_check", parent["index"], attempt)
                    ok, report = pending.wait(job_dir, checker)
                    active_quality = None
                    if ok:
                        _publish_unit(unit_dir, unit, tmp, report, attempt)
                        attempts[unit["index"]] = attempt
                    else:
                        tmp.replace(rejected / f"unit_{unit['index']:010d}_{label}.wav")
                        attempts[unit["index"]] = attempt
                        if attempt <= retries:
                            queued.append(unit)
                        else:
                            terminal_error = RuntimeError(f"major ASR coverage error; report {report.name}")
                if terminal_error:
                    raise terminal_error
            reports = [_unit_report(unit_dir, unit) for unit in units]
            aggregate = parent_quality(parent, reports, units=units)
            while not aggregate["ok"]:
                exhausted = {unit["unit_index"] for unit in units
                             if attempts[unit["index"]] >= retries + 1}
                try:
                    unit = choose_repair_unit(units, reports, exclude=exhausted)
                except ValueError as exc:
                    raise RuntimeError("parent quality failed after exhausting repair attempts") from exc
                receipt_path = _receipt_path(unit_dir, unit["index"])
                saved = json.loads(receipt_path.read_text(encoding="utf-8"))
                saved["needs_repair"] = True
                _write_json(receipt_path, saved)
                accepted = False
                while attempts[unit["index"]] < retries + 1:
                    if _cancelled(job_dir):
                        _progress(job_dir, done, len(passages), shard, "cancelled")
                        raise SystemExit(2)
                    attempt = attempts[unit["index"]] + 1
                    _progress(job_dir, done, len(passages), shard, "generating", parent["index"], attempt)
                    rendered = _render_items(torch, processor, model, voice, [(unit, attempt)], config, unit_dir)
                    _, _, tmp, render_error = rendered[0]
                    attempts[unit["index"]] = attempt
                    if render_error:
                        tmp.unlink(missing_ok=True)
                        if _recoverable_render_error(render_error):
                            continue
                        raise render_error
                    label = f"attempt{attempt}_{time.time_ns()}"
                    _progress(job_dir, done, len(passages), shard, "quality_check", parent["index"], attempt)
                    pending = active_quality = _QualityCheck(checker, tmp, unit, label)
                    ok, report = pending.wait(job_dir, checker)
                    active_quality = None
                    if not ok:
                        tmp.replace(rejected / f"unit_{unit['index']:010d}_{label}.wav")
                        continue
                    _publish_unit(unit_dir, unit, tmp, report, attempt)
                    accepted = True
                    break
                if not accepted:
                    raise RuntimeError(f"parent quality failed after repairing unit {unit['unit_index']}")
                reports = [_unit_report(unit_dir, candidate) for candidate in units]
                aggregate = parent_quality(parent, reports, units=units)
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
