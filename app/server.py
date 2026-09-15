"""
Storybird server. Runs in the base miniconda env (stdlib +
PyMuPDF + requests only, no Flask, nothing installed anywhere).

    python server.py            -> http://localhost:8765

One worker thread runs every pipeline stage strictly sequentially, so
GLM-OCR extraction (Ollama on GPU) and Chatterbox narration (torch on
GPU) can never overlap, per the project's hard rule. Narration runs as
a subprocess inside the chatterbox conda env; this process never
imports torch or chatterbox.
"""

import hashlib
import io
import json
import math
import os
import platform
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

import fitz  # PyMuPDF
import requests

import pipeline_text as pt
import visual_review
from audiobook_exports import AudiobookExportError, export_finished_audio
from audiobook_files import ArtworkReplacementError, replace_finished_artwork
from generation_settings import default_settings, normalize_settings, runtime_settings
from audiobook_library import owned_library_directory, visible_audio, publish_finished_output, delete_generated_files, contained
from config import CFG
from narration_eta import PROGRESS_FILENAME, STALE_PROGRESS_SECONDS, STALLED_BATCH_SECONDS

APP_DIR = Path(__file__).parent
try:
    APP_VERSION = (APP_DIR / "VERSION").read_text(encoding="utf-8").strip()
except OSError:
    APP_VERSION = "0.0.0"
# Where update checks look for the latest release. Only ever read from, never
# written to automatically: a new version is something the owner PUSHES (a
# GitHub Release), the app only checks and shows a link, it never downloads
# or applies anything itself.
GITHUB_REPO = "Lipton1010/Audiobook-Studio"
JOBS_DIR = Path(os.environ.get("AUDIOBOOK_JOBS_DIR", APP_DIR / "jobs"))
STATIC_DIR = APP_DIR / "static"
VOICES_DIR = Path(os.environ.get("AUDIOBOOK_VOICES_DIR", APP_DIR / "voices"))

# Machine-specific settings now come from config.py (env > config.json >
# auto-detect > original default), so the app is portable across machines
# without editing source. See config.example.json.
LIBRARY_ROOTS = CFG.library_roots
# PDFs chosen in the UI are copied here. Keep this deterministic and app-owned:
# browser file inputs intentionally do not reveal the source path, and an
# installed copy must not depend on the user finding its hidden install folder.
PDF_IMPORT_DIR = CFG.base_dir / "source_pdfs"
# Imported PDFs leave the active library only after their audiobook is safely
# copied to the output library. Keep them instead of deleting them: beta users
# can still recover the source without the completed book continuing to look
# like unprocessed work.
PROCESSED_PDF_DIR = CFG.base_dir / "processed_pdfs"
# Default voice: converted from "Voice Sample Male.mp3" via convert_voice.py;
# the old ref_15s.wav default was judged bad on listening (2026-07-21).
REFERENCE_WAV = CFG.reference_wav
DEFAULT_VOICE = "Default narrator (male sample)"
AUDIOBOOKS_DIR = CFG.audiobooks_dir
CHATTERBOX_PY = CFG.chatterbox_python
VIBEVOICE_PY = CFG.vibevoice_python
OLLAMA_URL = CFG.ollama_url
OCR_MODEL = CFG.ocr_model
OCR_PROMPT = CFG.ocr_prompt
PORT = CFG.port

AUDIO_EXTS = {".m4b", ".mp3", ".wav"}
AUDIO_MIME = {".m4b": "audio/mp4", ".mp3": "audio/mpeg", ".wav": "audio/wav"}
MAX_PDF_BYTES = 2 * 1024 * 1024 * 1024
MAX_COVER_BYTES = 20 * 1024 * 1024
MAX_COVER_PIXELS = 24_000_000
MAX_PREVIEW_PIXELS = 6_000_000
IMAGE_MIME = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}
WINDOWS_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0


class _WindowsWorkerJob:
    """Own narration subprocesses by handle, never by a reusable numeric PID.

    Windows does not automatically terminate children when their parent exits.
    A Job Object with KILL_ON_JOB_CLOSE does, including when this server crashes
    and the kernel closes its handles. Assignment uses Popen's live process
    handle, so it cannot target a different process after PID reuse.
    """

    def __init__(self):
        self.handle = None
        if os.name != "nt":
            return

        import ctypes
        from ctypes import wintypes

        class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
            _fields_ = [
                ("PerProcessUserTimeLimit", ctypes.c_longlong),
                ("PerJobUserTimeLimit", ctypes.c_longlong),
                ("LimitFlags", wintypes.DWORD),
                ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t),
                ("ActiveProcessLimit", wintypes.DWORD),
                ("Affinity", ctypes.c_size_t),
                ("PriorityClass", wintypes.DWORD),
                ("SchedulingClass", wintypes.DWORD),
            ]

        class IO_COUNTERS(ctypes.Structure):
            _fields_ = [
                ("ReadOperationCount", ctypes.c_ulonglong),
                ("WriteOperationCount", ctypes.c_ulonglong),
                ("OtherOperationCount", ctypes.c_ulonglong),
                ("ReadTransferCount", ctypes.c_ulonglong),
                ("WriteTransferCount", ctypes.c_ulonglong),
                ("OtherTransferCount", ctypes.c_ulonglong),
            ]

        class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
            _fields_ = [
                ("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION),
                ("IoInfo", IO_COUNTERS),
                ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t),
                ("PeakJobMemoryUsed", ctypes.c_size_t),
            ]

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        kernel32.CreateJobObjectW.restype = wintypes.HANDLE
        kernel32.SetInformationJobObject.argtypes = [
            wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD,
        ]
        kernel32.SetInformationJobObject.restype = wintypes.BOOL
        kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL

        handle = kernel32.CreateJobObjectW(None, None)
        if not handle:
            raise ctypes.WinError(ctypes.get_last_error())
        info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        info.BasicLimitInformation.LimitFlags = 0x00002000  # KILL_ON_JOB_CLOSE
        if not kernel32.SetInformationJobObject(handle, 9, ctypes.byref(info), ctypes.sizeof(info)):
            error = ctypes.get_last_error()
            kernel32.CloseHandle(handle)
            raise ctypes.WinError(error)
        self.handle = handle
        self._kernel32 = kernel32

    def assign(self, proc):
        if self.handle is None:
            return
        import ctypes
        if not self._kernel32.AssignProcessToJobObject(self.handle, proc._handle):
            raise ctypes.WinError(ctypes.get_last_error())

    def close(self):
        if self.handle is not None:
            self._kernel32.CloseHandle(self.handle)
            self.handle = None


_worker_job_lock = threading.Lock()


def _assign_worker_to_job(proc):
    """Assign a worker and its descendants to an exact owned Job Object."""
    if os.name != "nt":
        return
    job = _WindowsWorkerJob()
    try:
        job.assign(proc)
    except Exception:
        job.close()
        raise
    with _worker_job_lock:
        proc._audiobook_job = job


def _close_worker_job(procs=()):
    """Close only the Job Objects attached to these live process handles."""
    jobs, seen = [], set()
    with _worker_job_lock:
        for proc in list(procs):
            job = vars(proc).get("_audiobook_job")
            proc._audiobook_job = None
            if job is not None and id(job) not in seen:
                jobs.append(job)
                seen.add(id(job))
    for job in jobs:
        job.close()

# Bumping the number of narration processes to fit the GPU. Each Chatterbox
# worker loads its own model copy and, measured on this stack, holds ~9-10 GB
# of VRAM, so worker count is (usable VRAM / per-worker budget), clamped.
# Env overrides let a user tune or pin it: AUDIOBOOK_NUM_WORKERS forces a
# count; AUDIOBOOK_VRAM_PER_WORKER_GB adjusts the per-worker budget.
# Measured on the 4090: each worker holds ~6 GB under multi-process pressure,
# and throughput peaks at 3 workers (1.0x/1.12x/1.28x/1.15x for N=1..4) then
# falls off as time-slicing overhead dominates. So cap at 3 and budget ~6.5 GB.
VRAM_PER_WORKER_GB = float(os.environ.get("AUDIOBOOK_VRAM_PER_WORKER_GB", "6.5"))
VRAM_RESERVE_GB = 2.0
MAX_WORKERS = 3
# Bump when the chunk-planning/packing logic changes so old segments (which
# are keyed by plan index) are treated as stale and regenerated.
PLAN_VERSION = "1"
# Narration engine: "parallel" = the shipped v1 one-chunk-at-a-time path run in
# N processes; "batched" = batched T3 inference in a SINGLE process (measured
# ~2.7-3.3x vs v1-single on a 4090, and numerically verified to produce
# per-chunk output equivalent to v1). Default stays "parallel" until the
# batched engine is signed off by listening. Override per job or via env.
DEFAULT_ENGINE = os.environ.get("AUDIOBOOK_ENGINE", "batched")
DEFAULT_BACKEND = "vibevoice"
BATCH_SIZE = int(os.environ.get("AUDIOBOOK_BATCH_SIZE", "12"))
# Caps rows*Tmax per batch so the batched KV-cache stays within VRAM; a fixed
# row count OOM-thrashes (hangs) once chunks get long. See narrate_worker.
BATCH_TOKEN_BUDGET = int(os.environ.get("AUDIOBOOK_BATCH_TOKEN_BUDGET", "1300"))
# Vocode each bucket in one S3Gen pass instead of row by row. Measured ~1.16x
# whole book, with audio inside the model's own run-to-run variation. See the
# performance section of CLAUDE.md; AUDIOBOOK_BATCH_S3GEN=0 falls back.
BATCH_S3GEN = os.environ.get("AUDIOBOOK_BATCH_S3GEN", "1") not in ("0", "false", "False")

JOBS_DIR.mkdir(exist_ok=True)
VOICES_DIR.mkdir(exist_ok=True)


# ---------- voices ----------

def list_voices():
    # The default clip is NOT shipped with the repo (rights rule), so on a fresh
    # clone it is absent. Report that instead of offering a voice that cannot work.
    voices = [{"name": DEFAULT_VOICE, "builtin": True,
               "available": Path(REFERENCE_WAV).exists()}]
    for f in sorted(VOICES_DIR.glob("*.wav")):
        voices.append({"name": f.stem, "builtin": False, "available": True})
    return voices


def missing_voice_error(name):
    """None if `name` resolves to a reference clip that exists, else a message.

    Checked at job creation because the alternative is failing inside the worker
    after extraction has finished and the TTS weights have downloaded, which is
    the most expensive possible place to discover a missing file."""
    vp = voice_wav_path(name)
    if Path(vp).exists():
        return None
    if not name or name == DEFAULT_VOICE:
        return (f"No default voice clip at {vp}. The default narrator sample is not "
                f"distributed with this repo: upload a voice in the Voices panel, or "
                f"set reference_wav in app/config.json.")
    return (f"Voice '{name}' not found, and the default clip at {vp} is missing too. "
            f"Upload a voice in the Voices panel.")


def narration_backend(st):
    """Choose a backend without changing any existing job's cache contract."""
    return st.get("backend") if st.get("backend") in ("chatterbox", "vibevoice") else "chatterbox"


def missing_vibevoice_error():
    """Return setup advice before extraction spends time on a VibeVoice job."""
    if not VIBEVOICE_PY or not Path(VIBEVOICE_PY).exists():
        return ("VibeVoice Python was not found. Set vibevoice_python in app/config.json "
                "or AUDIOBOOK_VIBEVOICE_PY to the isolated VibeVoice environment's python.exe.")
    model_dir = Path(CFG.vibevoice_model_dir)
    index = model_dir / "model.safetensors.index.json"
    if not index.is_file() or not (model_dir / "config.json").is_file() or not (model_dir / "preprocessor_config.json").is_file():
        return (f"VibeVoice model is incomplete at {model_dir}. Set vibevoice_model_dir in "
                "app/config.json or AUDIOBOOK_VIBEVOICE_MODEL_DIR to the verified local model folder.")
    try:
        shards = set(json.loads(index.read_text(encoding="utf-8")).get("weight_map", {}).values())
    except (OSError, ValueError, json.JSONDecodeError):
        return f"VibeVoice model index is unreadable: {index}. Re-run the VibeVoice setup check."
    if not shards or any(not (model_dir / shard).is_file() for shard in shards):
        return "VibeVoice model weights are incomplete. Re-run the VibeVoice setup check before creating a job."
    if not CFG.vibevoice_quality_python or not Path(CFG.vibevoice_quality_python).exists():
        return ("VibeVoice quality Python was not found. Set vibevoice_quality_python in "
                "app/config.json or AUDIOBOOK_VIBEVOICE_QUALITY_PY to the CPU verifier environment.")
    quality_dir = Path(CFG.vibevoice_quality_model) if CFG.vibevoice_quality_model else None
    if not quality_dir or any(not (quality_dir / name).is_file() for name in ("model.bin", "config.json", "tokenizer.json")):
        return ("VibeVoice quality model is incomplete. Set vibevoice_quality_model in app/config.json "
                "or AUDIOBOOK_VIBEVOICE_QUALITY_MODEL to the verified local model folder.")
    if not (APP_DIR / "vibevoice_worker.py").exists():
        return "VibeVoice support is incomplete: app/vibevoice_worker.py is missing."
    return None


# ---------- ffmpeg ----------
#
# Same shape as the missing-voice guard above, and for the same reason. m4b is
# the default output format, but m4b and mp3 both need ffmpeg. Discovering that
# ffmpeg is missing inside the worker means discovering it AFTER a multi-hour
# narration, which is the most expensive possible moment.
#
# Note this is deliberately NOT enforced at install time. ffmpeg can be removed
# or moved after setup runs, so a check there proves nothing here.

FFMPEG_FORMATS = ("m4b", "mp3")
_ffmpeg_install = {"running": False, "error": None, "log": ""}
_ffmpeg_lock = threading.Lock()


def ffmpeg_status(refresh=False):
    path = CFG.ffmpeg_path(refresh=refresh)
    with _ffmpeg_lock:
        return {
            "available": path is not None,
            "path": path,
            "installing": _ffmpeg_install["running"],
            "error": _ffmpeg_install["error"],
            "formats_needing_ffmpeg": list(FFMPEG_FORMATS),
        }


