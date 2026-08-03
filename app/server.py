"""
Audiobook Studio server. Runs in the base miniconda env (stdlib +
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
from config import CFG

APP_DIR = Path(__file__).parent
JOBS_DIR = APP_DIR / "jobs"
STATIC_DIR = APP_DIR / "static"
VOICES_DIR = APP_DIR / "voices"

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
OLLAMA_URL = CFG.ollama_url
OCR_MODEL = CFG.ocr_model
OCR_PROMPT = CFG.ocr_prompt
PORT = CFG.port

AUDIO_EXTS = {".m4b", ".mp3", ".wav"}
AUDIO_MIME = {".m4b": "audio/mp4", ".mp3": "audio/mpeg", ".wav": "audio/wav"}
MAX_PDF_BYTES = 2 * 1024 * 1024 * 1024
WINDOWS_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0

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
        r = subprocess.run(
            [CHATTERBOX_PY, str(APP_DIR / "convert_voice.py"), str(tmp_in), str(out)],
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
                return
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


def list_jobs():
    out = []
    for d in sorted(JOBS_DIR.iterdir(), key=lambda p: p.name, reverse=True):
        if d.is_dir():
            st = load_state(d.name)
            if st:
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
        "pages": pages,
        "suggested_path": suggest_path(pdf_path, pages) if pages else "B",
        "suggested_page_from": suggested_start,
        "suggested_start_reason": start_reason,
    }


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
    the narration worker does not). Returns (metadata_dict, cover_path_or_None).
    Cover: the first embedded image on page 1, else page 1 rendered. Never
    fatal - a missing cover or metadata just yields fewer tags."""
    meta = {"title": title, "album": title, "genre": "Audiobook",
            "media_type": "2"}  # 2 = Audiobook in the iTunes/MP4 stik atom
    cover_path = None
    try:
        doc = fitz.open(pdf_path)
        pdf_meta = doc.metadata or {}
        if pdf_meta.get("author"):
            meta["artist"] = pdf_meta["author"]      # narrator/author field
            meta["album_artist"] = pdf_meta["author"]
        if pdf_meta.get("title"):
            meta["title"] = meta["album"] = pdf_meta["title"]
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
    return meta, cover_path


def scan_library():
    seen = set()
    items = []
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
            items.append(_library_item(p))
    return items


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


def enqueue(job_id):
    with _queue_cv:
        if job_id not in _queue:
            _queue.append(job_id)
            _queue_cv.notify()


def request_cancel(job_id):
    _cancel_flags[job_id] = True
    with _queue_cv:
        if job_id in _queue:
            _queue.remove(job_id)
            st = load_state(job_id)
            if st and st["status"] == "queued":
                st["status"] = "canceled"
                save_state(st)
    if _active_procs["job_id"] == job_id:
        for p in _active_procs["procs"]:
            try:
                p.kill()
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
            st["stage_progress"] = {"stage": "extract", "done": done, "total": tot}
            save_state(st)

        blocks, text_mode = pt.extract_path_a(pdf, p_from, p_to, progress_cb=cb)
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
            page_blocks.append(pt.tag_blocks(md))
            st["stage_progress"] = {"stage": "extract", "done": idx + 1, "total": total}
            save_state(st)
            log_line(job_id, f"extracted page {pno + 1} ({idx + 1}/{total})")
        blocks = pt.stitch_pages(page_blocks)

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


def _plan_hash(job_dir, st):
    """Identity of the segment set: if any input that determines the audio
    changes (text, voice, pause profile, planner version), old segments are
    stale and must be regenerated."""
    blob = (job_dir / "blocks.json").read_bytes()
    # Include the voice file's content signature (size + mtime), not just its
    # path, so overwriting a voice under the same name invalidates segments.
    vp = voice_wav_path(st.get("voice"))
    try:
        vstat = os.stat(vp)
        voice_sig = f"{vp}:{vstat.st_size}:{vstat.st_mtime_ns}"
    except OSError:
        voice_sig = vp
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
    key = _plan_hash(job_dir, st)
    old = hp.read_text(encoding="utf-8").strip() if hp.exists() else None
    if old is not None and old != key and seg_dir.exists():
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


