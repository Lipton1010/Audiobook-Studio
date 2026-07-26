"""
Audiobook Studio setup / installer. Run from the repo root:

    setup.bat            (Windows, double-click or from a terminal)
    python setup.py      (if you already have a base Python)

Runs in a plain Python (stdlib only) and drives conda to build the two
environments the app needs, pinned to the versions this project is known to
work with. Idempotent: re-running checks what exists and only does what's
missing. It never touches Ollama (a hard project rule) and never upgrades an
existing chatterbox env without asking.

What it sets up:
  * base env  (the web server): PyMuPDF + requests, into the conda base env
  * chatterbox env (the narrator): Python 3.11 + torch 2.6.0+cu124 +
    chatterbox-tts 0.1.7 + transformers 5.2.0, from install/requirements-chatterbox.txt

Prerequisites it checks and reports on:
  * Miniconda/Anaconda        - required. Auto-installed silently with
                                --auto-install-conda (install/bootstrap_conda.py);
                                otherwise only reported.
  * an NVIDIA GPU (nvidia-smi) - required for narration; text extraction works
                                without it. Never auto-installed (a driver, not
                                a package this tool can safely touch).
  * ffmpeg                    - required for m4b/mp3 output; WAV works without
                                it. Auto-fetched as a static build with
                                --auto-install-ffmpeg (install/bootstrap_ffmpeg.py);
                                otherwise only reported.
  * Ollama                    - OPTIONAL, only for scanned-image books (Path B).
                                Never touched by this installer (hard project rule).

--prefetch-weights downloads Chatterbox's ~3 GB of TTS weights right after the
chatterbox env is built, via install/bootstrap_weights.py. This is a plain
HTTP download (huggingface_hub), no CUDA/inference involved, so a failure here
is isolated from whether the GPU/torch stack itself works. Point of this flag:
without it, the ~3 GB download happens silently on first narration instead,
which is the single most common thing that makes a fresh install look broken.
"""
import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent
INSTALL = REPO / "install"
CHATTERBOX_ENV = "chatterbox"
PY_VERSION = "3.11"
CU_INDEX = "https://download.pytorch.org/whl/cu124"
# numpy is pinned alongside torch on purpose: torch does not pin it, so step 1
# would pull numpy 2.x and step 2 would immediately downgrade it. chatterbox-tts
# requires numpy<2.0.0, so a failure between the two steps would otherwise leave
# the env with a numpy the narrator cannot use. The cu124 index carries 1.26.4.
TORCH_PINS = ["torch==2.6.0+cu124", "torchaudio==2.6.0+cu124", "torchvision==0.21.0+cu124",
              "numpy==1.26.4"]


# ---------- pretty output ----------

def hr(): print("=" * 64)
def ok(msg): print(f"  [ OK ] {msg}")
def warn(msg): print(f"  [WARN] {msg}")
def err(msg): print(f"  [FAIL] {msg}")
def step(msg): print(f"\n>>> {msg}")


def run(cmd, **kw):
    print(f"    $ {' '.join(cmd)}")
    return subprocess.run(cmd, **kw)


# ---------- prerequisite discovery ----------

def find_conda():
    """Return a path to the conda executable, or None."""
    exe = shutil.which("conda")
    if exe:
        return exe
    home = Path(os.path.expanduser("~"))
    for root in (home / "miniconda3", home / "anaconda3", home / "miniforge3",
                 Path("C:/ProgramData/miniconda3"), Path("C:/ProgramData/anaconda3")):
        for sub in ("Scripts/conda.exe", "condabin/conda.bat", "bin/conda"):
            p = root / sub
            if p.exists():
                return str(p)
    return None


def env_exists(conda, name):
    r = run([conda, "env", "list"], capture_output=True, text=True)
    for line in (r.stdout or "").splitlines():
        parts = line.split()
        if parts and parts[0] == name:
            return True
    return False


# ---------- auto-install (opt-in) ----------

def auto_install_conda():
    step("Miniconda not found; installing silently")
    r = run([sys.executable, str(INSTALL / "bootstrap_conda.py")])
    return r.returncode == 0


def auto_install_ffmpeg():
    step("ffmpeg not found; fetching a static build")
    r = run([sys.executable, str(INSTALL / "bootstrap_ffmpeg.py")])
    return r.returncode == 0