def missing_ffmpeg_error(fmt):
    """None if `fmt` can actually be produced on this machine, else a message."""
    if fmt not in FFMPEG_FORMATS:
        return None
    if CFG.ffmpeg_path() is not None:
        return None
    return (f"{fmt} output needs ffmpeg, which is not installed on this machine. "
            f"Click 'Install ffmpeg' in the app to fix this automatically, or "
            f"choose WAV output instead.")


def _parse_version(v):
    """'v1.2.3' or '1.2.3' -> (1, 2, 3), tolerant of a missing/odd part."""
    parts = []
    for p in v.strip().lstrip("vV").split("."):
        try:
            parts.append(int(p))
        except ValueError:
            parts.append(0)
    return tuple(parts)


def check_for_update():
    """Best-effort check against GitHub Releases. Never raises: no internet,
    a rate limit, or GitHub being down all just mean 'nothing to show', not
    a broken app. Only ever NOTIFIES with a link to the release page; it
    never downloads or applies anything on its own."""
    try:
        r = requests.get(
            f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest",
            timeout=10, headers={"Accept": "application/vnd.github+json"},
        )
        if r.status_code != 200:
            return {"current": APP_VERSION, "update_available": False}
        data = r.json()
        latest = str(data.get("tag_name") or "").strip()
        if not latest or _parse_version(latest) <= _parse_version(APP_VERSION):
            return {"current": APP_VERSION, "update_available": False}
        return {
            "current": APP_VERSION,
            "latest": latest,
            "update_available": True,
            "release_url": data.get("html_url"),
        }
    except Exception:
        return {"current": APP_VERSION, "update_available": False}


def missing_gpu_error():
    """None if an NVIDIA GPU is visible to the system, else a message.

    This only catches the "no GPU at all" case (nvidia-smi absent or
    failing). It cannot tell whether the GPU has enough free VRAM for
    narration; that is handled by scaling the batch size down and, if it
    still runs out, failing narration itself with a clear message rather
    than a raw traceback."""
    if gpu_total_vram_gb() is not None:
        return None
    return ("No NVIDIA GPU was detected on this machine (or its driver is "
            "not installed). Chatterbox narration requires an NVIDIA GPU; "
            "CPU-only narration is not supported.")


def _run_ffmpeg_install():
    """Fetch ffmpeg in the background. ~110 MB, so this cannot be done inside
    the POST: the UI polls /api/ffmpeg for the result instead."""
    # APP_DIR is Path(__file__).parent, deliberately NOT resolved elsewhere in
    # this file; resolve here so .parent is the repo root even when the server
    # was started via a relative path.
    script = Path(__file__).resolve().parent.parent / "install" / "bootstrap_ffmpeg.py"
    try:
        if not script.exists():
            raise RuntimeError(f"{script} is missing from this install")
        # bootstrap_ffmpeg is stdlib-only, so the base env python running this
        # server can execute it directly; no conda env needed.
        r = subprocess.run([sys.executable, str(script)], capture_output=True,
                           text=True, timeout=1800,
                           creationflags=WINDOWS_NO_WINDOW)
        log = (r.stdout or "") + (r.stderr or "")
        # Trust the re-check, not the exit code: CFG.ffmpeg_path actually runs
        # the binary.
        available = CFG.ffmpeg_path(refresh=True) is not None
        with _ffmpeg_lock:
            _ffmpeg_install["log"] = log[-4000:]
            _ffmpeg_install["error"] = None if available else (
                "The download finished but ffmpeg still does not run. This is "
                "usually antivirus quarantining the file, or no internet access. "
                "You can still narrate to WAV. Details:\n" + log[-1500:])
    except Exception as e:
        CFG.ffmpeg_path(refresh=True)
        with _ffmpeg_lock:
            _ffmpeg_install["error"] = (
                f"Could not install ffmpeg automatically: {e}. You can still "
                f"narrate to WAV, or install ffmpeg yourself from "
                f"https://www.gyan.dev/ffmpeg/builds/ and restart the app.")
    finally:
        with _ffmpeg_lock:
            _ffmpeg_install["running"] = False


def start_ffmpeg_install():
    with _ffmpeg_lock:
        if _ffmpeg_install["running"]:
            return False
        _ffmpeg_install["running"] = True
        _ffmpeg_install["error"] = None
        _ffmpeg_install["log"] = ""
    threading.Thread(target=_run_ffmpeg_install, name="ffmpeg-install",
                     daemon=True).start()
    return True


def voice_wav_path(name):
    if not name or name == DEFAULT_VOICE:
        return REFERENCE_WAV
    p = VOICES_DIR / (name + ".wav")
    return str(p) if p.exists() else REFERENCE_WAV


def save_voice(name, raw_bytes, ext):
    safe = re.sub(r"[^\w \-]", "", name).strip() or "voice"
    tmp_in = VOICES_DIR / ("_upload_tmp" + ext)
    tmp_in.write_bytes(raw_bytes)
    out = VOICES_DIR / (safe + ".wav")
    try:
        # Voice conversion only needs numpy and soundfile. A fresh 1.0.5
        # VibeVoice install deliberately does not build the legacy Chatterbox
        # environment, so prefer its isolated runtime and retain Chatterbox as
        # the fallback for existing installations.
        converter = next(
            (candidate for candidate in (VIBEVOICE_PY, CHATTERBOX_PY)
             if candidate and Path(candidate).is_file()),
            None,
        )
        if not converter:
            raise RuntimeError(
                "Voice conversion needs the VibeVoice or Chatterbox runtime. "
                "Run setup before uploading a voice sample."
            )
        r = subprocess.run(
            [converter, str(APP_DIR / "convert_voice.py"), str(tmp_in), str(out)],
            capture_output=True, text=True, timeout=120,
            creationflags=WINDOWS_NO_WINDOW,
        )
        if r.returncode != 0:
            msg = (r.stdout + r.stderr).strip()
            raise RuntimeError(msg.splitlines()[-1] if msg else "conversion failed")
        return safe
    finally:
        tmp_in.unlink(missing_ok=True)

_jobs_lock = threading.Lock()
_page_count_cache = {}
_start_page_cache = {}


# ---------- job state helpers ----------

def _state_path(job_id):
    return JOBS_DIR / job_id / "state.json"


# Serializes state.json access WITHIN this process, which is where the real
# contention is: the worker thread writes progress constantly while every HTTP
# handler thread reads it (the UI polls). On Windows a reader's open handle
# lacks FILE_SHARE_DELETE, so it blocks the rename in save_state and the write
# fails with "[WinError 5] Access is denied". Retries alone do NOT fix this:
# measured with 6 readers hammering, only 2 of many writes got through in 6
# seconds. Holding this lock makes the replace collision-free; the retries that
# remain cover outside interference such as antivirus touching the .tmp file.
_STATE_LOCK = threading.RLock()
_JOB_MUTATION_LOCKS = {}
_JOB_MUTATION_LOCKS_LOCK = threading.Lock()


def _job_mutation_lock(job_id):
    """Serialize finished-output changes with other mutations for one job."""
    with _JOB_MUTATION_LOCKS_LOCK:
        return _JOB_MUTATION_LOCKS.setdefault(job_id, threading.RLock())


def load_state(job_id):
    p = _state_path(job_id)
    with _STATE_LOCK:
        if not p.exists():
            return None
        return json.loads(p.read_text(encoding="utf-8"))


def save_state(state):
    """Atomically write a job's state.

    The replace is retried because on Windows it is NOT reliably atomic against
    concurrent readers: load_state (called from every HTTP handler thread, and
    the UI polls constantly) opens state.json without FILE_SHARE_DELETE, which
    makes a rename onto that path fail with "[WinError 5] Access is denied".
    Antivirus touching the .tmp file causes the same thing. This is not
    hypothetical: an unretried replace killed a 208-page DMG job at 74% after
    the extraction had already survived a separate failure.

    Progress state is not worth aborting a multi-hour job over, so after the
    retries are exhausted we give up on THIS write and let the next one carry
    the state forward, rather than raising into the worker loop.
    """
    p = _state_path(state["id"])
    tmp = p.with_suffix(".tmp")
    blob = json.dumps(state, indent=2)
    with _STATE_LOCK:
        for attempt in range(12):
            try:
                tmp.write_text(blob, encoding="utf-8")
                tmp.replace(p)
                return True
            except OSError:
                if attempt == 11:
                    print(f"save_state: giving up on this write for {state['id'][:8]}")
                    try:
                        tmp.unlink(missing_ok=True)
                    except OSError:
                        pass
                    return
                time.sleep(0.05 * (attempt + 1))


def log_line(job_id, msg):
    line = f"[{time.strftime('%H:%M:%S')}] {msg}\n"
    with open(JOBS_DIR / job_id / "log.txt", "a", encoding="utf-8") as f:
        f.write(line)
    print(f"{job_id[:8]} {msg}")


def list_jobs(include_hidden=False):
    out = []
    for d in sorted(JOBS_DIR.iterdir(), key=lambda p: p.name, reverse=True):
        if d.is_dir():
            st = load_state(d.name)
            if st and (include_hidden or not st.get("library_hidden")):
                scope = visual_review.scope_summary(d, st)
                if scope:
                    st["narration_range"] = {"from": scope["page_from"],
                                             "to": scope["end_page"],
                                             "original_to": scope["page_to"]}
                out.append(st)
    return out


# ---------- library ----------

def page_count(pdf_path):
    key = str(pdf_path)
    if key not in _page_count_cache:
        try:
            doc = fitz.open(pdf_path)
            _page_count_cache[key] = doc.page_count
            doc.close()
        except Exception:
            _page_count_cache[key] = None
    return _page_count_cache[key]


_START_HEADING_RE = re.compile(
    r"^(?:prologue|chapter\s+(?:0*1|one|i)|book\s+(?:0*1|one|i)|"
    r"part\s+(?:0*1|one|i)|canto\s+(?:0*1|one|i))(?:\b|\s*[:.\-])",
    re.IGNORECASE,
)


def _start_heading(text):
    """Return a cleaned first-content heading, or None.

    This deliberately recognizes only explicit opening divisions. Generic
    words such as Introduction and Preface may be material the owner wants in
    the audiobook, so silently skipping them would be a bad recommendation.
    """
    cleaned = re.sub(r"\s+", " ", str(text or "")).strip()
    return cleaned if _START_HEADING_RE.match(cleaned) else None


def suggest_start_page(pdf_path, pages):
    """Return (1-based page, reason) using PDF structure when it is credible.

    Prefer the PDF outline because its destinations point at the real chapter
    pages rather than the printed page numbers in a contents table. If there is
    no useful outline, scan only the opening portion for a standalone Prologue,
    Chapter One, Book One, Part One or Canto One heading. The UI still lets the
    user override this recommendation before creating the job.
    """
    pdf_path = Path(pdf_path)
    try:
        stat = pdf_path.stat()
        key = (str(pdf_path.resolve()).lower(), stat.st_size, stat.st_mtime_ns)
    except OSError:
        return 1, None
    if key in _start_page_cache:
        return _start_page_cache[key]

    result = (1, None)
    try:
        with fitz.open(pdf_path) as doc:
            outline_candidates = []
            for entry in doc.get_toc(simple=True) or []:
                if len(entry) < 3:
                    continue
                heading = _start_heading(entry[1])
                try:
                    page = int(entry[2])
                except (TypeError, ValueError):
                    continue
                if heading and 1 <= page <= pages:
                    outline_candidates.append((page, heading))
            if outline_candidates:
                page, heading = min(outline_candidates, key=lambda item: item[0])
                result = (page, f'PDF outline: "{heading}"')
            else:
                # Eighty pages reaches unusually long front matter such as The
                # Odyssey without turning every library refresh into a scan of
                # the entire book.
                found = False
                for pno in range(min(pages, 80)):
                    text = doc.load_page(pno).get_text("text")
                    lines = [re.sub(r"\s+", " ", line).strip()
                             for line in text.splitlines() if line.strip()]
                    if not lines:
                        continue
                    # Do not mistake a contents page full of chapter links for
                    # the start of the book.
                    markers = [heading for line in lines
                               if (heading := _start_heading(line))]
                    head_text = " ".join(lines[:10]).lower()
                    if "contents" in head_text or len(markers) >= 3:
                        continue
                    for line in lines[:20]:
                        heading = _start_heading(line)
                        if heading:
                            result = (pno + 1, f'page heading: "{heading}"')
                            found = True
                            break
                    if found:
                        break
    except Exception:
        result = (1, None)

    _start_page_cache[key] = result
    return result


def _library_item(pdf_path):
    pdf_path = Path(pdf_path)
    pages = page_count(pdf_path)
    suggested_start, start_reason = suggest_start_page(pdf_path, pages) if pages else (1, None)
    return {
        "path": str(pdf_path),
        "name": pdf_path.stem,
        "folder": str(pdf_path.parent),
        "cover_url": "/api/library/cover/" + _library_cover_token(pdf_path),
        "pages": pages,
        "suggested_path": suggest_path(pdf_path, pages) if pages else "B",
        "suggested_page_from": suggested_start,
        "suggested_start_reason": start_reason,
    }


def _library_cover_token(pdf_path):
    """Return an opaque, stable identifier for a PDF in the local library."""
    return hashlib.sha256(str(Path(pdf_path).resolve()).encode("utf-8")).hexdigest()[:24]


_pdf_import_lock = threading.Lock()