def _write_worker_pids(job_dir, procs):
    (job_dir / "worker_pids.txt").write_text(
        "\n".join(str(p.pid) for p in procs), encoding="utf-8"
    )


def _reap_worker_pids(job_dir):
    """Kill any narration workers left over from a previous server process
    (Windows does not terminate children when the parent dies)."""
    pf = job_dir / "worker_pids.txt"
    if not pf.exists():
        return
    for line in pf.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line.isdigit():
            continue
        try:
            subprocess.run(["taskkill", "/F", "/PID", line],
                           capture_output=True, timeout=10,
                           creationflags=WINDOWS_NO_WINDOW)
        except Exception:
            pass
    pf.unlink(missing_ok=True)


def _spawn_worker(job_dir, logf, extra_args):
    return subprocess.Popen(
        [CHATTERBOX_PY, str(APP_DIR / "narrate_worker.py"), str(job_dir), *extra_args],
        stdout=logf, stderr=subprocess.STDOUT, cwd=str(APP_DIR),
        creationflags=WINDOWS_NO_WINDOW,
    )


def run_narration(st):
    job_id = st["id"]
    job_dir = JOBS_DIR / job_id
    engine = st.get("engine", DEFAULT_ENGINE)
    meta, cover = extract_book_meta(st["pdf_path"], st["title"], job_dir)
    config = {
        "path": st["path"],
        "reference_wav": voice_wav_path(st.get("voice")),
        "title": st["title"],
        "format": st.get("format", "m4b"),
        "fallback_part_minutes": 240,
        "engine": engine,
        "batch_size": BATCH_SIZE,
        "batch_token_budget": BATCH_TOKEN_BUDGET,
        "batch_s3gen": BATCH_S3GEN,
        "metadata": meta,
        "cover_image": cover,
    }
    (job_dir / "config.json").write_text(json.dumps(config, indent=2), encoding="utf-8")
    ensure_segments_fresh(job_dir, st)

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

    with open(job_dir / "log.txt", "a", encoding="utf-8") as logf:
        # Generation: N shard processes covering disjoint chunks.
        procs = [_spawn_worker(job_dir, logf, ["--shard", str(k), "--num-shards", str(n)])
                 for k in range(n)]
        _write_worker_pids(job_dir, procs)
        _active_procs["procs"] = procs
        _active_procs["job_id"] = job_id
        codes = [p.wait() for p in procs]
        _active_procs["procs"] = []
        _active_procs["job_id"] = None

        if _cancel_flags.pop(job_id, False):
            raise _Cancelled()
        if any(c != 0 for c in codes):
            raise RuntimeError(f"a narration worker failed (exit codes {codes}), see log")

        # Assembly: one process, no model load. Register it BEFORE the cancel
        # check so a cancel arriving in this window still kills it.
        log_line(job_id, "generation complete, assembling")
        ap = _spawn_worker(job_dir, logf, ["--assemble"])
        _active_procs["procs"] = [ap]
        _active_procs["job_id"] = job_id
        _write_worker_pids(job_dir, [ap])
        if _cancel_flags.pop(job_id, False):
            ap.kill()
            _active_procs["procs"] = []
            _active_procs["job_id"] = None
            raise _Cancelled()
        acode = ap.wait()
        _active_procs["procs"] = []
        _active_procs["job_id"] = None

    (job_dir / "worker_pids.txt").unlink(missing_ok=True)

    if _cancel_flags.pop(job_id, False):
        raise _Cancelled()
    if acode != 0:
        raise RuntimeError(f"assembly failed (exit {acode}), see log")
    return st


class _Cancelled(Exception):
    pass


