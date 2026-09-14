"""One-GPU, resumable VibeVoice 1.5B narration worker.

This module deliberately imports VibeVoice only after planning and resume checks;
the base server and Chatterbox environment never import its model stack.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import soundfile as sf

from vibevoice_audio import mono_24k
from vibevoice_plan import load_plan, normalize_text, sha256_file
from vibevoice_assembly import _ffmpeg, assemble


SEGMENTS_DIR = "vibevoice_segments"
PROGRESS_FILE = "vibevoice_progress.json"
ERROR_FILE = "vibevoice_error.json"
REJECTED_DIR = "vibevoice_rejected"
CANCEL_FILE = "cancel_flag.txt"


def _write_json(path, value):
    temporary = path.with_suffix(path.suffix + f".tmp{os.getpid()}")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def _progress(job_dir, done, total, shard, status):
    _write_json(Path(job_dir) / PROGRESS_FILE, {"done": int(done), "total": int(total), "shard": int(shard), "status": str(status)})


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


def _quality_check(job_dir, wav_path, passage, config, attempt_label):
    python = config.get("quality_python")
    model = config.get("quality_model")
    if not python or not model:
        raise RuntimeError("VibeVoice quality verification requires quality_python and quality_model")
    report = Path(job_dir) / REJECTED_DIR / f"seg_{passage['index']:06d}_{attempt_label}.quality.json"
    command = [python, str(Path(__file__).with_name("vibevoice_quality.py")), "--audio", str(wav_path), "--expected", passage["text"], "--model", model, "--report", str(report), "--major-words", str(int(config.get("quality_major_words", 5)))]
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    deadline = time.monotonic() + int(config.get("quality_timeout_seconds", 300))
    while process.poll() is None:
        if _cancelled(job_dir):
            process.kill()
            process.wait()
            raise SystemExit(2)
        if time.monotonic() >= deadline:
            process.kill()
            process.wait()
            raise RuntimeError("quality verifier timed out")
        time.sleep(0.1)
    stdout, stderr = process.communicate()
    result = type("QualityResult", (), {"returncode": process.returncode, "stdout": stdout, "stderr": stderr})()
    if result.returncode not in (0, 3):
        raise RuntimeError(f"quality verifier failed (exit {result.returncode}): {result.stderr.strip() or result.stdout.strip()}")
    return result.returncode == 0, report


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


def run_generate(job_dir, shard=0, num_shards=1):
    if shard != 0 or num_shards != 1:
        raise RuntimeError("VibeVoice uses exactly one GPU worker; shard 0 of 1 is required")
    job_dir = Path(job_dir)
    plan, config = load_plan(job_dir)
    passages = plan["passages"]
    seg_dir = job_dir / SEGMENTS_DIR
    rejected = job_dir / REJECTED_DIR
    seg_dir.mkdir(exist_ok=True)
    rejected.mkdir(exist_ok=True)
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
    for passage in todo:
        if _cancelled(job_dir):
            _progress(job_dir, done, len(passages), shard, "cancelled")
            raise SystemExit(2)
        failure = None
        for attempt in range(1, retries + 2):
            if _cancelled(job_dir):
                _progress(job_dir, done, len(passages), shard, "cancelled")
                raise SystemExit(2)
            tmp = _wav_path(seg_dir, passage["index"]).with_suffix(f".tmp{os.getpid()}.wav")
            try:
                _render_one(torch, processor, model, voice, passage, config, tmp)
            except Exception as exc:
                tmp.unlink(missing_ok=True)
                if str(exc).startswith(("generation reached", "generated audio was", "loudness normalization")):
                    failure = exc
                    continue
                raise
            attempt_label = f"attempt{attempt}_{time.time_ns()}"
            quality_ok, quality_report = _quality_check(job_dir, tmp, passage, config, attempt_label)
            if not quality_ok:
                tmp.replace(rejected / f"seg_{passage['index']:06d}_{attempt_label}.wav")
                failure = RuntimeError(f"major ASR coverage error; report {quality_report.name}")
                continue
            final = _wav_path(seg_dir, passage["index"])
            tmp.replace(final)
            _write_json(_receipt_path(seg_dir, passage["index"]), {"identity": passage["identity"], "text_sha256": passage["text_sha256"], "wav_sha256": sha256_file(final), "quality_report": str(quality_report), "attempt": attempt})
            done += 1
            _progress(job_dir, done, len(passages), shard, "generating")
            failure = None
            break
        if failure:
            _write_json(job_dir / ERROR_FILE, {"reason": "passage_failed", "message": str(failure), "passage_index": passage["index"], "attempts": retries + 1})
            raise failure
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