def import_pdf(stream, length, original_name, import_dir=None):
    """Stream, validate, and atomically add one PDF to the managed library."""
    if length <= 0:
        raise ValueError("The selected PDF is empty.")
    if length > MAX_PDF_BYTES:
        raise ValueError("The selected PDF is larger than the 2 GB import limit.")

    # The browser supplies only a basename, but sanitize again because this is
    # also an HTTP endpoint. Windows-invalid characters cannot reach the disk.
    filename = Path(str(original_name or "book.pdf")).name
    filename = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", filename).strip(" .")
    if not filename.lower().endswith(".pdf"):
        raise ValueError("Choose a PDF file.")
    stem = filename[:-4].strip(" .") or "book"
    filename = stem + ".pdf"

    destination_dir = Path(import_dir or PDF_IMPORT_DIR)
    destination_dir.mkdir(parents=True, exist_ok=True)
    temp_path = destination_dir / ("._pdf_import_" + uuid.uuid4().hex + ".tmp")
    remaining = length
    header = b""
    try:
        with temp_path.open("wb") as out:
            while remaining:
                chunk = stream.read(min(1024 * 1024, remaining))
                if not chunk:
                    raise ValueError("The PDF upload ended before the whole file arrived.")
                if len(header) < 1024:
                    header += chunk[:1024 - len(header)]
                out.write(chunk)
                remaining -= len(chunk)

        if b"%PDF-" not in header:
            raise ValueError("That file does not contain a valid PDF header.")
        try:
            with fitz.open(temp_path) as doc:
                if doc.needs_pass:
                    raise ValueError("Password-protected PDFs are not supported.")
                if doc.page_count < 1:
                    raise ValueError("That PDF has no readable pages.")
        except ValueError:
            raise
        except Exception as exc:
            raise ValueError("That PDF could not be opened. It may be damaged.") from exc

        with _pdf_import_lock:
            target = destination_dir / filename
            suffix = 2
            while target.exists():
                target = destination_dir / f"{stem} ({suffix}).pdf"
                suffix += 1
            os.replace(temp_path, target)
        return _library_item(target)
    finally:
        try:
            temp_path.unlink(missing_ok=True)
        except OSError:
            pass