def worker_loop():
    while True:
        with _queue_cv:
            while not _queue:
                _queue_cv.wait()
            job_id = _queue.pop(0)
        st = load_state(job_id)
        if not st:
            continue
        try:
            if not (JOBS_DIR / job_id / "blocks.json").exists():
                st = run_extraction(st)
            st = run_narration(st)
            out_dir = JOBS_DIR / job_id / "output"
            safe_title = re.sub(r"[^\w \-]", "", st["title"]).strip() or job_id
            book_dir = AUDIOBOOKS_DIR / safe_title
            book_dir.mkdir(parents=True, exist_ok=True)
            # Deliver whatever format the job produced; clear old copies
            # so a re-run with a new format does not leave both behind.
            for old in book_dir.glob("*"):
                if old.suffix.lower() in AUDIO_EXTS:
                    old.unlink()
            for f in sorted(out_dir.iterdir()):
                if f.suffix.lower() in AUDIO_EXTS:
                    shutil.copy2(f, book_dir / f.name)
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

            st["status"] = "done"
            st["finished_at"] = time.time()
            save_state(st)
            log_line(job_id, f"job complete, audiobook copied to {book_dir}")
        except _Cancelled:
            st["status"] = "canceled"
            save_state(st)
            log_line(job_id, "job canceled")
        except Exception as e:
            st["status"] = "failed"
            st["error"] = str(e)
            save_state(st)
            log_line(job_id, f"FAILED: {e}")


def _narration_progress(job_dir, st):
    """Aggregate progress across all parallel workers by counting finished
    segments. Works regardless of worker count and survives resumes."""
    seg_dir = job_dir / "segments"
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
    if total and done < total and elapsed > 0 and this_run > 0:
        eta = (total - done) * (elapsed / this_run)
    if total and done >= total:
        message = "assembling"
    elif done == 0:
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
    if st.get("status") == "narrating":
        st["narrate_progress"] = _narration_progress(job_dir, st)
    log_path = job_dir / "log.txt"
    if log_path.exists():
        st["log_tail"] = _tail_text_lines(log_path, 30)
    out_dir = job_dir / "output"
    if out_dir.exists():
        st["outputs"] = sorted(
            [{"name": f.name, "bytes": f.stat().st_size}
             for f in out_dir.iterdir() if f.suffix.lower() in AUDIO_EXTS],
            key=lambda x: x["name"],
        )
    bl = job_dir / "blocks.json"
    if bl.exists() and "block_counts" not in st:
        blocks = json.loads(bl.read_text(encoding="utf-8"))["blocks"]
        counts = {}
        for b in blocks:
            counts[b["type"]] = counts.get(b["type"], 0) + 1
        st["block_counts"] = counts
    return st


