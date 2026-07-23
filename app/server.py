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
import json
import os
import re
import shutil
import subprocess
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

import fitz  # PyMuPDF
import requests

import pipeline_text as pt

APP_DIR = Path(__file__).parent
JOBS_DIR = APP_DIR / "jobs"
STATIC_DIR = APP_DIR / "static"
LIBRARY_ROOTS = [
    Path(r"D:\Audiobook_Pipeline\samples"),
    Path(r"D:\Audiobook_Pipeline\source_pdfs"),
]
# Converted from "Voice Sample Male.mp3" via convert_voice.py; the old
# ref_15s.wav default was judged bad on listening (2026-07-21).
REFERENCE_WAV = r"D:\Audiobook_Pipeline\samples\Voice_Sample\male_ref.wav"
DEFAULT_VOICE = "Default narrator (male sample)"
VOICES_DIR = APP_DIR / "voices"
AUDIOBOOKS_DIR = Path(r"D:\Audiobook_Pipeline\audiobooks")
CHATTERBOX_PY = r"C:\Users\paulm\miniconda3\envs\chatterbox\python.exe"
OLLAMA_URL = "http://localhost:11434/api/generate"
OCR_MODEL = "glm-ocr-doc"
OCR_PROMPT = "Transcribe this document page as clean Markdown, preserving reading order and tables."
PORT = 8765

AUDIO_EXTS = {".m4b", ".mp3", ".wav"}
AUDIO_MIME = {".m4b": "audio/mp4", ".mp3": "audio/mpeg", ".wav": "audio/wav"}

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

JOBS_DIR.mkdir(exist_ok=True)
VOICES_DIR.mkdir(exist_ok=True)


# ---------- voices ----------

def list_voices():
    voices = [{"name": DEFAULT_VOICE, "builtin": True}]
    for f in sorted(VOICES_DIR.glob("*.wav")):
        voices.append({"name": f.stem, "builtin": False})
    return voices


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
        )
        if r.returncode != 0:
            msg = (r.stdout + r.stderr).strip()
            raise RuntimeError(msg.splitlines()[-1] if msg else "conversion failed")
        return safe
    finally:
        tmp_in.unlink(missing_ok=True)

_jobs_lock = threading.Lock()
_page_count_cache = {}


# ---------- job state helpers ----------

def _state_path(job_id):
    return JOBS_DIR / job_id / "state.json"


def load_state(job_id):
    p = _state_path(job_id)
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


def save_state(state):
    p = _state_path(state["id"])
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2), encoding="utf-8")
    tmp.replace(p)


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


def scan_library():
    seen = set()
    items = []
    for root in LIBRARY_ROOTS:
        if not root.exists():
            continue
        for p in sorted(root.rglob("*.pdf")):
            key = str(p).lower()
            if key in seen:
                continue
            seen.add(key)
            n = page_count(p)
            items.append(
                {
                    "path": str(p),
                    "name": p.stem,
                    "folder": str(p.parent),
                    "pages": n,
                    "suggested_path": suggest_path(p, n) if n else "B",
                }
            )
    return items


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
                           capture_output=True, timeout=10)
        except Exception:
            pass
    pf.unlink(missing_ok=True)


def _spawn_worker(job_dir, logf, extra_args):
    return subprocess.Popen(
        [CHATTERBOX_PY, str(APP_DIR / "narrate_worker.py"), str(job_dir), *extra_args],
        stdout=logf, stderr=subprocess.STDOUT, cwd=str(APP_DIR),
    )


def run_narration(st):
    job_id = st["id"]
    job_dir = JOBS_DIR / job_id
    config = {
        "path": st["path"],
        "reference_wav": voice_wav_path(st.get("voice")),
        "title": st["title"],
        "format": st.get("format", "m4b"),
        "fallback_part_minutes": 240,
    }
    (job_dir / "config.json").write_text(json.dumps(config, indent=2), encoding="utf-8")
    ensure_segments_fresh(job_dir, st)

    n = narration_worker_count()
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


def job_detail(job_id):
    st = load_state(job_id)
    if not st:
        return None
    job_dir = JOBS_DIR / job_id
    if st.get("status") == "narrating":
        st["narrate_progress"] = _narration_progress(job_dir, st)
    log_path = job_dir / "log.txt"
    if log_path.exists():
        lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
        st["log_tail"] = lines[-30:]
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
            if path == "/api/voices":
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
    mark_interrupted_jobs()
    threading.Thread(target=worker_loop, daemon=True).start()
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print(f"Audiobook Studio running at http://localhost:{PORT}")
    server.serve_forever()


if __name__ == "__main__":
    main()