def suggest_path(pdf_path, pages):
    """
    A needs a healthy text layer AND a single-column layout. Multi-column
    pages (many lines starting past mid-page) extract in the wrong reading
    order, so they go to GLM-OCR (B). User can override in UI.
    """
    try:
        doc = fitz.open(pdf_path)
        sample = range(0, pages, max(1, pages // 8))
        chars = []
        mid_start = total_lines = 0
        for i in sample:
            page = doc.load_page(i)
            chars.append(len(page.get_text()))
            width = page.rect.width
            d = page.get_text("dict")
            for block in d["blocks"]:
                if block.get("type", 0) != 0:
                    continue
                for line in block["lines"]:
                    total_lines += 1
                    if line["bbox"][0] > width * 0.45:
                        mid_start += 1
        doc.close()
        avg = sum(chars) / max(1, len(chars))
        if avg <= 300:
            return "B"
        if total_lines and mid_start / total_lines > 0.25:
            return "B"
        return "A"
    except Exception:
        return "B"


def extract_book_meta(pdf_path, title, job_dir):
    """Pull audiobook tags + cover art from the source PDF (base env has fitz;
    the narration worker does not). Returns (metadata, cover path, PDF outline).
    Cover: the first embedded image on page 1, else page 1 rendered. Never
    fatal - missing cover, metadata, or outline just yields fewer tags."""
    meta = {"title": title, "album": title, "genre": "Audiobook",
            "media_type": "2"}  # 2 = Audiobook in the iTunes/MP4 stik atom
    cover_path = None
    outline = []
    try:
        doc = fitz.open(pdf_path)
        pdf_meta = doc.metadata or {}
        if pdf_meta.get("author"):
            meta["artist"] = pdf_meta["author"]      # narrator/author field
            meta["album_artist"] = pdf_meta["author"]
        if pdf_meta.get("title"):
            meta["title"] = meta["album"] = pdf_meta["title"]
        try:
            outline = [
                {"level": int(level), "title": str(entry_title), "page": int(page)}
                for level, entry_title, page in doc.get_toc(simple=True)
                if int(page) > 0
            ]
        except Exception as e:
            print(f"outline extraction failed: {e}")
        # Cover: prefer the largest embedded image on page 1, else render it.
        try:
            page = doc.load_page(0)
            best = None
            for img in page.get_images(full=True):
                base = doc.extract_image(img[0])
                if base and (best is None or len(base["image"]) > len(best["image"])):
                    best = base
            cp = job_dir / "cover.jpg"
            if best and best["width"] >= 200 and best["height"] >= 200:
                ext = best["ext"]
                raw = job_dir / f"cover.{ext}"
                raw.write_bytes(best["image"])
                cover_path = str(raw)
            else:
                page.get_pixmap(dpi=150).save(str(cp))
                cover_path = str(cp)
        except Exception as e:
            print(f"cover extraction failed: {e}")
        doc.close()
    except Exception as e:
        print(f"metadata extraction failed: {e}")
    return meta, cover_path, outline


def _library_pdfs():
    seen = set()
    roots = list(LIBRARY_ROOTS)
    if not any(Path(root).resolve() == PDF_IMPORT_DIR.resolve() for root in roots):
        roots.append(PDF_IMPORT_DIR)
    for root in roots:
        if not root.exists():
            continue
        for p in sorted(root.rglob("*.pdf")):
            if _path_is_within(p, PROCESSED_PDF_DIR):
                continue
            key = str(p).lower()
            if key in seen:
                continue
            seen.add(key)
            yield p


def scan_library():
    return [_library_item(pdf_path) for pdf_path in _library_pdfs()]


def _library_pdf_for_cover(token):
    """Resolve only an opaque token back to an active library PDF."""
    if not re.fullmatch(r"[0-9a-f]{24}", token):
        return None
    for pdf_path in _library_pdfs():
        if _library_cover_token(pdf_path) == token:
            return pdf_path
    return None


def _render_library_cover(pdf_path):
    """Render the first page at thumbnail size in the CPU-only base process."""
    with fitz.open(pdf_path) as doc:
        if doc.page_count < 1:
            raise ValueError("PDF has no pages")
        pixmap = doc.load_page(0).get_pixmap(dpi=72, alpha=False)
        return pixmap.tobytes("png")


def _render_library_preview(pdf_path, page_number):
    """Render one PDF page in memory for the setup dialog's CPU-only preview."""
    with fitz.open(pdf_path) as doc:
        if not 1 <= page_number <= doc.page_count:
            raise ValueError("PDF page is outside the available range")
        page = doc.load_page(page_number - 1)
        width, height = page.rect.width, page.rect.height
        if width <= 0 or height <= 0:
            raise ValueError("PDF page has no visible area")
        scale = min(96 / 72, (MAX_PREVIEW_PIXELS / (width * height)) ** 0.5)
        pixmap = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
        return pixmap.tobytes("png")


def _job_cover_source(st):
    """Return (kind, path) for a job-owned cover without exposing paths to UI."""
    job_dir = JOBS_DIR / st["id"]
    override = job_dir / "cover_override.png"
    if override.is_file():
        return "image", override
    for cover in job_dir.glob("cover.*"):
        if cover.suffix.lower() in IMAGE_MIME and cover.is_file():
            return "image", cover
    for raw_pdf in (st.get("processed_pdf_path"), st.get("pdf_path")):
        if raw_pdf:
            pdf_path = Path(raw_pdf)
            allowed_roots = [PROCESSED_PDF_DIR, PDF_IMPORT_DIR, *LIBRARY_ROOTS]
            if pdf_path.is_file() and any(_path_is_within(pdf_path, root) for root in allowed_roots):
                return "pdf", pdf_path
    return None, None


def _job_cover_url(st):
    _kind, source = _job_cover_source(st)
    version = source.stat().st_mtime_ns if source else 0
    return f"/api/jobs/{st['id']}/cover?v={version}"


def _job_cover_bytes(st):
    kind, source = _job_cover_source(st)
    if kind == "image":
        return source.read_bytes(), IMAGE_MIME[source.suffix.lower()]
    if kind == "pdf":
        return _render_library_cover(source), "image/png"
    raise FileNotFoundError("cover not found")


def _validated_cover_png(raw):
    """Decode a local raster upload and normalize it to a bounded PNG."""
    if not raw or len(raw) > MAX_COVER_BYTES:
        raise ValueError("Choose an image smaller than 20 MB.")
    if raw.startswith(b"\x89PNG\r\n\x1a\n"):
        image_type = "png"
    elif raw.startswith(b"\xff\xd8\xff"):
        image_type = "jpeg"
    elif raw.startswith(b"RIFF") and raw[8:12] == b"WEBP":
        image_type = "webp"
    else:
        raise ValueError("Choose a PNG, JPEG, or WebP image.")
    try:
        with fitz.open(stream=raw, filetype=image_type) as doc:
            page = doc.load_page(0)
            if page.rect.width * page.rect.height > MAX_COVER_PIXELS:
                raise ValueError("Choose an image under 24 megapixels.")
            pixmap = page.get_pixmap(alpha=False)
            return pixmap.tobytes("png")
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError("That image could not be opened.") from exc


def _path_is_within(path, root):
    try:
        Path(path).resolve().relative_to(Path(root).resolve())
        return True
    except (OSError, ValueError):
        return False


def _unique_path(directory, filename):
    target = directory / filename
    stem, suffix = target.stem, target.suffix
    number = 2
    while target.exists():
        target = directory / f"{stem} ({number}){suffix}"
        number += 1
    return target


def archive_completed_pdf(st):
    """Move a completed job's app-managed PDF out of the active library.

    Never move a PDF from a configured external library such as samples or a
    user's own folder. Also leave it in place while another unfinished job
    still refers to the same source, because that job may need extraction on a
    later resume. Returns (new_path, error_message); archiving failure is a
    completion warning, not a reason to discard an already-built audiobook.
    """
    source = Path(st.get("pdf_path") or "")
    if not source.exists() or not source.is_file():
        return None, None
    if not _path_is_within(source, PDF_IMPORT_DIR):
        return None, None

    source_resolved = source.resolve()
    active_statuses = {
        "queued", "extracting", "tagging", "narrating",
        "interrupted", "failed", "canceled",
    }
    for other in list_jobs():
        if other.get("id") == st.get("id") or other.get("status") not in active_statuses:
            continue
        try:
            if Path(other.get("pdf_path") or "").resolve() == source_resolved:
                return None, "another unfinished job still uses this source PDF"
        except OSError:
            continue

    try:
        PROCESSED_PDF_DIR.mkdir(parents=True, exist_ok=True)
        target = _unique_path(PROCESSED_PDF_DIR, source.name)
        shutil.move(str(source), str(target))
        return str(target), None
    except Exception as exc:
        return None, str(exc)


# ---------- pipeline worker ----------

_queue = []
_queue_cv = threading.Condition()
_cancel_flags = {}
_active_procs = {"procs": [], "job_id": None}
_active_procs_lock = threading.Lock()


def enqueue(job_id):
    with _queue_cv:
        if job_id not in _queue:
            _queue.append(job_id)
            _queue_cv.notify()


def queue_persisted(st):
    st["status"] = "queued"
    st["queued_at"] = time.time()
    if not save_state(st):
        raise OSError("Could not save the queued job. Try again.")
    enqueue(st["id"])


def request_cancel(job_id):
    with _STATE_LOCK:
        st = load_state(job_id)
        if st and st["status"] in ("review_required", "queued"):
            st["status"] = "canceled"
            if not save_state(st):
                raise OSError("Could not save cancellation. Try again.")
        _cancel_flags[job_id] = True
        with _queue_cv:
            if job_id in _queue:
                _queue.remove(job_id)
        if st and narration_backend(st) == "vibevoice":
            (JOBS_DIR / job_id / "cancel_flag.txt").write_text("cancel", encoding="utf-8")
    with _active_procs_lock:
        procs = (list(_active_procs["procs"])
                 if _active_procs["job_id"] == job_id else [])
    _terminate_processes(procs)


def _set_active_processes(job_id, procs):
    with _active_procs_lock:
        _active_procs["job_id"] = job_id
        _active_procs["procs"] = list(procs)


def _clear_active_processes(job_id):
    with _active_procs_lock:
        if _active_procs["job_id"] == job_id:
            _active_procs["procs"] = []
            _active_procs["job_id"] = None


def _terminate_processes(procs):
    """Terminate the current owned process tree, then reap its root handles."""
    # A root worker can have a CPU quality-check child. Killing only the root
    # leaves that child running while the server remains alive, so close this
    # run's kill-on-close Job Object before reaping the root handles. The next
    # worker creates a fresh Job Object in _assign_worker_to_job.
    _close_worker_job(procs)
    for p in list(procs):
        try:
            if p.poll() is None:
                p.kill()
        except Exception:
            pass
    for p in list(procs):
        try:
            p.wait(timeout=10)
        except Exception:
            pass


def _cancelled(job_id):
    return _cancel_flags.pop(job_id, False) if job_id in _cancel_flags else False


def ocr_page(image_path):
    import base64

    with open(image_path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("utf-8")
    payload = {
        "model": OCR_MODEL,
        "prompt": OCR_PROMPT,
        "images": [b64],
        "stream": False,
        # num_predict caps runaway degenerate output on textless art
        # pages; real pages in this book are far under 4096 tokens.
        "options": {"temperature": 0, "num_ctx": 16384, "num_predict": 4096},
    }
    r = requests.post(OLLAMA_URL, json=payload, timeout=900)
    r.raise_for_status()
    return r.json()["response"]


def run_extraction(st):
    job_id = st["id"]
    job_dir = JOBS_DIR / job_id
    pdf = st["pdf_path"]
    p_from, p_to = st["page_from"], st["page_to"]
    total = p_to - p_from + 1

    if st["path"] == "A":
        st["status"] = "extracting"
        save_state(st)

        def cb(done, tot):
            if _cancelled(job_id):
                raise _Cancelled()
            st["stage_progress"] = {"stage": "extract", "done": done, "total": tot}
            save_state(st)

        blocks, text_mode = pt.extract_path_a(pdf, p_from, p_to, progress_cb=cb)
        if _cancelled(job_id):
            raise _Cancelled()
        st["text_mode"] = text_mode
        log_line(job_id, f"path A text mode: {text_mode}")
    else:
        pages_dir = job_dir / "pages"
        images_dir = job_dir / "images"
        pages_dir.mkdir(exist_ok=True)
        images_dir.mkdir(exist_ok=True)
        st["status"] = "extracting"
        save_state(st)
        page_blocks = []
        for idx, pno in enumerate(range(p_from - 1, p_to)):
            if _cancelled(job_id):
                raise _Cancelled()
            md_path = pages_dir / f"page_{pno + 1:04d}.md"
            if md_path.exists():
                md = md_path.read_text(encoding="utf-8")
            else:
                img_path = images_dir / f"page_{pno + 1:04d}.jpg"
                if not img_path.exists():
                    pt.rasterize_page(pdf, pno, str(img_path))
                md = ocr_page(str(img_path))
                md_path.write_text(md, encoding="utf-8")
            # An empty OCR response may be a blank page, artwork, or an OCR
            # failure. Preserve the uncertainty for an explicit manual skip;
            # nonempty source that copyright filtering removes is intentional.
            tagged = ([{"type": "visual", "text": "", "visual_kind": "unreadable OCR page"}]
                      if not md.strip() else pt.filter_copyright_blocks(pt.tag_blocks(md)))
            for block in tagged:
                block["source_page"] = pno + 1
            page_blocks.append(tagged)
            st["stage_progress"] = {"stage": "extract", "done": idx + 1, "total": total}
            save_state(st)
            log_line(job_id, f"extracted page {pno + 1} ({idx + 1}/{total})")
        blocks = pt.stitch_pages(page_blocks)

    if _cancelled(job_id):
        raise _Cancelled()

    # Keep extraction evidence separate from the narration projection. Visual
    # decisions may change blocks.json later, but never this source record.
    visual_review._write(job_dir / "source_blocks.json", {
        "blocks": blocks, "source_available": True,
    })
    (job_dir / "blocks.json").write_text(
        json.dumps({"blocks": blocks}, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    counts = {}
    for b in blocks:
        counts[b["type"]] = counts.get(b["type"], 0) + 1
    st["block_counts"] = counts
    log_line(job_id, f"tagged {len(blocks)} blocks: {counts}")
    return st


def gpu_total_vram_gb():
    """Total VRAM of GPU 0 in GB, or None if no NVIDIA GPU is present."""
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.total", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=15,
            creationflags=WINDOWS_NO_WINDOW,
        )
        if out.returncode != 0:
            return None
        return float(out.stdout.strip().splitlines()[0]) / 1024.0
    except Exception:
        return None


def narration_worker_count():
    """
    How many Chatterbox processes to run in parallel, sized to the GPU.
    A modest card (or CPU-only) gets 1; a big card gets several. Honors
    AUDIOBOOK_NUM_WORKERS as a hard override.
    """
    forced = os.environ.get("AUDIOBOOK_NUM_WORKERS")
    if forced:
        try:
            return max(1, min(MAX_WORKERS, int(forced)))
        except ValueError:
            pass
    vram = gpu_total_vram_gb()
    if not vram:
        return 1  # CPU or unknown GPU: one worker
    n = int((vram - VRAM_RESERVE_GB) / VRAM_PER_WORKER_GB)
    return max(1, min(MAX_WORKERS, n))


def scaled_batch_token_budget():
    """The batched engine's per-bucket VRAM budget, scaled down for cards
    smaller than the 4090 this was calibrated on.

    BATCH_TOKEN_BUDGET=1300 was measured to peak around 8 GB on a 24 GB
    card, and separately measured to NOT help further if raised even on
    that same 4090 (see CLAUDE.md), so 1300 stays a ceiling rather than
    something bigger cards get more of. This scales it down linearly by
    detected VRAM for anything smaller. This is a straight-line estimate,
    NOT a measurement on any card but the 4090: it assumes peak VRAM is
    roughly proportional to the token budget, which ignores the model's
    own fixed load footprint. Treat it as a way to make OOM less likely on
    the first try, not a guarantee; narrate_worker's per-bucket OOM retry
    is what actually recovers when this guess is still too high.
    An explicit AUDIOBOOK_BATCH_TOKEN_BUDGET env override always wins.
    """
    if os.environ.get("AUDIOBOOK_BATCH_TOKEN_BUDGET"):
        return BATCH_TOKEN_BUDGET
    vram = gpu_total_vram_gb()
    if not vram:
        return 300  # unknown GPU: stay conservative
    usable = max(0.0, vram - VRAM_RESERVE_GB)
    scaled = int(1300 * usable / (24.0 - VRAM_RESERVE_GB))
    return max(150, min(1300, scaled))


def _plan_hash(job_dir, st):
    """Identity of generated segment audio, excluding assembly-only metadata.

    Page provenance, chapter marks, pauses, and output format can all change at
    assembly time without changing a segment's spoken samples. Hash only the
    block fields that determine chunk text, plus the voice and planner version,
    so those metadata improvements never trigger an unnecessary re-narration.
    """
    payload = json.loads((job_dir / "blocks.json").read_text(encoding="utf-8"))
    spoken_blocks = [
        {"type": block.get("type"), "text": block.get("text", "")}
        for block in payload.get("blocks", [])
    ]
    blob = json.dumps(
        spoken_blocks, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")
    voice_sig = _voice_signature(st)
    key = b"\x00".join([
        blob,
        st["path"].encode(),
        voice_sig.encode(),
        PLAN_VERSION.encode(),
    ])
    return hashlib.sha256(key).hexdigest()


def _voice_signature(st):
    # Include the voice file's content signature (size + mtime), not just its
    # path, so overwriting a voice under the same name invalidates segments.
    vp = voice_wav_path(st.get("voice"))
    try:
        vstat = os.stat(vp)
        return f"{vp}:{vstat.st_size}:{vstat.st_mtime_ns}"
    except OSError:
        return vp


def _legacy_plan_hash(job_dir, st):
    """The pre-provenance hash, used only to migrate existing segment sets."""
    blob = (job_dir / "blocks.json").read_bytes()
    voice_sig = _voice_signature(st)
    key = b"\x00".join([
        blob,
        st["path"].encode(),
        voice_sig.encode(),
        PLAN_VERSION.encode(),
    ])
    return hashlib.sha256(key).hexdigest()


def ensure_segments_fresh(job_dir, st):
    seg_dir = job_dir / "segments"
    # Sweep any orphaned atomic-write temp files every run (a worker killed
    # between write and rename leaves one behind); do this regardless of the
    # hash so a strict progress count never trips over them.
    if seg_dir.exists():
        for t in seg_dir.glob("seg_*.tmp*.wav"):
            t.unlink()
    hp = job_dir / "plan_hash.txt"
    key = "v2:" + _plan_hash(job_dir, st)
    old = hp.read_text(encoding="utf-8").strip() if hp.exists() else None
    if old is None:
        stale = False
    elif old.startswith("v2:"):
        stale = old != key
    else:
        # Existing jobs have an unprefixed hash over the raw blocks.json.
        # Accept and migrate it only when it still matches exactly; this keeps
        # every validated segment while moving future resumes to the metadata-
        # independent identity.
        stale = old != _legacy_plan_hash(job_dir, st)
    if stale and seg_dir.exists():
        stale = list(seg_dir.glob("seg_*.wav"))
        for f in stale:
            f.unlink()
        log_line(st["id"], f"plan inputs changed; cleared {len(stale)} stale segments")
    hp.write_text(key, encoding="utf-8")


_SEG_RE = re.compile(r"seg_\d{6}\.wav$")


def _count_segments(seg_dir):
    """Count only finalized segments. glob('seg_*.wav') would also match the
    atomic-write temp files seg_NNNNNN.tmpK.wav, so match the exact name."""
    if not seg_dir.exists():
        return 0
    return sum(1 for f in seg_dir.glob("seg_??????.wav") if _SEG_RE.match(f.name))


def _directory_size(path):
    """Total bytes below a directory; missing paths are an empty cache."""
    path = Path(path)
    if not path.exists():
        return 0
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())


def cleanup_completed_job_cache(job_id):
    """Remove only resumable PCM segments from a completed job.

    The job record, extraction blocks, log, chapter metadata, job-local final
    output, and copied audiobook-library output are deliberately preserved.
    """
    st = load_state(job_id)
    if not st:
        raise ValueError("job not found")
    if st.get("status") != "done":
        raise ValueError("cache cleanup is only available for completed jobs")
    seg_dir = JOBS_DIR / job_id / ("vibevoice_segments" if narration_backend(st) == "vibevoice" else "segments")
    freed = _directory_size(seg_dir)
    if seg_dir.exists():
        shutil.rmtree(seg_dir)
    st["segment_cache_bytes"] = 0
    st["segment_cache_freed_bytes"] = st.get("segment_cache_freed_bytes", 0) + freed
    st["segment_cache_cleared_at"] = time.time()
    save_state(st)
    log_line(job_id, f"freed {freed} bytes of completed narration segment cache")
    return freed


def _ensure_segment_cache_stat(st, job_dir):
    """Populate cache size once for completed jobs created before this field."""
    seg_dir = Path(job_dir) / ("vibevoice_segments" if narration_backend(st) == "vibevoice" else "segments")
    if st.get("status") == "done" and (
        "segment_cache_bytes" not in st
        or (st.get("segment_cache_bytes", 0) and not seg_dir.exists())
    ):
        st["segment_cache_bytes"] = _directory_size(seg_dir)
        save_state(st)


def _discard_legacy_worker_pid_file(job_dir):
    """Remove unsafe pre-1.0.2 metadata without acting on reusable PIDs."""
    pf = job_dir / "worker_pids.txt"
    pf.unlink(missing_ok=True)


def _spawn_worker(job_dir, logf, extra_args, backend="chatterbox"):
    python, worker = (CHATTERBOX_PY, "narrate_worker.py")
    if backend == "vibevoice":
        python, worker = VIBEVOICE_PY, "vibevoice_worker.py"
    proc = subprocess.Popen(
        [python, str(APP_DIR / worker), str(job_dir), *extra_args],
        stdout=logf, stderr=subprocess.STDOUT, cwd=str(APP_DIR),
        creationflags=WINDOWS_NO_WINDOW,
    )
    proc._audiobook_started_at = time.time()
    try:
        _assign_worker_to_job(proc)
    except Exception:
        # Never continue with an unowned GPU worker. If this server exits, that
        # process could otherwise survive with no safe way to identify it.
        _terminate_processes([proc])
        raise
    return proc


def _narration_failure_message(job_dir, codes, backend="chatterbox"):
    """A worker's own clean diagnosis, if it wrote one, else the generic
    exit-code message. narrate_worker writes error.json for causes it can
    identify (currently: GPU out of memory even at a single chunk)."""
    err_file = job_dir / ("vibevoice_error.json" if backend == "vibevoice" else "error.json")
    if err_file.exists():
        try:
            data = json.loads(err_file.read_text(encoding="utf-8"))
            if data.get("message"):
                return data["message"]
        except Exception:
            pass
    return f"a narration worker failed (exit codes {codes}), see log"


def _wait_for_generation(proc, job_dir, engine, backend="chatterbox"):
    if backend == "vibevoice":
        progress_file = job_dir / "vibevoice_progress.json"
    elif engine != "batched":
        return proc.wait()
    else:
        progress_file = job_dir / PROGRESS_FILENAME
    while True:
        try:
            return proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            try:
                age = time.time() - progress_file.stat().st_mtime
            except FileNotFoundError:
                # The VibeVoice server sidecar and the legacy worker both
                # expose model loading before any audio is finalized.
                age = time.time() - getattr(proc, "_audiobook_started_at", time.time())
            if age > STALLED_BATCH_SECONDS:
                raise RuntimeError(
                    "Narration stopped because the worker made no progress for five minutes. "
                    "Completed segments are saved. Close other GPU-heavy applications "
                    "and resume the job."
                )


def _run_vibevoice_narration(st, job_dir, blocks):
    """Run the isolated VibeVoice worker without touching Chatterbox cache files."""
    import vibevoice_plan

    meta, cover, outline = extract_book_meta(st["pdf_path"], st["title"], job_dir)
    config = {
        "reference_wav": voice_wav_path(st.get("voice")),
        "model_dir": CFG.vibevoice_model_dir,
        "model_id": "microsoft/VibeVoice-1.5B",
        "model_revision": CFG.vibevoice_model_revision,
        "tokenizer_revision": CFG.vibevoice_tokenizer_revision,
        "cache_dir": CFG.vibevoice_cache_dir or None,
        "format": st.get("format", "m4b"),
        "title": st["title"],
        "metadata": meta,
        "cover_image": cover,
        "pdf_outline": outline,
        "dtype": "bfloat16",
        "cfg_scale": 2.0,
        "ddpm_steps": 20,
        "attention": "sdpa",
        "quality_python": CFG.vibevoice_quality_python or None,
        "quality_model": CFG.vibevoice_quality_model or None,
        "quality_major_words": 5,
        "quality_max_retries": 2,
    }
    config.update(runtime_settings("vibevoice", st["path"], st.get("generation_settings")))
    plan = vibevoice_plan.write_plan(job_dir, blocks, config)
    (job_dir / "cancel_flag.txt").unlink(missing_ok=True)
    progress_path = job_dir / "vibevoice_progress.json"
    # Only the worker can validate a VibeVoice WAV against its identity receipt.
    # Start neutral; it publishes the verified reusable count before model load.
    existing = 0
    total = len(plan.get("passages", [])) if isinstance(plan, dict) else 0
    progress_path.write_text(json.dumps({"done": existing, "total": total,
                                         "status": "checking_cache"}), encoding="utf-8")
    st.update(status="narrating", num_workers=1, narrate_started_at=time.time(),
              narrate_baseline_done=existing, vibevoice_total=total)
    save_state(st)
    log_line(st["id"], f"narrating with VibeVoice; {existing} passages already present")

    owned = []
    try:
        with open(job_dir / "log.txt", "a", encoding="utf-8") as logf:
            proc = _spawn_worker(job_dir, logf, ["--shard", "0", "--num-shards", "1"], "vibevoice")
            owned.append(proc)
            _set_active_processes(st["id"], [proc])
            if _cancel_flags.pop(st["id"], False):
                raise _Cancelled()
            code = _wait_for_generation(proc, job_dir, "", "vibevoice")
            _clear_active_processes(st["id"])
            if _cancel_flags.pop(st["id"], False) or code == 2:
                raise _Cancelled()
            if code != 0:
                raise RuntimeError(_narration_failure_message(job_dir, [code], "vibevoice"))
            log_line(st["id"], "generation complete, assembling")
            assembly = _spawn_worker(job_dir, logf, ["--assemble"], "vibevoice")
            owned.append(assembly)
            _set_active_processes(st["id"], [assembly])
            if _cancel_flags.pop(st["id"], False):
                assembly.kill()
                raise _Cancelled()
            code = assembly.wait()
            if code == 2 or _cancel_flags.pop(st["id"], False):
                raise _Cancelled()
            if code != 0:
                raise RuntimeError(_narration_failure_message(job_dir, [code], "vibevoice"))
    finally:
        _terminate_processes(owned)
        _clear_active_processes(st["id"])
    return st


def run_narration(st):
    job_id = st["id"]
    job_dir = JOBS_DIR / job_id
    blocks, unresolved, items, _decisions = visual_review.project(job_dir, st)
    if unresolved:
        raise _ReviewRequired()
    scope = visual_review.review_payload(job_dir, st)["narration_scope"]
    if (items or scope or st.get("preview_required")) and st.get("review_previewed_hash") != _preview_signature(st, job_dir, blocks):
        raise _ReviewRequired()
    if not any(str(block.get("text", "")).strip() for block in blocks):
        raise _ReviewRequired("No spoken text remains. Keep or describe a passage before narration.")
    visual_review._write(job_dir / "blocks.json", {"blocks": blocks})
    if narration_backend(st) == "vibevoice":
        return _run_vibevoice_narration(st, job_dir, blocks)
    engine = st.get("engine", DEFAULT_ENGINE)
    meta, cover, outline = extract_book_meta(st["pdf_path"], st["title"], job_dir)
    config = {
        "path": st["path"],
        "reference_wav": voice_wav_path(st.get("voice")),
        "title": st["title"],
        "format": st.get("format", "m4b"),
        "fallback_part_minutes": 240,
        "engine": engine,
        "batch_size": BATCH_SIZE,
        "batch_token_budget": (
            scaled_batch_token_budget() if engine == "batched" else BATCH_TOKEN_BUDGET
        ),
        "batch_s3gen": BATCH_S3GEN,
        "metadata": meta,
        "cover_image": cover,
        "pdf_outline": outline,
    }
    config.update(runtime_settings("chatterbox", st["path"], st.get("generation_settings")))
    if config["batch_preference"] == "conservative":
        config["batch_size"] = 1
    (job_dir / "config.json").write_text(json.dumps(config, indent=2), encoding="utf-8")
    ensure_segments_fresh(job_dir, st)
    (job_dir / PROGRESS_FILENAME).unlink(missing_ok=True)

    # The batched engine fills the GPU by batching sequences, so extra processes
    # would only time-slice against each other (Windows has no CUDA MPS).
    n = 1 if engine == "batched" else narration_worker_count()
    seg_dir = job_dir / "segments"
    baseline = _count_segments(seg_dir)  # segments already done from prior runs
    st["status"] = "narrating"
    st["num_workers"] = n
    st["narrate_started_at"] = time.time()
    st["narrate_baseline_done"] = baseline
    save_state(st)
    log_line(job_id, f"narrating with {n} parallel worker(s); {baseline} segments already present")

    owned = []
    try:
        with open(job_dir / "log.txt", "a", encoding="utf-8") as logf:
            # Generation: N shard processes covering disjoint chunks.
            procs = []
            for k in range(n):
                proc = _spawn_worker(
                    job_dir, logf, ["--shard", str(k), "--num-shards", str(n)]
                )
                procs.append(proc)
                owned.append(proc)
                _set_active_processes(job_id, procs)
                if _cancel_flags.pop(job_id, False):
                    raise _Cancelled()
            codes = [_wait_for_generation(p, job_dir, engine) for p in procs]
            _clear_active_processes(job_id)

            if _cancel_flags.pop(job_id, False):
                raise _Cancelled()
            if any(c != 0 for c in codes):
                raise RuntimeError(_narration_failure_message(job_dir, codes))

            # Assembly: one process, no model load. Register it BEFORE the cancel
            # check so a cancel arriving in this window still kills it.
            log_line(job_id, "generation complete, assembling")
            ap = _spawn_worker(job_dir, logf, ["--assemble"])
            owned.append(ap)
            _set_active_processes(job_id, [ap])
            if _cancel_flags.pop(job_id, False):
                ap.kill()
                raise _Cancelled()
            acode = ap.wait()
            _clear_active_processes(job_id)
    finally:
        _terminate_processes(owned)
        _clear_active_processes(job_id)
        _discard_legacy_worker_pid_file(job_dir)

    if _cancel_flags.pop(job_id, False):
        raise _Cancelled()
    if acode != 0:
        raise RuntimeError(f"assembly failed (exit {acode}), see log")
    return st


class _Cancelled(Exception):
    pass


class _ReviewRequired(Exception):
    pass


def _review_signature(blocks):
    spoken = [{"type": block.get("type"), "text": block.get("text", "")}
              for block in blocks]
    return hashlib.sha256(json.dumps(spoken, ensure_ascii=False,
                                     separators=(",", ":")).encode("utf-8")).hexdigest()


def _preview_signature(st, job_dir, blocks):
    """Keep legacy review signatures stable unless a VibeVoice page scope is active."""
    source, _items, decisions = visual_review.prepare(job_dir, st)
    scope = visual_review._scope(job_dir, st, source)
    if scope is None:
        return _review_signature(blocks)
    payload = {
        "version": 2,
        "spoken": [{"type": block.get("type"), "text": block.get("text", "")}
                   for block in blocks],
        "source_fingerprint": visual_review._source_fingerprint(source),
        "decisions": decisions,
        "scope": scope,
        "backend": narration_backend(st),
        "page_from": st.get("page_from"),
        "page_to": st.get("page_to"),
    }
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode("utf-8")).hexdigest()


def _narrated_signature_path(job_id):
    return JOBS_DIR / job_id / "narrated_projection_hash.txt"


def _record_narrated_signature(st, blocks=None):
    job_dir = JOBS_DIR / st["id"]
    if blocks is None:
        blocks, _unresolved, _items, _decisions = visual_review.project(job_dir, st)
    visual_review._write(_narrated_signature_path(st["id"]), {
        "signature": _preview_signature(st, job_dir, blocks)})


def _narration_is_stale(st):
    marker_path = _narrated_signature_path(st["id"])
    if not marker_path.exists():
        return bool(st.get("narration_stale"))
    try:
        marker = visual_review._required_json(marker_path)
        recorded = marker.get("signature") if isinstance(marker, dict) else None
        if not isinstance(recorded, str) or not re.fullmatch(r"[0-9a-f]{64}", recorded):
            return True
    except ValueError:
        return True
    try:
        job_dir = JOBS_DIR / st["id"]
        blocks, unresolved, _items, _decisions = visual_review.project(job_dir, st)
        return bool(unresolved) or recorded != _preview_signature(st, job_dir, blocks)
    except ValueError:
        return True


def _hold_for_visual_review(st):
    """Pause a job before GPU narration when any detected visual lacks review."""
    job_dir = JOBS_DIR / st["id"]
    blocks, unresolved, _items, _decisions = visual_review.project(job_dir, st)
    if not unresolved:
        if st.get("preview_required") and st.get("review_previewed_hash") != _preview_signature(st, job_dir, blocks):
            st["status"] = "review_required"
            st["visual_review_unresolved"] = 0
            save_state(st)
            return True
        if not any(str(block.get("text", "")).strip() for block in blocks):
            st["status"] = "review_required"
            st["error"] = "No spoken text remains. Keep or describe a passage before narration."
            save_state(st)
            return True
        visual_review._write(job_dir / "blocks.json", {"blocks": blocks})
        return False
    st["status"] = "review_required"
    st["visual_review_unresolved"] = len(unresolved)
    save_state(st)
    log_line(st["id"], f"waiting for review of {len(unresolved)} visual item(s)")
    return True


def _snapshot_prior_audio(st):
    """Keep current audio before an explicit review-driven regeneration."""
    job_dir = JOBS_DIR / st["id"]
    candidates = [(job_dir / "output", "job_output")]
    library = st.get("audiobook_dir")
    if library:
        candidates.append((Path(library), "library_output"))
    else:
        safe_title = re.sub(r"[^\w \-]", "", st.get("title", "")).strip()
        if safe_title:
            candidates.append((AUDIOBOOKS_DIR / safe_title, "library_output"))
    audio = [(source, label) for source, label in candidates
             if source.is_dir() and any(_visible_output_audio(f) for f in source.iterdir())]
    if not audio:
        return None
    snapshot = job_dir / "output_history" / str(time.time_ns())
    for source, label in audio:
        target = snapshot / label
        target.mkdir(parents=True, exist_ok=False)
        for file in source.iterdir():
            if _visible_output_audio(file):
                shutil.copy2(file, target / file.name)
    return str(snapshot)


def _gpu_report_info():
    """Best-effort 'name, VRAM' string for crash reports. Never raises;
    a report is worth sending even if this one field is unavailable."""
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader"],
            capture_output=True, text=True, timeout=15,
            creationflags=WINDOWS_NO_WINDOW,
        )
        if out.returncode != 0:
            return "no NVIDIA GPU detected"
        return out.stdout.strip().splitlines()[0]
    except Exception:
        return "unknown (nvidia-smi not available)"


def _report_crash(st, stage, exc):
    """Best-effort crash report to a Discord webhook, only if the owner has
    configured error_webhook_url (see config.py; disabled by default on
    every install). Deliberately sends ONLY structured fields, never book
    text: no chunk text, no blocks.json content, no log tail. Every
    exception message actually raised in this codebase (checked
    2026-08-23) is a static string or built from numbers/paths/exit codes,
    never book content, which is what makes str(exc) safe to include here
    as-is; keep future exception messages that way rather than assuming
    this function would filter anything out.

    Never allowed to raise: a Discord/network hiccup must never mask the
    real job failure this is reporting on top of."""
    url = CFG.error_webhook_url
    if not url:
        return
    payload = {
        "embeds": [{
            "title": f"Storybird job failed: {stage}",
            "color": 15548997,
            "fields": [
                {"name": "Error", "value": str(exc)[:1000] or "(empty)", "inline": False},
                {"name": "Stage", "value": str(stage), "inline": True},
                {"name": "Engine", "value": str(st.get("engine", DEFAULT_ENGINE)), "inline": True},
                {"name": "Job title", "value": str(st.get("title", "unknown")), "inline": True},
                {"name": "GPU", "value": _gpu_report_info(), "inline": False},
                {"name": "OS", "value": platform.platform(), "inline": False},
            ],
        }],
    }
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as report_exc:
        log_line(st["id"], f"crash report not sent: {report_exc}")


def worker_loop():
    while True:
        with _queue_cv:
            while not _queue:
                _queue_cv.wait()
            job_id = _queue.pop(0)
        with _STATE_LOCK:
            st = load_state(job_id)
            canceled = _cancel_flags.pop(job_id, False)
            if not st or st.get("status") != "queued":
                continue
            if canceled:
                st["status"] = "canceled"
                save_state(st)
                continue
            st["status"] = "extracting"
            st.pop("error", None)
            if not save_state(st):
                st["status"] = "queued"
                st["error"] = "Could not claim the queued job. Retrying shortly."
                save_state(st)
                retry_claim = True
            else:
                retry_claim = False
        if retry_claim:
            time.sleep(0.1)
            enqueue(job_id)
            continue
        try:
            if _cancelled(job_id):
                raise _Cancelled()
            if not (JOBS_DIR / job_id / "blocks.json").exists():
                st = run_extraction(st)
            if _cancelled(job_id):
                raise _Cancelled()
            if _hold_for_visual_review(st):
                continue
            if _cancelled(job_id):
                raise _Cancelled()
            st = run_narration(st)
            out_dir = JOBS_DIR / job_id / "output"
            book_dir = publish_finished_output(out_dir, AUDIOBOOKS_DIR, st)
            st["audiobook_dir"] = str(book_dir)

            original_pdf = st.get("pdf_path")
            processed_pdf, archive_error = archive_completed_pdf(st)
            if processed_pdf:
                st["source_pdf_original_path"] = original_pdf
                st["pdf_path"] = processed_pdf
                st["processed_pdf_path"] = processed_pdf
                save_state(st)
                log_line(job_id, f"source PDF moved to processed library: {processed_pdf}")
            elif archive_error:
                st["pdf_archive_error"] = archive_error
                log_line(job_id, f"WARNING: source PDF was not moved: {archive_error}")

            _record_narrated_signature(st)
            st["status"] = "done"
            st.pop("narration_stale", None)
            st["finished_at"] = time.time()
            st["segment_cache_bytes"] = _directory_size(
                JOBS_DIR / job_id / ("vibevoice_segments" if narration_backend(st) == "vibevoice" else "segments")
            )
            save_state(st)
            log_line(job_id, f"job complete, audiobook copied to {book_dir}")
        except _Cancelled:
            st["status"] = "canceled"
            save_state(st)
            log_line(job_id, "job canceled")
        except _ReviewRequired as exc:
            st["status"] = "review_required"
            if str(exc):
                st["error"] = str(exc)
            save_state(st)
            log_line(job_id, "narration held for visual review")
        except Exception as e:
            stage = st.get("status", "unknown")
            st["status"] = "failed"
            st["error"] = str(e)
            save_state(st)
            log_line(job_id, f"FAILED: {e}")
            _report_crash(st, stage, e)


def _narration_progress(job_dir, st):
    """Aggregate progress across all parallel workers by counting finished
    segments. Works regardless of worker count and survives resumes."""
    vibevoice = narration_backend(st) == "vibevoice"
    seg_dir = job_dir / ("vibevoice_segments" if vibevoice else "segments")
    total_file = job_dir / "plan_total.txt"
    total = 0
    if total_file.exists():
        try:
            total = int(total_file.read_text(encoding="utf-8").strip())
        except ValueError:
            total = 0
    done = _count_segments(seg_dir)
    n = st.get("num_workers", 1)
    started = st.get("narrate_started_at")
    elapsed = time.time() - started if started else 0
    # Rate must be measured over work done THIS run: on a resume, `done`
    # includes segments from prior runs that cost ~0 of this run's elapsed.
    baseline = st.get("narrate_baseline_done", 0)
    this_run = done - baseline
    eta = None
    progress_stale = False
    worker_status = None
    if vibevoice:
        try:
            progress_file = job_dir / "vibevoice_progress.json"
            progress = json.loads(progress_file.read_text(encoding="utf-8"))
            progress_stale = time.time() - progress_file.stat().st_mtime > STALE_PROGRESS_SECONDS
            done = int(progress.get("done", done))
            total = int(progress.get("total", st.get("vibevoice_total", total)))
            worker_status = progress.get("status")
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            total = st.get("vibevoice_total", total)
    elif st.get("engine") == "batched":
        try:
            progress_file = job_dir / PROGRESS_FILENAME
            progress = json.loads(progress_file.read_text(encoding="utf-8"))
            progress_stale = time.time() - progress_file.stat().st_mtime > STALE_PROGRESS_SECONDS
            worker_eta = progress.get("eta_sec")
            if not progress_stale and worker_eta is not None and float(worker_eta) >= 0:
                eta = float(worker_eta)
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            pass
    elif total and done < total and elapsed > 0 and this_run > 0:
        eta = (total - done) * (elapsed / this_run)
    if worker_status == "assembling" or (total and done >= total):
        eta = None
        message = "assembling"
    elif progress_stale:
        message = "current batch is taking longer than expected; time estimate unavailable"
    elif worker_status == "checking_cache":
        message = "checking resumable passages"
    elif worker_status == "quality_check":
        message = f"checking generated passage quality ({n} worker{'s' if n > 1 else ''})"
    elif worker_status == "loading_model" or (not worker_status and done == 0):
        message = f"loading model ({n} worker{'s' if n > 1 else ''})"
    else:
        message = f"generating ({n} worker{'s' if n > 1 else ''})"
    return {
        "done": done,
        "total": total,
        "elapsed_sec": round(elapsed, 1),
        "eta_sec": round(eta, 1) if eta is not None else None,
        "message": message,
    }


# ---------- HTTP ----------

def _json_response(handler, obj, code=200):
    body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
    handler.send_response(code)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def _safe_download_name(filename):
    return re.sub(r'[^A-Za-z0-9 .()_\-]', '_', filename).strip() or "download.txt"


def _visible_output_audio(path):
    """Hide all temporary and atomic audio files from finished-output APIs."""
    return visible_audio(path)


def _finished_audio_paths(st, formats=AUDIO_EXTS):
    """Return de-duplicated audio only from this job's owned output locations."""
    job_dir = JOBS_DIR / st["id"]
    locations = [job_dir / "output"]
    library = owned_library_directory(st, AUDIOBOOKS_DIR, list_jobs(include_hidden=True), job_dir=job_dir)
    if library:
        locations.append(library)
    paths, seen = [], set()
    for directory in locations:
        if not directory.is_dir():
            continue
        for path in sorted(directory.iterdir(), key=lambda item: item.name.lower()):
            if not _visible_output_audio(path) or path.suffix.lower() not in formats:
                continue
            contained(path, directory)
            key = os.path.normcase(str(path.resolve()))
            if key not in seen:
                seen.add(key)
                paths.append(path)
    return paths


def _export_finished_output(st, fmt):
    """Reuse a completed format or safely create it under the job's output folder."""
    if fmt not in {"m4b", "mp3", "wav"}:
        raise ValueError("Export format must be M4B, MP3, or WAV.")
    job_dir = JOBS_DIR / st["id"]
    output = job_dir / "output"
    existing = [path for path in _finished_audio_paths(st, {f".{fmt}"})
                if _path_is_within(path, output)]
    if existing:
        return existing[0]
    metadata = next((job_dir / name for name in ("chapters.ffmeta", "vibevoice.ffmeta")
                     if (job_dir / name).is_file()), None)
    sources = _finished_audio_paths(st, {".m4b", ".mp3"})
    if metadata:
        wav_sources = _finished_audio_paths(st, {".wav"})
        if wav_sources:
            sources = wav_sources + sources
    if not sources:
        sources = _finished_audio_paths(st, {".wav"})
    if not sources:
        raise ValueError("No finished audiobook audio is available to export.")
    output.mkdir(parents=True, exist_ok=True)
    title = re.sub(r"[^\w .()\-]", "", st.get("title", "")).strip() or "audiobook"
    target = _unique_path(output, f"{title} ({fmt.upper()}).{fmt}")
    ffmpeg = ffmpeg_status().get("path")
    if not ffmpeg:
        raise ValueError("Exporting another format needs ffmpeg, which is not installed on this machine.")
    cover_temporary = None
    try:
        kind, cover = _job_cover_source(st)
        if kind == "pdf":
            cover_temporary = job_dir / f".export-cover-{uuid.uuid4().hex}.png"
            cover_temporary.write_bytes(_render_library_cover(cover))
            cover = cover_temporary
        return export_finished_audio(sources[0], target, fmt, ffmpeg,
                                     metadata_path=metadata, cover_path=cover if kind else None)
    except AudiobookExportError as exc:
        raise ValueError(str(exc)) from exc
    finally:
        if cover_temporary:
            cover_temporary.unlink(missing_ok=True)


def regenerate_job(job_id, backend, settings=None):
    if backend not in ("vibevoice", "chatterbox"):
        raise ValueError("Choose VibeVoice or Chatterbox for regeneration.")
    original = load_state(job_id)
    if not original or original.get("status") != "done" or original.get("library_hidden"):
        raise ValueError("Regeneration needs a completed audiobook.")
    pdf = _review_pdf_path(original)
    if pdf is None:
        raise ValueError("The source PDF is unavailable. Restore it before regenerating.")
    errors = [missing_voice_error(original.get("voice")), missing_gpu_error(),
              missing_ffmpeg_error(original.get("format", "m4b"))]
    if backend == "vibevoice":
        errors.append(missing_vibevoice_error())
    if any(errors):
        raise ValueError(next(error for error in errors if error))
    settings = normalize_settings(backend, original.get("path", "B"), settings)
    new_id = str(uuid.uuid4())
    source = JOBS_DIR / job_id
    destination = JOBS_DIR / new_id
    state = {key: original[key] for key in ("title", "path", "page_from", "page_to", "voice", "format", "engine") if key in original}
    state.update(id=new_id, pdf_path=str(pdf), backend=backend, status="queued",
                 created_at=time.time(), regenerated_from=job_id, preview_required=True, generation_settings=settings)
    destination.mkdir()
    for name in ("source_blocks.json", "legacy_blocks.json", "blocks.json", "visual_review.json",
                 "narration_scope.json", "cover_override.png", "cover.png", "cover.jpg", "cover.jpeg"):
        path = source / name
        if path.is_file():
            contained(path, source)
            shutil.copy2(path, destination / name)
    if (destination / "blocks.json").exists():
        visual_review.project(destination, state)
    with _STATE_LOCK:
        queue_persisted(state)
    log_line(new_id, "created as a new generation; final text preview is required")
    return state


def _tail_text_lines(path, count=30, chunk_bytes=65536):
    """Read only enough of a potentially huge UTF-8 log to return its tail."""
    path = Path(path)
    with path.open("rb") as stream:
        stream.seek(0, os.SEEK_END)
        position = stream.tell()
        chunks = []
        newline_count = 0
        while position > 0 and newline_count <= count:
            size = min(chunk_bytes, position)
            position -= size
            stream.seek(position)
            chunk = stream.read(size)
            chunks.append(chunk)
            newline_count += chunk.count(b"\n")
    text = b"".join(reversed(chunks)).decode("utf-8", errors="replace")
    return text.splitlines()[-count:]


def job_detail(job_id):
    st = load_state(job_id)
    if not st:
        return None
    job_dir = JOBS_DIR / job_id
    scope = visual_review.scope_summary(job_dir, st)
    if scope:
        st["narration_range"] = {"from": scope["page_from"],
                                 "to": scope["end_page"],
                                 "original_to": scope["page_to"]}
    _ensure_segment_cache_stat(st, job_dir)
    if st.get("status") == "narrating":
        st["narrate_progress"] = _narration_progress(job_dir, st)
    log_path = job_dir / "log.txt"
    if log_path.exists():
        st["log_tail"] = _tail_text_lines(log_path, 30)
    out_dir = job_dir / "output"
    if out_dir.exists() and not _narration_is_stale(st):
        st["outputs"] = sorted(
            [{"name": f.name, "bytes": f.stat().st_size}
             for f in out_dir.iterdir() if _visible_output_audio(f)],
            key=lambda x: x["name"],
        )
    bl = job_dir / "blocks.json"
    if bl.exists() and "block_counts" not in st:
        blocks = json.loads(bl.read_text(encoding="utf-8"))["blocks"]
        counts = {}
        for b in blocks:
            counts[b["type"]] = counts.get(b["type"], 0) + 1
        st["block_counts"] = counts
    st["cover_url"] = _job_cover_url(st)
    return st


def _visual_review_detail(job_id):
    st = load_state(job_id)
    if not st:
        return None
    payload = visual_review.review_payload(JOBS_DIR / job_id, st)
    payload["status"] = st.get("status")
    payload["editable"] = st.get("status") not in ("queued", "extracting", "tagging", "narrating")
    payload["vibevoice_scope_available"] = narration_backend(st) == "vibevoice"
    if payload["vibevoice_scope_available"]:
        payload["original_page_range"] = {"from": st.get("page_from"), "to": st.get("page_to")}
    history = JOBS_DIR / job_id / "output_history"
    payload["history_available"] = history.is_dir() and any(history.iterdir())
    pdf_path = _review_pdf_path(st)
    for item in payload["items"]:
        page = item.get("source_page")
        if isinstance(page, int) and pdf_path:
            item["preview_url"] = f"/api/jobs/{job_id}/visual-review/{item['id']}/page-preview"
        else:
            item["preview_url"] = None
    return payload


def _review_pdf_path(st):
    for key in ("pdf_path", "processed_pdf_path", "source_pdf_original_path"):
        candidate = Path(str(st.get(key, "")))
        if candidate.is_file() and candidate.suffix.lower() == ".pdf":
            return candidate
    return None


def _full_narration_preview(job_id):
    with _STATE_LOCK:
        st = load_state(job_id)
        if not st:
            return None
        job_dir = JOBS_DIR / job_id
        blocks, unresolved, items, _decisions = visual_review.project(job_dir, st)
        preview_blocks = visual_review.preview_blocks(job_dir, st)
        text = "\n\n".join(block.get("text", "") for block in preview_blocks if block.get("text"))
        if not unresolved and st.get("status") not in ("queued", "extracting", "tagging", "narrating"):
            st["review_previewed_hash"] = _preview_signature(st, job_dir, blocks)
            save_state(st)
        scope = visual_review.review_payload(job_dir, st)["narration_scope"]
        return {"text": text, "unresolved_count": len(unresolved), "item_count": len(items),
                "narration_scope": scope}


def beta_test_report(job_id):
    """Build a compact summary for the downloadable beta-test bundle."""
    st = load_state(job_id)
    if not st:
        return None
    job_dir = JOBS_DIR / job_id
    _ensure_segment_cache_stat(st, job_dir)
    created = st.get("created_at")
    finished = st.get("finished_at")
    wall_time = None
    if isinstance(created, (int, float)) and isinstance(finished, (int, float)):
        wall_time = max(0, finished - created)

    gpu = "unavailable"
    try:
        r = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total,driver_version",
             "--format=csv,noheader"],
            capture_output=True, text=True, timeout=15,
            creationflags=WINDOWS_NO_WINDOW,
        )
        if r.returncode == 0 and r.stdout.strip():
            gpu = r.stdout.strip()
    except Exception as exc:
        gpu = f"unavailable ({exc})"

    log_path = job_dir / "log.txt"
    log_bytes = log_path.stat().st_size if log_path.exists() else 0
    report = [
        "Storybird beta test report",
        f"Generated: {time.strftime('%Y-%m-%d %H:%M:%S %Z')}",
        f"Computer: {platform.node() or '(unknown)'}",
        f"Windows/platform: {platform.platform()}",
        f"Python: {sys.version.replace(chr(10), ' ')}",
        f"Python executable: {sys.executable}",
        f"GPU: {gpu}",
        f"App directory: {CFG.base_dir}",
        f"Audiobook output library: {AUDIOBOOKS_DIR}",
        f"Complete job log bytes: {log_bytes}",
    ]
    if wall_time is not None:
        report.append(
            "Job wall time from creation through completion: "
            f"{wall_time:.1f} seconds ({wall_time / 3600:.2f} hours)"
        )
    report.extend([
        "",
        "JOB STATE",
        json.dumps(st, ensure_ascii=False, indent=2),
    ])
    return "\n".join(report).rstrip() + "\n"