def beta_test_report(job_id):
    """Build a compact summary for the downloadable beta-test bundle."""
    st = load_state(job_id)
    if not st:
        return None
    job_dir = JOBS_DIR / job_id
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
        "Audiobook Studio beta test report",
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

    def do_GET(self):
        path = urlparse(self.path).path
        try:
            if path == "/" or path == "/index.html":
                self._serve_file(STATIC_DIR / "index.html", "text/html; charset=utf-8")
            elif path == "/api/library":
                _json_response(self, {"items": scan_library()})
            elif path == "/api/voices":
                _json_response(self, {"voices": list_voices()})
            elif path == "/api/ffmpeg":
                _json_response(self, ffmpeg_status())
            elif path == "/api/jobs":
                _json_response(self, {"jobs": list_jobs()})
            elif re.fullmatch(r"/api/jobs/[0-9a-f-]+", path):
                st = job_detail(path.rsplit("/", 1)[1])
                _json_response(self, st if st else {"error": "not found"}, 200 if st else 404)
            elif re.fullmatch(r"/api/jobs/[0-9a-f-]+/blocks", path):
                job_id = path.split("/")[3]
                bl = JOBS_DIR / job_id / "blocks.json"
                if bl.exists():
                    self._serve_file(bl, "application/json; charset=utf-8")
                else:
                    _json_response(self, {"error": "no blocks yet"}, 404)
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
                if target.parent != out_dir or target.suffix.lower() not in AUDIO_EXTS:
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
                # Preflight the voice before creating anything, so a fresh install
                # fails here with a clear message instead of hours into the job.
                verr = missing_voice_error(body.get("voice") or DEFAULT_VOICE)
                if verr:
                    _json_response(self, {"error": verr}, 400)
                    return
                # Same preflight for ffmpeg: refuse an m4b/mp3 job now rather
                # than failing the encode after the narration has finished.
                req_fmt = body.get("format") if body.get("format") in ("m4b", "mp3", "wav") else "m4b"
                ferr = missing_ffmpeg_error(req_fmt)
                if ferr:
                    _json_response(self, {"error": ferr, "ffmpeg_missing": True}, 400)
                    return
                job_id = str(uuid.uuid4())
                job_dir = JOBS_DIR / job_id
                job_dir.mkdir()
                n = page_count(body["pdf_path"]) or 1
                st = {
                    "id": job_id,
                    "title": body.get("title") or Path(body["pdf_path"]).stem,
                    "pdf_path": body["pdf_path"],
                    "path": body.get("path", "B"),
                    "page_from": max(1, int(body.get("page_from", 1))),
                    "page_to": min(n, int(body.get("page_to", n))),
                    "voice": body.get("voice") or DEFAULT_VOICE,
                    "format": body.get("format") if body.get("format") in ("m4b", "mp3", "wav") else "m4b",
                    "engine": body.get("engine") if body.get("engine") in ("parallel", "batched") else DEFAULT_ENGINE,
                    "status": "queued",
                    "created_at": time.time(),
                }
                save_state(st)
                log_line(job_id, f"created: {st['title']} path {st['path']} pages {st['page_from']}..{st['page_to']}")
                enqueue(job_id)
                _json_response(self, st)
            elif re.fullmatch(r"/api/jobs/[0-9a-f-]+/cancel", path):
                job_id = path.split("/")[3]
                request_cancel(job_id)
                _json_response(self, {"ok": True})
            elif re.fullmatch(r"/api/jobs/[0-9a-f-]+/resume", path):
                job_id = path.split("/")[3]
                st = load_state(job_id)
                if st and st["status"] in ("failed", "canceled", "interrupted"):
                    st["status"] = "queued"
                    st.pop("error", None)
                    _cancel_flags.pop(job_id, None)  # no stale cancel survives into the retry
                    save_state(st)
                    enqueue(job_id)
                    _json_response(self, {"ok": True})
                else:
                    _json_response(self, {"error": "job not resumable"}, 400)
            elif re.fullmatch(r"/api/jobs/[0-9a-f-]+/delete", path):
                job_id = path.split("/")[3]
                st = load_state(job_id)
                if st and st["status"] in ("done", "failed", "canceled", "interrupted", "queued"):
                    shutil.rmtree(JOBS_DIR / job_id, ignore_errors=True)
                    _json_response(self, {"ok": True})
                else:
                    _json_response(self, {"error": "stop the job first"}, 400)
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
        safe_name = re.sub(r'[^A-Za-z0-9 .()_\-]', '_', filename).strip() or "download.txt"
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
    for st in list_jobs():
        if st["status"] in ("extracting", "tagging", "narrating", "queued"):
            # Kill any workers this job's previous server orphaned before we
            # let it resume, so they cannot contend for the GPU or collide on
            # segment temp files with a fresh worker set.
            _reap_worker_pids(JOBS_DIR / st["id"])
            st["status"] = "interrupted"
            save_state(st)


def main():
    for line in CFG.warnings():
        print(f"[config] WARNING: {line}")
    mark_interrupted_jobs()
    threading.Thread(target=worker_loop, daemon=True).start()
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print(f"Audiobook Studio running at http://localhost:{PORT}")
    print(f"  chatterbox python: {CHATTERBOX_PY}")
    print(f"  audiobooks dir:    {AUDIOBOOKS_DIR}")
    print(f"  library roots:     {', '.join(str(r) for r in LIBRARY_ROOTS) or '(none)'}")
    server.serve_forever()


if __name__ == "__main__":
    main()
