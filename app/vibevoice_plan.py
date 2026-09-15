"""Deterministic, speech-only planning for the isolated VibeVoice backend."""

import hashlib
import json
import re
from pathlib import Path

try:
    from .generation_settings import normalize_settings
except ImportError:  # Worker imports this module as a top-level script.
    from generation_settings import normalize_settings


PLAN_FILENAME = "vibevoice_plan.json"
CONFIG_FILENAME = "vibevoice_config.json"
PLAN_SCHEMA = 1
MODEL_ID = "microsoft/VibeVoice-1.5B"
MODEL_REVISION = "c00898d257e6b46004e3e2866a47534085fb685a"
TOKENIZER_REVISION = "8faed761d45a263340a0528343f099c05c9a4323"
RUNTIME = {
    "model_id": MODEL_ID,
    "model_revision": MODEL_REVISION,
    "tokenizer_revision": TOKENIZER_REVISION,
    "dtype": "bfloat16",
    "cfg_scale": 2.0,
    "ddpm_steps": 20,
    "attention": "sdpa",
    "max_new_tokens": 4000,
    "max_input_tokens": 2048,
    "sample_rate": 24000,
    "target_lufs": -21.0,
    "quality_major_words": 5,
    "quality_max_retries": 2,
    "quality_policy_revision": 1,
}
TARGET_WORDS = 365
MAX_WORDS = 430
SENTENCE_RE = re.compile(r"(?<=[.!?])\s+(?=[\"'“‘A-Z])")
SPACED_ELLIPSIS_RE = re.compile(r"\.\s*\.\s*\.")


def normalize_text(text):
    """Preserve words exactly while making VibeVoice's one-line input stable."""
    text = " ".join(str(text).split())
    return SPACED_ELLIPSIS_RE.sub("...", text)


def _words(text):
    return len(text.split())


def _split_oversize(text, max_words=MAX_WORDS):
    """Split only when one extracted paragraph exceeds the hard passage bound."""
    sentences = [part.strip() for part in SENTENCE_RE.split(text) if part.strip()]
    if len(sentences) < 2:
        words = text.split()
        return [" ".join(words[start:start + max_words]) for start in range(0, len(words), max_words)]
    bounded = []
    for sentence in sentences:
        sentence_words = sentence.split()
        bounded.extend(" ".join(sentence_words[start:start + max_words]) for start in range(0, len(sentence_words), max_words))
    result, current = [], []
    for sentence in bounded:
        candidate = " ".join(current + [sentence])
        if current and _words(candidate) > max_words:
            result.append(" ".join(current))
            current = [sentence]
        else:
            current.append(sentence)
    if current:
        result.append(" ".join(current))
    return result


def _paragraphs(blocks):
    if isinstance(blocks, dict):
        blocks = blocks.get("blocks", [])
    for block in blocks:
        text = normalize_text(block.get("text", ""))
        if text:
            yield text, block.get("type", "body"), block.get("source_page")


def pack_passages(blocks, target_words=TARGET_WORDS, max_words=MAX_WORDS):
    """Pack whole extracted paragraphs first, retaining dialogue with its paragraph."""
    if not 1 <= target_words <= max_words:
        raise ValueError("target_words must be between 1 and max_words")
    passages, current, pages, types = [], [], [], []

    def flush():
        if current:
            passages.append({
                "text": " ".join(current),
                "source_pages": sorted(set(page for page in pages if page is not None)),
                "block_types": list(types),
            })
            current.clear()
            pages.clear()
            types.clear()

    for text, block_type, page in _paragraphs(blocks):
        if block_type == "heading":
            flush()
            passages.append({"text": text, "heading": text, "source_pages": [page] if page is not None else [], "block_types": [block_type]})
            continue
        units = _split_oversize(text, max_words) if _words(text) > max_words else [text]
        for unit in units:
            candidate = " ".join(current + [unit])
            if current and _words(candidate) > max_words:
                flush()
            current.append(unit)
            pages.append(page)
            types.append(block_type)
            if _words(" ".join(current)) >= target_words:
                flush()
    flush()
    return passages


def sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def model_fingerprint(model_dir):
    """Cheaply bind resumes to the installed model layout without hashing GiB weights."""
    root = Path(model_dir)
    index = root / "model.safetensors.index.json"
    config = root / "config.json"
    if not index.is_file() or not config.is_file():
        raise ValueError("VibeVoice model directory is missing config or weight index")
    data = json.loads(index.read_text(encoding="utf-8"))
    names = sorted(set(data.get("weight_map", {}).values()))
    if not names:
        raise ValueError("VibeVoice model weight index is empty")
    files = []
    for name in names:
        path = root / name
        if not path.is_file():
            raise ValueError(f"VibeVoice model shard is missing: {name}")
        stat = path.stat()
        files.append((name, stat.st_size, stat.st_mtime_ns))
    payload = {"config_sha256": sha256_file(config), "index_sha256": sha256_file(index), "shards": files}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def passage_identity(text, voice_sha256, runtime=None):
    payload = {
        "schema": PLAN_SCHEMA,
        "runtime": runtime or RUNTIME,
        "voice_sha256": voice_sha256,
        "text": text,
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def write_plan(job_dir, blocks, config):
    """Write the backend sidecar without modifying legacy plans or segment caches."""
    job_dir = Path(job_dir)
    config = dict(config)
    raw_settings = dict(config.get("generation_settings") or {})
    for key in ("cfg_scale", "ddpm_steps", "passage_gap_ms", "heading_lead_ms"):
        if key in config:
            if key in raw_settings and config[key] != raw_settings[key]:
                raise ValueError(f"VibeVoice config {key} conflicts with generation settings")
            raw_settings[key] = config[key]
    settings = normalize_settings("vibevoice", config.get("path", "A"), raw_settings)
    config["generation_settings"] = settings
    config["cfg_scale"] = settings["cfg_scale"]
    config["ddpm_steps"] = settings["ddpm_steps"]
    config["passage_gap_ms"] = settings["passage_gap_ms"]
    config["heading_lead_ms"] = settings["heading_lead_ms"]
    config["batch_preference"] = settings["performance_mode"]
    voice = Path(config["reference_wav"])
    if not config.get("model_dir"):
        raise ValueError("VibeVoice model_dir is required")
    voice_sha256 = sha256_file(voice)
    runtime = dict(RUNTIME)
    for key in RUNTIME:
        if key in ("cfg_scale", "ddpm_steps"):
            continue
        if key in config and config[key] != runtime[key]:
            raise ValueError(f"VibeVoice requires {key}={runtime[key]!r}")
    runtime["cfg_scale"] = settings["cfg_scale"]
    runtime["ddpm_steps"] = settings["ddpm_steps"]
    runtime["model_fingerprint"] = model_fingerprint(config["model_dir"])
    # Persist the resolved settings. The worker must never silently substitute a
    # different model or generation setting after a plan has been fingerprinted.
    config.update(runtime)
    passages = pack_passages(blocks, int(config.get("target_words", TARGET_WORDS)), int(config.get("max_words", MAX_WORDS)))
    for index, passage in enumerate(passages):
        passage["index"] = index
        passage["before_ms"] = settings["heading_lead_ms"] if passage.get("heading") else 0
        passage["after_ms"] = settings["passage_gap_ms"] if index < len(passages) - 1 else 0
        passage["speaker_text"] = "Speaker 0: " + passage["text"]
        passage["text_sha256"] = hashlib.sha256(passage["text"].encode("utf-8")).hexdigest()
        passage["identity"] = passage_identity(passage["text"], voice_sha256, runtime)
    plan = {
        "schema": PLAN_SCHEMA,
        "runtime": runtime,
        "voice_sha256": voice_sha256,
        "passages": passages,
    }
    (job_dir / PLAN_FILENAME).write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    (job_dir / CONFIG_FILENAME).write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    return plan


def load_plan(job_dir):
    job_dir = Path(job_dir)
    plan = json.loads((job_dir / PLAN_FILENAME).read_text(encoding="utf-8"))
    config = json.loads((job_dir / CONFIG_FILENAME).read_text(encoding="utf-8"))
    settings = normalize_settings("vibevoice", config.get("path", "A"), config.get("generation_settings"))
    for key, value in RUNTIME.items():
        if key in ("cfg_scale", "ddpm_steps"):
            value = settings[key]
        if config.get(key) != value:
            raise ValueError(f"VibeVoice config {key} does not match its fixed runtime")
    for key in ("cfg_scale", "ddpm_steps", "passage_gap_ms", "heading_lead_ms"):
        if config.get(key) != settings[key]:
            raise ValueError(f"VibeVoice config {key} does not match generation settings")
    expected_runtime = {**RUNTIME, "cfg_scale": settings["cfg_scale"], "ddpm_steps": settings["ddpm_steps"], "model_fingerprint": model_fingerprint(config["model_dir"])}
    if plan.get("schema") != PLAN_SCHEMA or plan.get("runtime") != expected_runtime:
        raise ValueError("VibeVoice plan runtime does not match its config; rebuild the plan")
    if sha256_file(config["reference_wav"]) != plan.get("voice_sha256"):
        raise ValueError("VibeVoice voice reference changed; rebuild the plan")
    for index, passage in enumerate(plan.get("passages", [])):
        if passage.get("index") != index or passage.get("identity") != passage_identity(passage.get("text", ""), plan["voice_sha256"], plan["runtime"]):
            raise ValueError("VibeVoice plan passage identity mismatch; rebuild the plan")
    return plan, config
