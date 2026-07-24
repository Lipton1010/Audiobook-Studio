"""
Portable configuration for Audiobook Studio.

Runs in the BASE miniconda env alongside server.py, so this module is
stdlib only (no torch, no third-party imports). It resolves every
machine-specific value (conda env python, folders, Ollama, port) in a
fixed precedence so the app runs on someone else's Windows box without
editing source:

    environment variable  >  config.json  >  auto-detection  >  built-in default

The built-in defaults reproduce the author's original hardcoded values
(relative to the repo root where possible), so nothing changes on the
machine this was written on. A friend copies config.example.json to
config.json and edits only what auto-detection cannot find.

config.json is gitignored; only config.example.json is committed.
"""

import json
import os
import shutil
import sys
from pathlib import Path


def _warn(msg):
    # Import-time warnings go to stderr so callers that capture stdout for a
    # single value (the launcher reads CFG.port via stdout) stay uncontaminated.
    print(f"[config] WARNING: {msg}", file=sys.stderr)


APP_DIR = Path(__file__).resolve().parent
# Repo root (D:\Audiobook_Pipeline on the author's machine). Everything
# that used to be an absolute D:\Audiobook_Pipeline\... path defaults to a
# location under here, so a clone anywhere just works.
DEFAULT_BASE_DIR = APP_DIR.parent

CONFIG_PATH = APP_DIR / "config.json"

# env var name -> config.json key. Env always wins so a launcher or an
# A/B test harness can override without touching the file.
_ENV = {
    "base_dir": "AUDIOBOOK_BASE_DIR",
    "chatterbox_python": "AUDIOBOOK_CHATTERBOX_PY",
    "reference_wav": "AUDIOBOOK_REFERENCE_WAV",
    "audiobooks_dir": "AUDIOBOOK_AUDIOBOOKS_DIR",
    "library_roots": "AUDIOBOOK_LIBRARY_ROOTS",  # os.pathsep-separated in env
    "ollama_url": "AUDIOBOOK_OLLAMA_URL",
    "ocr_model": "AUDIOBOOK_OCR_MODEL",
    "ocr_prompt": "AUDIOBOOK_OCR_PROMPT",
    "port": "AUDIOBOOK_PORT",
}


def _load_file():
    if CONFIG_PATH.exists():
        try:
            return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except Exception as e:
            _warn(f"could not parse {CONFIG_PATH.name}: {e}; using defaults")
    return {}


def _pick(key, file_cfg, default):
    """env > config.json > default (auto-detection is folded into default)."""
    env_name = _ENV.get(key)
    if env_name and os.environ.get(env_name):
        return os.environ[env_name]
    if key in file_cfg and file_cfg[key] not in (None, ""):
        return file_cfg[key]
    return default


# ---------- auto-detection ----------

def _find_chatterbox_python(base_dir):
    """Locate the chatterbox conda env's python.exe.

    Order: an explicit env/config value is handled by the caller; here we
    search the conda roots a Windows install is likely to use. Returns the
    first match, or the author's original path as a last resort so behavior
    is unchanged when detection cannot see the file (e.g. env not created
    yet at import time)."""
    candidates = []
    # If we are launched from inside a conda base, its sibling envs/ dir.
    for var in ("CONDA_PREFIX_1", "CONDA_PREFIX"):
        root = os.environ.get(var)
        if root:
            candidates.append(Path(root))
    home = Path(os.path.expanduser("~"))
    for name in ("miniconda3", "anaconda3", "miniforge3", "mambaforge"):
        candidates.append(home / name)
        candidates.append(Path("C:/") / name)
        candidates.append(Path("C:/ProgramData") / name)
    seen = set()
    for root in candidates:
        try:
            root = root.resolve()
        except Exception:
            continue
        if root in seen:
            continue
        seen.add(root)
        # A CONDA_PREFIX may itself be the chatterbox env or the base; check
        # both "<root>/envs/chatterbox" and treat root as a conda base.
        py = root / "envs" / "chatterbox" / "python.exe"
        if py.exists():
            return str(py)
    # Last resort: original author path (unchanged behavior on that machine).
    return r"C:\Users\paulm\miniconda3\envs\chatterbox\python.exe"


def _as_path_list(value):
    if isinstance(value, (list, tuple)):
        return [str(v) for v in value if str(v).strip()]
    if isinstance(value, str):
        return [p for p in value.split(os.pathsep) if p.strip()]
    return []


# ---------- public config ----------

class Config:
    def __init__(self):
        file_cfg = _load_file()

        base = _pick("base_dir", file_cfg, str(DEFAULT_BASE_DIR))
        self.base_dir = Path(base).resolve()

        self.chatterbox_python = _pick(
            "chatterbox_python", file_cfg, _find_chatterbox_python(self.base_dir)
        )

        self.reference_wav = _pick(
            "reference_wav", file_cfg,
            str(self.base_dir / "samples" / "Voice_Sample" / "male_ref.wav"),
        )
        self.audiobooks_dir = Path(
            _pick("audiobooks_dir", file_cfg, str(self.base_dir / "audiobooks"))
        )

        default_roots = [
            str(self.base_dir / "samples"),
            str(self.base_dir / "source_pdfs"),
        ]
        roots_val = _pick("library_roots", file_cfg, default_roots)
        self.library_roots = [Path(p) for p in _as_path_list(roots_val)]

        self.ollama_url = _pick("ollama_url", file_cfg, "http://localhost:11434/api/generate")
        self.ocr_model = _pick("ocr_model", file_cfg, "glm-ocr-doc")
        self.ocr_prompt = _pick(
            "ocr_prompt", file_cfg,
            "Transcribe this document page as clean Markdown, preserving reading order and tables.",
        )
        raw_port = _pick("port", file_cfg, 8765)
        try:
            self.port = int(raw_port)
        except (TypeError, ValueError):
            _warn(f"invalid port {raw_port!r}; using 8765")
            self.port = 8765

    def warnings(self):
        """Human-readable list of things that look wrong, surfaced at startup
        so a tester on a fresh machine gets told what to fix instead of a
        stack trace deep in a job."""
        out = []
        if not Path(self.chatterbox_python).exists():
            out.append(
                f"chatterbox python not found at {self.chatterbox_python}. "
                f"Set chatterbox_python in config.json or AUDIOBOOK_CHATTERBOX_PY."
            )
        if not Path(self.reference_wav).exists():
            out.append(
                f"default voice sample not found at {self.reference_wav}. "
                f"Upload a voice in the UI, or set reference_wav in config.json."
            )
        if shutil.which("ffmpeg") is None and not Path(
            r"C:\ProgramData\chocolatey\bin\ffmpeg.exe"
        ).exists():
            out.append(
                "ffmpeg not found on PATH; m4b/mp3 output will fail (wav still works). "
                "Install ffmpeg and reopen the launcher."
            )
        existing_roots = [r for r in self.library_roots if r.exists()]
        if not existing_roots:
            out.append(
                "no library folders exist yet; drop PDFs into "
                + " or ".join(str(r) for r in self.library_roots)
                + " (or set library_roots in config.json)."
            )
        return out

    def summary(self):
        return {
            "base_dir": str(self.base_dir),
            "chatterbox_python": self.chatterbox_python,
            "reference_wav": self.reference_wav,
            "audiobooks_dir": str(self.audiobooks_dir),
            "library_roots": [str(r) for r in self.library_roots],
            "ollama_url": self.ollama_url,
            "ocr_model": self.ocr_model,
            "port": self.port,
        }


# Import-time singleton; server.py reads these module attributes.
CFG = Config()
