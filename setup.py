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

Prerequisites it checks and reports on (does NOT auto-install these):
  * Miniconda/Anaconda        - required
  * an NVIDIA GPU (nvidia-smi) - required for narration; text extraction works without it
  * ffmpeg on PATH            - required for m4b/mp3 output; WAV works without it
  * Ollama                    - OPTIONAL, only for scanned-image books (Path B)
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
TORCH_PINS = ["torch==2.6.0+cu124", "torchaudio==2.6.0+cu124", "torchvision==0.21.0+cu124"]


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


def env_python(conda, name):
    """Best-effort path to an env's python.exe."""
    home = Path(os.path.expanduser("~"))
    for root in (home / "miniconda3", home / "anaconda3", home / "miniforge3",
                 Path("C:/ProgramData/miniconda3")):
        p = root / "envs" / name / "python.exe"
        if p.exists():
            return str(p)
    return None


# ---------- checks ----------

def check_prereqs():
    step("Checking prerequisites")
    problems = []
    conda = find_conda()
    if conda:
        ok(f"conda found: {conda}")
    else:
        err("conda not found. Install Miniconda from https://docs.conda.io/en/latest/miniconda.html, "
            "reopen your terminal, and re-run this.")
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

    if shutil.which("ffmpeg"):
        ok("ffmpeg on PATH")
    elif Path(r"C:\ProgramData\chocolatey\bin\ffmpeg.exe").exists():
        ok("ffmpeg found (chocolatey)")
    else:
        warn("ffmpeg not found. Needed for .m4b/.mp3 output (WAV works without it). "
             "Install from https://www.gyan.dev/ffmpeg/builds/ or 'choco install ffmpeg', then reopen the terminal.")

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

    r = run([conda, "run", "-n", CHATTERBOX_ENV, "python", "-c",
             "import torch, transformers, chatterbox; "
             "print('torch', torch.__version__, 'cuda', torch.cuda.is_available(), "
             "'transformers', transformers.__version__)"],
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
    else:
        err(f"chatterbox env import failed: {(r.stderr or '').strip()[:200]}")
        good = False
    return good


def main():
    ap = argparse.ArgumentParser(description="Audiobook Studio setup")
    ap.add_argument("--yes", action="store_true", help="non-interactive; assume yes")
    ap.add_argument("--check-only", action="store_true", help="only check prerequisites, install nothing")
    args = ap.parse_args()

    hr()
    print("  Audiobook Studio - setup")
    hr()
    conda, problems = check_prereqs()
    if "conda" in problems:
        print("\nInstall the missing prerequisites above, then re-run.")
        sys.exit(1)
    if args.check_only:
        print("\nCheck-only mode: nothing installed.")
        return

    base_ok = setup_base_env(conda)
    cb_ok = setup_chatterbox_env(conda, assume_yes=args.yes)
    all_ok = verify(conda) and base_ok and cb_ok

    hr()
    if all_ok:
        print("  Setup complete. Launch the app with:  Start_Audiobook_Studio.bat")
        print("  Then open http://localhost:8765")
    else:
        print("  Setup finished with problems (see [FAIL]/[WARN] above).")
        print("  Fix those and re-run  python setup.py  (it is safe to re-run).")
    hr()
    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