def beta_test_bundle(job_id):
    """Return a ZIP containing complete logs but never book, voice or audio data."""
    summary = beta_test_report(job_id)
    if summary is None:
        return None
    job_dir = JOBS_DIR / job_id
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED,
                         compresslevel=6) as bundle:
        bundle.writestr("beta_summary.txt", summary.encode("utf-8"))
        candidates = [
            (job_dir / "log.txt", "job_log.txt"),
            (APP_DIR.parent / "launcher_log.txt", "launcher_log.txt"),
            (APP_DIR.parent / "install_log.txt", "install_log.txt"),
            (APP_DIR.parent / "miniconda_install_log.txt", "miniconda_install_log.txt"),
            (APP_DIR.parent / "install_warnings.txt", "install_warnings.txt"),
        ]
        for path, archive_name in candidates:
            if path.exists() and path.is_file():
                bundle.write(path, archive_name)
    return buffer.getvalue()


def open_job_output_folder(job_id):
    """Open a completed job's final output folder in Windows Explorer."""
    st = load_state(job_id)
    if not st:
        raise ValueError("Job not found.")
    raw = st.get("audiobook_dir")
    if not raw:
        raise ValueError("This job does not have a completed output folder yet.")
    target = Path(raw).resolve()
    root = AUDIOBOOKS_DIR.resolve()
    if not _path_is_within(target, root) or not target.is_dir():
        raise ValueError("The completed output folder is missing or outside the output library.")
    if not hasattr(os, "startfile"):
        raise ValueError("Opening folders is available only in the Windows app.")
    os.startfile(str(target))


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def _read_json(self):
        length = int(self.headers.get("Content-Length", 0))
        return json.loads(self.rfile.read(length) or b"{}")

    def do_HEAD(self):
        """Cheap availability check used for visible download feedback."""
        path = urlparse(self.path).path
        try:
            if re.fullmatch(r"/api/jobs/[0-9a-f-]+/beta-log", path):
                job_id = path.split("/")[3]
                st = load_state(job_id)
                if not st:
                    self.send_error(404)
                    return
                filename = _safe_download_name(
                    (st.get("title") or "audiobook") + " - beta test report.zip"
                )
                self.send_response(200)
                self.send_header("Content-Type", "application/zip")
                self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
                self.end_headers()
            elif re.fullmatch(r"/api/jobs/[0-9a-f-]+/audio/.+\.(wav|m4b|mp3)", path):
                job_id = path.split("/")[3]
                fname = unquote(path.split("/audio/", 1)[1])
                st = load_state(job_id)
                if not st or _narration_is_stale(st):
                    self.send_error(409)
                    return
                out_dir = (JOBS_DIR / job_id / "output").resolve()
                target = (out_dir / fname).resolve()
                if target.parent != out_dir or not _visible_output_audio(target):
                    self.send_error(404)
                    return
                self.send_response(200)
                self.send_header(
                    "Content-Type",
                    AUDIO_MIME.get(target.suffix.lower(), "application/octet-stream"),
                )
                filename = _safe_download_name(target.name)
                self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
                self.send_header("Content-Length", str(target.stat().st_size))
                self.end_headers()
            else:
                self.send_error(404)
        except Exception:
            self.send_error(500)

    def do_GET(self):
        path = urlparse(self.path).path
        try:
            if path == "/" or path == "/index.html":
                self._serve_file(STATIC_DIR / "index.html", "text/html; charset=utf-8")
            elif path in ("/storybird-mark.svg", "/storybird-library-book.svg"):
                self._serve_file(STATIC_DIR / path.lstrip("/"), "image/svg+xml")
            elif re.fullmatch(r"/api/library/cover/[0-9a-f]{24}", path):
                pdf_path = _library_pdf_for_cover(path.rsplit("/", 1)[1])
                if pdf_path is None:
                    self.send_error(404)
                else:
                    try:
                        image = _render_library_cover(pdf_path)
                    except Exception:
                        self.send_error(500)
                    else:
                        self.send_response(200)
                        self.send_header("Content-Type", "image/png")
                        self.send_header("Content-Length", str(len(image)))
                        self.send_header("Cache-Control", "private, max-age=3600")
                        self.end_headers()
                        self.wfile.write(image)
            elif re.fullmatch(r"/api/library/preview/[0-9a-f]{24}", path):
                from urllib.parse import parse_qs

                pdf_path = _library_pdf_for_cover(path.rsplit("/", 1)[1])
                page_values = parse_qs(urlparse(self.path).query).get("page", [])
                try:
                    page_number = int(page_values[0])
                except (IndexError, TypeError, ValueError):
                    page_number = 0
                if pdf_path is None:
                    self.send_error(404)
                elif page_number < 1:
                    _json_response(self, {"error": "Choose a PDF page starting at 1."}, 400)
                else:
                    try:
                        image = _render_library_preview(pdf_path, page_number)
                    except ValueError as exc:
                        _json_response(self, {"error": str(exc)}, 400)
                    except Exception:
                        self.send_error(500)
                    else:
                        self.send_response(200)
                        self.send_header("Content-Type", "image/png")
                        self.send_header("Content-Length", str(len(image)))
                        self.send_header("Cache-Control", "private, no-store")
                        self.end_headers()
                        self.wfile.write(image)
            elif path == "/api/library":
                _json_response(self, {"items": scan_library()})
            elif path == "/api/voices":
                _json_response(self, {"voices": list_voices()})
            elif path == "/api/ffmpeg":
                _json_response(self, ffmpeg_status())
            elif path == "/api/generation-settings":
                from urllib.parse import parse_qs
                query = parse_qs(urlparse(self.path).query)
                try:
                    defaults = default_settings(query.get("backend", [DEFAULT_BACKEND])[0], query.get("path", ["B"])[0])
                    _json_response(self, {"defaults": defaults})
                except ValueError as exc:
                    _json_response(self, {"error": str(exc)}, 400)
            elif path == "/api/jobs":
                _json_response(self, {"jobs": list_jobs()})
            elif path == "/api/update/check":
                _json_response(self, check_for_update())
            elif re.fullmatch(r"/api/jobs/[0-9a-f-]+", path):
                st = job_detail(path.rsplit("/", 1)[1])
                _json_response(self, st if st else {"error": "not found"}, 200 if st else 404)
            elif re.fullmatch(r"/api/jobs/[0-9a-f-]+/cover", path):
                st = load_state(path.split("/")[3])
                if not st:
                    self.send_error(404)
                else:
                    try:
                        image, content_type = _job_cover_bytes(st)
                    except FileNotFoundError:
                        self.send_error(404)
                    except Exception:
                        self.send_error(500)
                    else:
                        self.send_response(200)
                        self.send_header("Content-Type", content_type)
                        self.send_header("Content-Length", str(len(image)))
                        self.send_header("Cache-Control", "private, no-store")
                        self.end_headers()
                        self.wfile.write(image)
            elif re.fullmatch(r"/api/jobs/[0-9a-f-]+/blocks", path):
                job_id = path.split("/")[3]
                bl = JOBS_DIR / job_id / "blocks.json"
                if bl.exists():
                    self._serve_file(bl, "application/json; charset=utf-8")
                else:
                    _json_response(self, {"error": "no blocks yet"}, 404)
            elif re.fullmatch(r"/api/jobs/[0-9a-f-]+/visual-review", path):
                detail = _visual_review_detail(path.split("/")[3])
                _json_response(self, detail if detail else {"error": "not found"}, 200 if detail else 404)
            elif re.fullmatch(r"/api/jobs/[0-9a-f-]+/visual-review/preview", path):
                preview = _full_narration_preview(path.split("/")[3])
                _json_response(self, preview if preview else {"error": "not found"}, 200 if preview else 404)
            elif re.fullmatch(r"/api/jobs/[0-9a-f-]+/visual-review/[0-9a-f-]+/page-preview", path):
                parts = path.split("/")
                job_id, item_id = parts[3], parts[5]
                detail = _visual_review_detail(job_id)
                item = next((entry for entry in (detail or {}).get("items", []) if entry["id"] == item_id), None)
                st = load_state(job_id)
                if not item or not st or not isinstance(item.get("source_page"), int):
                    _json_response(self, {"error": "Page preview is unavailable for this visual."}, 404)
                else:
                    try:
                        pdf_path = _review_pdf_path(st)
                        if pdf_path is None:
                            raise ValueError("source PDF is unavailable")
                        image = _render_library_preview(pdf_path, item["source_page"])
                    except Exception:
                        _json_response(self, {"error": "Page preview is unavailable for this visual."}, 404)
                    else:
                        self.send_response(200)
                        self.send_header("Content-Type", "image/png")
                        self.send_header("Content-Length", str(len(image)))
                        self.send_header("Cache-Control", "private, no-store")
                        self.end_headers()
                        self.wfile.write(image)
            elif re.fullmatch(r"/api/jobs/[0-9a-f-]+/beta-log", path):
                job_id = path.split("/")[3]
                bundle = beta_test_bundle(job_id)
                if bundle is None:
                    _json_response(self, {"error": "not found"}, 404)
                else:
                    st = load_state(job_id) or {}
                    safe_title = re.sub(r"[^\w \-]", "", st.get("title", "audiobook")).strip()
                    self._serve_download(
                        bundle,
                        (safe_title or "audiobook") + " - beta test report.zip",
                        "application/zip",
                    )
            elif re.fullmatch(r"/api/jobs/[0-9a-f-]+/audio/.+\.(wav|m4b|mp3)", path):
                job_id = path.split("/")[3]
                fname = unquote(path.split("/audio/", 1)[1])
                out_dir = (JOBS_DIR / job_id / "output").resolve()
                target = (out_dir / fname).resolve()
                st = load_state(job_id)
                if not st or _narration_is_stale(st):
                    _json_response(self, {"error": "This audio is retained as a prior version and is not the current narration."}, 409)
                elif target.parent != out_dir or not _visible_output_audio(target):
                    self.send_error(404)
                else:
                    self._serve_audio(target)
            else:
                self.send_error(404)
        except (ConnectionAbortedError, BrokenPipeError):
            pass
        except Exception as e:
            try:
                _json_response(self, {"error": str(e)}, 500)
            except Exception:
                pass

    def do_POST(self):
        path = urlparse(self.path).path
        try:
            if path == "/api/ffmpeg/install":
                started = start_ffmpeg_install()
                st = ffmpeg_status()
                st["started"] = started
                _json_response(self, st)
            elif path == "/api/library/import":
                from urllib.parse import parse_qs

                q = parse_qs(urlparse(self.path).query)
                name = (q.get("name") or ["book.pdf"])[0]
                try:
                    length = int(self.headers.get("Content-Length", 0))
                    item = import_pdf(self.rfile, length, name)
                    _json_response(self, {"ok": True, "item": item})
                except (TypeError, ValueError) as exc:
                    _json_response(self, {"error": str(exc)}, 400)
            elif path == "/api/voices":
                from urllib.parse import parse_qs

                q = parse_qs(urlparse(self.path).query)
                name = (q.get("name") or ["voice"])[0]
                ext = (q.get("ext") or [".wav"])[0]
                if not re.fullmatch(r"\.\w{1,5}", ext):
                    ext = ".wav"
                length = int(self.headers.get("Content-Length", 0))
                if length > 100 * 1024 * 1024:
                    _json_response(self, {"error": "file too large"}, 400)
                    return
                raw = self.rfile.read(length)
                try:
                    saved = save_voice(name, raw, ext)
                    _json_response(self, {"ok": True, "name": saved})
                except Exception as e:
                    _json_response(self, {"error": str(e)}, 400)
            elif re.fullmatch(r"/api/voices/[^/]+/delete", path):
                name = unquote(path.split("/")[3])
                p = VOICES_DIR / (name + ".wav")
                if p.exists():
                    p.unlink()
                _json_response(self, {"ok": True})
            elif path == "/api/jobs":
                body = self._read_json()
                backend = body.get("backend") if body.get("backend") in ("chatterbox", "vibevoice") else DEFAULT_BACKEND
                # Preflight the voice before creating anything, so a fresh install
                # fails here with a clear message instead of hours into the job.
                verr = missing_voice_error(body.get("voice") or DEFAULT_VOICE)
                if verr:
                    _json_response(self, {"error": verr}, 400)
                    return False
                if backend == "vibevoice":
                    vibevoice_error = missing_vibevoice_error()
                    if vibevoice_error:
                        _json_response(self, {"error": vibevoice_error}, 400)
                        return
                # Same preflight for ffmpeg: refuse an m4b/mp3 job now rather
                # than failing the encode after the narration has finished.
                req_fmt = body.get("format") if body.get("format") in ("m4b", "mp3", "wav") else "m4b"
                ferr = missing_ffmpeg_error(req_fmt)
                if ferr:
                    _json_response(self, {"error": ferr, "ffmpeg_missing": True}, 400)
                    return
                gerr = missing_gpu_error()
                if gerr:
                    _json_response(self, {"error": gerr}, 400)
                    return
                try:
                    settings = normalize_settings(backend, body.get("path", "B"), body.get("generation_settings"))
                except ValueError as exc:
                    _json_response(self, {"error": str(exc)}, 400)
                    return
                job_id = str(uuid.uuid4())
                job_dir = JOBS_DIR / job_id
                job_dir.mkdir()
                n = page_count(body["pdf_path"]) or 1
                page_from = int(body.get("page_from", 1))
                page_to = int(body.get("page_to", n))
                if not 1 <= page_from <= page_to <= n:
                    _json_response(self, {"error": f"Choose pages from 1 through {n}, with the first page before the last."}, 400)
                    return
                st = {
                    "id": job_id,
                    "title": body.get("title") or Path(body["pdf_path"]).stem,
                    "pdf_path": body["pdf_path"],
                    "path": body.get("path", "B"),
                    "page_from": page_from,
                    "page_to": page_to,
                    "voice": body.get("voice") or DEFAULT_VOICE,
                    "format": body.get("format") if body.get("format") in ("m4b", "mp3", "wav") else "m4b",
                    "backend": backend,
                    "generation_settings": settings,
                    "engine": body.get("engine") if body.get("engine") in ("parallel", "batched") else DEFAULT_ENGINE,
                    "status": "queued",
                    "created_at": time.time(),
                }
                st["queued_at"] = time.time()
                if not save_state(st):
                    raise OSError("Could not save the queued job. Try again.")
                log_line(job_id, f"created: {st['title']} path {st['path']} pages {st['page_from']}..{st['page_to']}")
                enqueue(job_id)
                _json_response(self, st)
            elif re.fullmatch(r"/api/jobs/[0-9a-f-]+/cover", path):
                job_id = path.split("/")[3]
                length = int(self.headers.get("Content-Length", 0))
                if not 0 < length <= MAX_COVER_BYTES:
                    _json_response(self, {"error": "Choose an image smaller than 20 MB."}, 400)
                    return
                try:
                    with _job_mutation_lock(job_id):
                        st = load_state(job_id)
                        if not st:
                            _json_response(self, {"error": "not found"}, 404)
                            return
                        if st.get("status") != "done" or _narration_is_stale(st):
                            _json_response(self, {"error": "A cover can be changed after current narration finishes."}, 409)
                            return
                        png = _validated_cover_png(self.rfile.read(length))
                        job_dir = JOBS_DIR / job_id
                        upload = job_dir / f".cover-upload-{uuid.uuid4().hex}.png"
                        try:
                            upload.write_bytes(png)
                            audio = _finished_audio_paths(st, {".m4b", ".mp3"})
                            if audio:
                                ffmpeg = ffmpeg_status().get("path")
                                if not ffmpeg:
                                    raise ValueError("Updating embedded artwork needs ffmpeg, which is not installed on this machine.")
                                replace_finished_artwork(audio, upload, ffmpeg,
                                                         cover_target=job_dir / "cover_override.png")
                                message = "Cover updated in the finished audiobook files."
                            else:
                                target = job_dir / "cover_override.png"
                                temporary = job_dir / f".cover-override-{uuid.uuid4().hex}.tmp"
                                temporary.write_bytes(png)
                                os.replace(temporary, target)
                                message = "Cover updated for the app. WAV files do not support embedded artwork."
                        finally:
                            upload.unlink(missing_ok=True)
                    _json_response(self, {"ok": True, "cover_url": _job_cover_url(st), "message": message})
                except (ArtworkReplacementError, ValueError) as exc:
                    _json_response(self, {"error": str(exc)}, 400)
            elif re.fullmatch(r"/api/jobs/[0-9a-f-]+/export", path):
                job_id = path.split("/")[3]
                body = self._read_json()
                with _job_mutation_lock(job_id):
                    st = load_state(job_id)
                    if not st:
                        _json_response(self, {"error": "not found"}, 404)
                        return
                    if st.get("status") != "done" or _narration_is_stale(st):
                        _json_response(self, {"error": "Export is available after current narration finishes."}, 409)
                        return
                    try:
                        output = _export_finished_output(st, body.get("format"))
                    except ValueError as exc:
                        _json_response(self, {"error": str(exc)}, 400)
                        return
                _json_response(self, {"ok": True, "output": {"name": output.name, "bytes": output.stat().st_size}})
            elif re.fullmatch(r"/api/jobs/[0-9a-f-]+/cancel", path):
                job_id = path.split("/")[3]
                request_cancel(job_id)
                _json_response(self, {"ok": True})
            elif re.fullmatch(r"/api/jobs/[0-9a-f-]+/resume", path):
                job_id = path.split("/")[3]
                with _job_mutation_lock(job_id):
                    with _STATE_LOCK:
                        st = load_state(job_id)
                        if st and st["status"] in ("failed", "canceled", "interrupted"):
                            st.pop("error", None)
                            _cancel_flags.pop(job_id, None)  # no stale cancel survives into the retry
                            queue_persisted(st)
                            _json_response(self, {"ok": True})
                        else:
                            _json_response(self, {"error": "job not resumable"}, 400)
            elif re.fullmatch(r"/api/jobs/[0-9a-f-]+/visual-review/scope", path):
                job_id = path.split("/")[3]
                body = self._read_json()
                with _job_mutation_lock(job_id), _STATE_LOCK:
                    st = load_state(job_id)
                    if not st:
                        _json_response(self, {"error": "not found"}, 404)
                        return
                    if narration_backend(st) != "vibevoice":
                        _json_response(self, {"error": "Narrate through page is available for VibeVoice jobs only."}, 409)
                        return
                    if st.get("status") in ("queued", "extracting", "tagging", "narrating"):
                        _json_response(self, {"error": "Stop or wait for the job before changing its narration range."}, 409)
                        return
                    job_dir = JOBS_DIR / job_id
                    try:
                        old_blocks, old_unresolved, _items, _decisions = visual_review.project(job_dir, st)
                        old_signature = _preview_signature(st, job_dir, old_blocks)
                        scope = visual_review.set_scope(job_dir, st, body.get("end_page"))
                        blocks, unresolved, _items, _decisions = visual_review.project(job_dir, st)
                    except ValueError as exc:
                        _json_response(self, {"error": str(exc)}, 400)
                        return
                    if old_signature != _preview_signature(st, job_dir, blocks):
                        st["narration_stale"] = True
                    st["status"] = "review_required"
                    st["visual_review_unresolved"] = len(unresolved)
                    st.pop("review_previewed_hash", None)
                    save_state(st)
                _json_response(self, {"ok": True, "narration_scope": scope,
                                      **_visual_review_detail(job_id)})
            elif re.fullmatch(r"/api/jobs/[0-9a-f-]+/visual-review/[0-9a-f-]+", path):
                parts = path.split("/")
                job_id, item_id = parts[3], parts[5]
                body = self._read_json()
                with _job_mutation_lock(job_id), _STATE_LOCK:
                    st = load_state(job_id)
                    if not st:
                        _json_response(self, {"error": "not found"}, 404)
                        return
                    if st.get("status") in ("queued", "extracting", "tagging", "narrating"):
                        _json_response(self, {"error": "Stop or wait for the job before editing review decisions."}, 409)
                        return
                    job_dir = JOBS_DIR / job_id
                    old_blocks, _old_unresolved, _old_items, _old_decisions = visual_review.project(job_dir, st)
                    old_output = JOBS_DIR / job_id / "output"
                    if (old_output.exists() and any(f.suffix.lower() in AUDIO_EXTS for f in old_output.iterdir())
                            and not _narrated_signature_path(job_id).exists()):
                        _record_narrated_signature(st, old_blocks)
                    old_signature = _preview_signature(st, job_dir, old_blocks)
                    try:
                        blocks, unresolved, _items, _decisions = visual_review.save_decision(
                            job_dir, item_id, body.get("fingerprint"),
                            body.get("decision"), body.get("spoken_text", ""), st,
                        )
                    except ValueError as exc:
                        _json_response(self, {"error": str(exc)}, 400)
                        return
                    if not unresolved:
                        visual_review._write(job_dir / "blocks.json", {"blocks": blocks})
                        if old_signature != _preview_signature(st, job_dir, blocks):
                            st["narration_stale"] = True
                    st["status"] = "review_required"
                    st["visual_review_unresolved"] = len(unresolved)
                    st.pop("review_previewed_hash", None)
                    save_state(st)
                _json_response(self, _visual_review_detail(job_id))
            elif re.fullmatch(r"/api/jobs/[0-9a-f-]+/visual-review/reopen", path):
                job_id = path.split("/")[3]
                with _job_mutation_lock(job_id), _STATE_LOCK:
                    st = load_state(job_id)
                    if not st:
                        _json_response(self, {"error": "not found"}, 404)
                        return
                    if st.get("status") in ("queued", "extracting", "tagging", "narrating"):
                        _json_response(self, {"error": "Stop or wait for the job before reopening review."}, 409)
                        return
                    detail = visual_review.review_payload(JOBS_DIR / job_id, st)
                    st["status"] = "review_required"
                    st["visual_review_unresolved"] = detail["unresolved_count"]
                    st.pop("review_previewed_hash", None)
                    save_state(st)
                _json_response(self, {"ok": True, **_visual_review_detail(job_id)})
            elif re.fullmatch(r"/api/jobs/[0-9a-f-]+/visual-review/start", path):
                job_id = path.split("/")[3]
                with _job_mutation_lock(job_id), _STATE_LOCK:
                    st = load_state(job_id)
                    if not st or st.get("status") not in ("review_required", "done", "failed", "canceled", "interrupted"):
                        _json_response(self, {"error": "review is not ready to start"}, 409)
                        return
                    job_dir = JOBS_DIR / job_id
                    if narration_backend(st) != "vibevoice" and not st.get("regenerated_from") and visual_review.review_payload(job_dir, st)["narration_scope"]:
                        _json_response(self, {"error": "Narrate through page is available for VibeVoice jobs only."}, 409)
                        return
                    blocks, unresolved, _items, _decisions = visual_review.project(job_dir, st)
                    if unresolved:
                        _json_response(self, {"error": "Save a decision for every visual before narration."}, 409)
                        return
                    if not any(str(block.get("text", "")).strip() for block in blocks):
                        _json_response(self, {"error": "No spoken text remains. Keep or describe a passage before narration."}, 409)
                        return
                    signature = _preview_signature(st, job_dir, blocks)
                    if st.get("review_previewed_hash") != signature:
                        _json_response(self, {"error": "Open the full narration preview after your latest review changes."}, 409)
                        return
                    snapshot = _snapshot_prior_audio(st)
                    visual_review._write(job_dir / "blocks.json", {"blocks": blocks})
                    st["visual_review_unresolved"] = 0
                    st.pop("error", None)
                    _cancel_flags.pop(job_id, None)
                    if snapshot:
                        st["previous_output_snapshot"] = snapshot
                    queue_persisted(st)
                _json_response(self, {"ok": True})
            elif re.fullmatch(r"/api/jobs/[0-9a-f-]+/regenerate", path):
                job_id = path.split("/")[3]
                body = self._read_json()
                try:
                    with _job_mutation_lock(job_id):
                        result = regenerate_job(job_id, body.get("backend"), body.get("generation_settings"))
                    _json_response(self, result)
                except ValueError as exc:
                    _json_response(self, {"error": str(exc)}, 400)
            elif re.fullmatch(r"/api/jobs/[0-9a-f-]+/delete", path):
                job_id = path.split("/")[3]
                body = self._read_json()
                if body.get("confirmed") is not True or body.get("mode") not in ("library", "generated"):
                    _json_response(self, {"error": "Choose what to remove and confirm deletion."}, 400)
                    return
                with _job_mutation_lock(job_id), _STATE_LOCK:
                    st = load_state(job_id)
                    if not st or st.get("status") in ("queued", "extracting", "tagging", "narrating"):
                        _json_response(self, {"error": "Stop the job before deleting it."}, 409)
                        return
                    freed = 0
                    if body["mode"] == "generated":
                        st["status"] = "deleting"
                        st["delete_requested_at"] = time.time()
                        if not save_state(st):
                            raise OSError("Could not record deletion. No generated files were removed.")
                        try:
                            freed = delete_generated_files(JOBS_DIR / job_id, st, AUDIOBOOKS_DIR, list_jobs(include_hidden=True))
                        except (ValueError, OSError) as exc:
                            st["status"] = "delete_failed"
                            st["error"] = str(exc)
                            save_state(st)
                            _json_response(self, {"error": str(exc)}, 409)
                            return
                        st["status"] = "deleted"
                        st.pop("error", None)
                        st["generated_files_deleted_at"] = time.time()
                        st["segment_cache_bytes"] = 0
                    st["library_hidden"] = True
                    if not save_state(st):
                        raise OSError("The file operation finished, but its library update could not be saved. Retry deletion to finish updating the record.")
                _json_response(self, {"ok": True, "freed_bytes": freed})
            elif re.fullmatch(r"/api/jobs/[0-9a-f-]+/cleanup-cache", path):
                job_id = path.split("/")[3]
                try:
                    freed = cleanup_completed_job_cache(job_id)
                    _json_response(self, {"ok": True, "freed_bytes": freed})
                except ValueError as exc:
                    _json_response(self, {"error": str(exc)}, 400)
            elif re.fullmatch(r"/api/jobs/[0-9a-f-]+/open-output", path):
                job_id = path.split("/")[3]
                try:
                    open_job_output_folder(job_id)
                    _json_response(self, {"ok": True})
                except ValueError as exc:
                    _json_response(self, {"error": str(exc)}, 400)
            else:
                self.send_error(404)
        except (ConnectionAbortedError, BrokenPipeError):
            pass
        except Exception as e:
            try:
                _json_response(self, {"error": str(e)}, 500)
            except Exception:
                pass

    def _serve_file(self, fpath, ctype):
        data = Path(fpath).read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _serve_download(self, data, filename, ctype):
        safe_name = _safe_download_name(filename)
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Disposition", f'attachment; filename="{safe_name}"')
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _serve_audio(self, fpath):
        fpath = Path(fpath)
        if not fpath.exists():
            self.send_error(404)
            return
        size = fpath.stat().st_size
        range_header = self.headers.get("Range")
        start, end = 0, size - 1
        if range_header:
            m = re.match(r"bytes=(\d*)-(\d*)", range_header)
            if m:
                if m.group(1):
                    start = int(m.group(1))
                if m.group(2):
                    end = min(int(m.group(2)), size - 1)
                elif not m.group(1):
                    start = 0
        length = end - start + 1
        self.send_response(206 if range_header else 200)
        self.send_header("Content-Type", AUDIO_MIME.get(fpath.suffix.lower(), "application/octet-stream"))
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(length))
        if range_header:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.end_headers()
        with open(fpath, "rb") as f:
            f.seek(start)
            remaining = length
            while remaining > 0:
                chunk = f.read(min(65536, remaining))
                if not chunk:
                    break
                self.wfile.write(chunk)
                remaining -= len(chunk)