def prefetch_weights(conda):
    step("Pre-fetching Chatterbox weights (~3 GB, one-time)")
    r = run([conda, "run", "-n", CHATTERBOX_ENV, "python", str(INSTALL / "bootstrap_weights.py")])
    if r.returncode == 0:
        ok("weights cached")
    else:
        warn("weights pre-fetch failed; first narration will download them instead (see errors above)")
    return r.returncode == 0


# ---------- checks ----------

def check_prereqs(auto_conda=False):
    step("Checking prerequisites")
    problems = []
    conda = find_conda()
    if conda:
        ok(f"conda found: {conda}")
    elif auto_conda:
        if auto_install_conda():
            conda = find_conda()
            if conda:
                ok(f"conda installed: {conda}")
            else:
                err("Miniconda installer reported success but conda still can't be found. "
                    "Close and reopen this terminal (PATH may need a refresh) and re-run.")
                problems.append("conda")
        else:
            err("Automatic Miniconda install failed; see output above.")
            problems.append("conda")
    else:
        err("conda not found. Install Miniconda from https://docs.conda.io/en/latest/miniconda.html, "
            "reopen your terminal, and re-run this (or re-run with --auto-install-conda).")
        problems.append("conda")

    if shutil.which("nvidia-smi"):
        try:
            r = subprocess.run(["nvidia-smi", "--query-gpu=name,memory.total",
                                "--format=csv,noheader"], capture_output=True, text=True, timeout=15)
            ok(f"NVIDIA GPU: {r.stdout.strip().splitlines()[0]}")
        except Exception:
            ok("NVIDIA GPU present")
    else:
        warn("No NVIDIA GPU detected (nvidia-smi missing). Narration REQUIRES an NVIDIA GPU "
             "with ~6 GB+ VRAM. You can extract text but not generate audio.")

    bundled_ffmpeg = REPO / "tools" / "ffmpeg.exe"
    if shutil.which("ffmpeg"):
        ok("ffmpeg on PATH")
    elif bundled_ffmpeg.exists():
        ok(f"ffmpeg found ({bundled_ffmpeg})")
    elif Path(r"C:\ProgramData\chocolatey\bin\ffmpeg.exe").exists():
        ok("ffmpeg found (chocolatey)")
    else:
        warn("ffmpeg not found. Needed for .m4b/.mp3 output (WAV works without it). "
             "Install from https://www.gyan.dev/ffmpeg/builds/ or 'choco install ffmpeg' "
             "(or re-run with --auto-install-ffmpeg), then reopen the terminal.")

    if shutil.which("ollama"):
        ok("Ollama present (optional, for scanned-image books). NOTE: this installer never changes it.")
    else:
        print("  [ -- ] Ollama not found (optional; only needed for scanned-image PDFs / Path B).")

    return conda, problems


# ---------- env building ----------

def setup_base_env(conda):
    step("Base env (web server): PyMuPDF + requests")
    req = INSTALL / "requirements-base.txt"
    r = run([conda, "run", "-n", "base", "python", "-m", "pip", "install", "-r", str(req)])
    if r.returncode == 0:
        ok("base env dependencies installed")
    else:
        err("base env pip install failed (see output above)")
    return r.returncode == 0


def setup_chatterbox_env(conda, assume_yes=False):
    step("Chatterbox env (narrator): Python 3.11 + torch cu124 + chatterbox-tts")
    exists = env_exists(conda, CHATTERBOX_ENV)
    if exists:
        warn(f"conda env '{CHATTERBOX_ENV}' already exists.")
        if not assume_yes:
            ans = input("    Reinstall/repair its packages? Existing env is left in place either way [y/N]: ").strip().lower()
            if ans != "y":
                print("    Skipping chatterbox env package install.")
                return True
    else:
        r = run([conda, "create", "-n", CHATTERBOX_ENV, f"python={PY_VERSION}", "-y"])
        if r.returncode != 0:
            err("conda create failed")
            return False
        ok(f"created env '{CHATTERBOX_ENV}' (python {PY_VERSION})")

    pip = [conda, "run", "-n", CHATTERBOX_ENV, "python", "-m", "pip", "install"]
    # 1) CUDA torch first, from the pytorch cu124 index, so nothing pulls CPU torch.
    r = run(pip + ["--index-url", CU_INDEX] + TORCH_PINS)
    if r.returncode != 0:
        err("torch (cu124) install failed. Check your internet and that the GPU/driver supports CUDA 12.4.")
        return False
    ok("torch 2.6.0+cu124 installed")
    # 2) Everything else, pinned; --extra-index-url keeps the +cu124 wheels resolvable.
    req = INSTALL / "requirements-chatterbox.txt"
    r = run(pip + ["-r", str(req), "--extra-index-url", CU_INDEX])
    if r.returncode != 0:
        err("chatterbox requirements install failed (see output above)")
        return False
    ok("chatterbox env dependencies installed")
    return True