def mark_interrupted_jobs():
    queued = []
    for st in list_jobs():
        # Delete unsafe legacy metadata for every job state. It is never
        # authority to terminate a process, even if the job already failed.
        _discard_legacy_worker_pid_file(JOBS_DIR / st["id"])
        if st["status"] == "deleting":
            st["status"] = "delete_failed"
            st["error"] = "Deletion was interrupted. Retry Delete to remove any remaining generated files."
            save_state(st)
        elif st["status"] in ("extracting", "tagging", "narrating"):
            # New builds cannot orphan workers: the owning Job Object is
            # killed when the old server handle closes. Old PID metadata is
            # untrusted because Windows may have reused the number, so only
            # discard it; never taskkill an unknown process.
            st["status"] = "interrupted"
            save_state(st)
        elif st["status"] == "queued":
            queued.append(st)
    def queued_time(st, key):
        value = st.get(key)
        return value if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) else 0
    with _queue_cv:
        _queue[:] = [st["id"] for st in sorted(queued, key=lambda st: (
            queued_time(st, "queued_at") or queued_time(st, "created_at"), st["id"]))]
        _queue_cv.notify_all()


def main():
    for line in CFG.warnings():
        print(f"[config] WARNING: {line}")
    mark_interrupted_jobs()
    threading.Thread(target=worker_loop, daemon=True).start()
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print(f"Storybird running at http://localhost:{PORT}")
    print(f"  chatterbox python: {CHATTERBOX_PY}")
    print(f"  audiobooks dir:    {AUDIOBOOKS_DIR}")
    print(f"  library roots:     {', '.join(str(r) for r in LIBRARY_ROOTS) or '(none)'}")
    server.serve_forever()


if __name__ == "__main__":
    main()