# ---------- verification ----------

def verify(conda):
    step("Verifying the install")
    good = True
    r = run([conda, "run", "-n", "base", "python", "-c",
             "import fitz, requests; print('base ok', fitz.__doc__ is not None)"],
            capture_output=True, text=True)
    if r.returncode == 0:
        ok("base env imports (fitz + requests)")
    else:
        err(f"base env import failed: {(r.stderr or '').strip()[:200]}")
        good = False

    # Import exactly what the narrator imports at runtime, not just the top-level
    # packages: a shallower check passes envs that die later on soundfile, the
    # perth watermarker stub, or the transformers 5.2 API the batched engine uses.
    r = run([conda, "run", "-n", CHATTERBOX_ENV, "python", "-c", "import torch, transformers, numpy, soundfile, perth;import chatterbox.tts as T;T.ChatterboxTTS; T.punc_norm;from chatterbox.models.s3tokenizer import drop_invalid_tokens;from transformers.generation.logits_process import RepetitionPenaltyLogitsProcessor, MinPLogitsWarper, TopPLogitsWarper;DC = getattr(transformers, 'DynamicCache', None) or __import__('transformers.cache_utils', fromlist=['DynamicCache']).DynamicCache;print('torch', torch.__version__, 'cuda', torch.cuda.is_available(), 'transformers', transformers.__version__, 'numpy', numpy.__version__, 'sndfile', soundfile.__libsndfile_version__, 'cache', DC.__name__)"],
            capture_output=True, text=True)
    out = (r.stdout or "").strip()
    if r.returncode == 0:
        ok(f"chatterbox env imports: {out}")
        if "cuda True" not in out:
            warn("torch.cuda.is_available() is False - the GPU/driver isn't visible to torch. "
                 "Narration will fail until the NVIDIA driver + CUDA runtime are working.")
        if "transformers 5.2.0" not in out:
            warn("transformers is not 5.2.0 - the batched engine was verified on 5.2.0; "
                 "pin it with: pip install transformers==5.2.0")
        if " numpy 2." in out:
            warn("numpy is 2.x but chatterbox-tts requires <2.0.0; "
                 "fix with: pip install numpy==1.26.4")
    else:
        err(f"chatterbox env import failed: {(r.stderr or '').strip()[:200]}")
        good = False
    return good


def main():
    ap = argparse.ArgumentParser(description="Audiobook Studio setup")
    ap.add_argument("--yes", action="store_true", help="non-interactive; assume yes")
    ap.add_argument("--check-only", action="store_true", help="only check prerequisites, install nothing")
    ap.add_argument("--auto-install-conda", action="store_true",
                     help="silently install Miniconda if not found (current user only, no admin)")
    ap.add_argument("--auto-install-ffmpeg", action="store_true",
                     help="fetch a static ffmpeg build into tools/ if not found")
    ap.add_argument("--prefetch-weights", action="store_true",
                     help="download Chatterbox's ~3 GB of TTS weights now instead of on first narration")
    args = ap.parse_args()

    hr()
    print("  Audiobook Studio - setup")
    hr()
    conda, problems = check_prereqs(auto_conda=args.auto_install_conda)
    if "conda" in problems:
        print("\nInstall the missing prerequisites above, then re-run.")
        sys.exit(1)

    if args.auto_install_ffmpeg:
        auto_install_ffmpeg()

    if args.check_only:
        print("\nCheck-only mode: nothing installed.")
        return

    base_ok = setup_base_env(conda)
    cb_ok = setup_chatterbox_env(conda, assume_yes=args.yes)
    weights_ok = True
    if args.prefetch_weights and cb_ok:
        weights_ok = prefetch_weights(conda)
    all_ok = verify(conda) and base_ok and cb_ok and weights_ok

    hr()
    if all_ok:
        print("  Setup complete. Launch the app with:  Start_Audiobook_Studio.bat")
        print("  It opens in its own window (falls back to your browser if that fails).")
    else:
        print("  Setup finished with problems (see [FAIL]/[WARN] above).")
        print("  Fix those and re-run  python setup.py  (it is safe to re-run).")
    hr()
    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
