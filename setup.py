"""
Audiobook Studio setup / installer. Run from the repo root:

    setup.bat            (Windows, double-click or from a terminal)
    python setup.py      (if you already have a base Python)

Runs in a plain Python (stdlib only) and drives conda to build the two
environments the app needs, pinned to the versions this project is known to
work with. Idempotent: re-running checks what exists and only does what's
missing. It never touches Ollama (optional, Path B only, and shared with other
projects on the author's machine, so it is not this installer's to manage; the
old do-not-upgrade rule is retired, see CLAUDE.md) and never upgrades an
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
import json
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

# Warnings a non-technical user actually needs to see. When the one-click
# installer runs this, stdout goes to install_log.txt with no visible console,
# so anything only printed here is invisible in practice. These get written to
# install_warnings.txt, which AudiobookStudio.iss shows in a message box.
# Ordinary warn() stays log-only (env already exists, version drift, etc).
USER_WARNINGS = []
WARNINGS_FILE = REPO / "install_warnings.txt"


def hr(): print("=" * 64)
def ok(msg): print(f"  [ OK ] {msg}")
def warn(msg): print(f"  [WARN] {msg}")
def err(msg): print(f"  [FAIL] {msg}")
def step(msg): print(f"\n>>> {msg}")


def user_warn(msg):
    print(f"  [WARN] {msg}")
    USER_WARNINGS.append(msg)


def write_warnings_file():
    """Always rewrite (or remove) the file so a clean re-run clears stale
    warnings from a previous attempt."""
    try:
        if USER_WARNINGS:
            WARNINGS_FILE.write_text(
                "\n".join(f"- {w}" for w in USER_WARNINGS), encoding="utf-8")
        else:
            WARNINGS_FILE.unlink(missing_ok=True)
    except Exception as e:
        warn(f"could not write {WARNINGS_FILE.name}: {e}")


def run(cmd, **kw):
    print(f"    $ {' '.join(cmd)}")
    return subprocess.run(cmd, **kw)


# ---------- prerequisite discovery ----------

def find_conda():
    """Return a path to the conda executable, or None."""
    # If we are already running under a conda base python (which is exactly
    # what the one-click installer does -- it hands us the python.exe it just
    # found or installed), use THAT install's conda. Otherwise a machine with
    # two condas can have the installer pick one and setup.py build the envs in
    # the other, leaving a launcher that finds neither. No-op everywhere else:
    # a system python has no sibling Scripts\conda.exe.
    sibling = Path(sys.executable).resolve().parent / "Scripts" / "conda.exe"
    if sibling.exists():
        return str(sibling)
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
        user_warn("The 3 GB voice model could not be downloaded now. This is not fatal: "
                  "the app will download it the first time you narrate a book, so that "
                  "first run will sit at 0% for several minutes before anything happens.")
    return r.returncode == 0


# ---------- checks ----------

def check_prereqs(auto_conda=False, auto_ffmpeg=False):
    step("Checking prerequisites")
    problems = []
    ffmpeg_ok = True
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
        user_warn("No NVIDIA GPU detected (nvidia-smi missing). Narration REQUIRES an "
                  "NVIDIA GPU with ~6 GB+ VRAM. You can extract text from PDFs but "
                  "the app will not be able to generate audio on this machine.")

    # Auto-install BEFORE reporting, so the user is not shown a scary "ffmpeg
    # not found" warning immediately followed by it being installed.
    def _find_ffmpeg():
        """Delegate to bootstrap_ffmpeg so there is exactly ONE definition of
        "ffmpeg is available", and so this EXECUTES the binary rather than
        testing that a file exists.

        The existence-only version had a hole: a failed fetch used to leave a
        broken ffmpeg.exe in tools\, which this function then reported as
        success, with no warning written. bootstrap_ffmpeg now stages the
        binary under a candidate name and only promotes it after it runs, and
        this check runs it again."""
        try:
            if str(INSTALL) not in sys.path:
                sys.path.insert(0, str(INSTALL))
            from bootstrap_ffmpeg import ffmpeg_already_available
        except Exception:
            return None
        found_path = ffmpeg_already_available()
        return f"ffmpeg found and runs ({found_path})" if found_path else None

    found = _find_ffmpeg()
    if not found and auto_ffmpeg:
        reported_ok = auto_install_ffmpeg()
        found = _find_ffmpeg()
        if reported_ok and not found:
            err("bootstrap_ffmpeg.py exited 0 but no runnable ffmpeg can be found. "
                "Treating ffmpeg as missing.")
    if found:
        ok(found)
    else:
        # Reported, and deliberately NOT fatal to the install. Two reasons, and
        # the second is the one that actually decides it:
        #   1. WAV output still works, so the install is reduced, not broken.
        #   2. Install time is the wrong layer to enforce this anyway. ffmpeg can
        #      be removed or moved AFTER setup runs, so a pass here would prove
        #      nothing later. The real guard is at job creation: the app now
        #      refuses to accept an m4b/mp3 job when ffmpeg is absent and offers
        #      a one-click install, the same shape as the missing-voice fix.
        # This warning still goes to install_warnings.txt and the installer's
        # message box, so a friend is told at the earliest useful moment.
        ffmpeg_ok = False
        user_warn("ffmpeg is not installed, so .m4b and .mp3 output are unavailable "
                  "for now. This is NOT fatal: the app will start, will offer WAV "
                  "output, and has an 'Install ffmpeg' button that fixes this in one "
                  "click. You can also run 'choco install ffmpeg' or download it from "
                  "https://www.gyan.dev/ffmpeg/builds/.")

    if shutil.which("ollama"):
        ok("Ollama present (optional, for scanned-image books). NOTE: this installer never changes it.")
    else:
        print("  [ -- ] Ollama not found (optional; only needed for scanned-image PDFs / Path B).")

    return conda, problems, ffmpeg_ok


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


# ---------- pinning the resolved interpreter ----------

def pin_chatterbox_python(conda):
    """Write the REAL chatterbox interpreter path into app/config.json.

    setup.py creates and verifies the env BY NAME ("-n chatterbox"), while
    app/config.py has to GUESS a path (<some conda root>\envs\chatterbox\
    python.exe) and falls back to the original author's path when it cannot
    find one. Those two can disagree: conda honours envs_dirs, so an env can be
    created somewhere this guess will never look. The result is the worst kind
    of failure, a setup that reports success followed by an app that cannot
    narrate.

    Asking the env itself for sys.executable removes the guess. config.json is
    gitignored and is read at a higher precedence than auto-detection, so this
    is exactly the hook it exists for."""
    step("Recording the chatterbox interpreter path")
    r = run([conda, "run", "-n", CHATTERBOX_ENV, "python", "-c",
             "import sys; print(sys.executable)"],
            capture_output=True, text=True)
    exe = (r.stdout or "").strip().splitlines()[-1].strip() if r.returncode == 0 and (r.stdout or "").strip() else ""
    if r.returncode != 0 or not exe or not Path(exe).exists():
        err("could not resolve the chatterbox env's python. The app may not find "
            "it either; set chatterbox_python in app/config.json by hand.")
        return False

    cfg_path = REPO / "app" / "config.json"
    try:
        data = json.loads(cfg_path.read_text(encoding="utf-8")) if cfg_path.exists() else {}
        if not isinstance(data, dict):
            data = {}
    except Exception:
        # A corrupt config.json should not take the install down, but do not
        # silently overwrite it either.
        warn(f"{cfg_path} is not valid JSON; leaving it alone. "
             f"Set chatterbox_python to {exe} by hand.")
        return False

    if data.get("chatterbox_python") == exe:
        ok(f"chatterbox python already recorded: {exe}")
        return True
    data["chatterbox_python"] = exe
    try:
        cfg_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = cfg_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        os.replace(tmp, cfg_path)
    except Exception as e:
        err(f"could not write {cfg_path}: {e}")
        return False
    ok(f"chatterbox python recorded in app/config.json: {exe}")
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
            user_warn("torch cannot see your GPU (torch.cuda.is_available() is False). "
                      "Narration will fail until the NVIDIA driver is installed/updated. "
                      "Text extraction still works.")
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
    conda, problems, ffmpeg_ok = check_prereqs(auto_conda=args.auto_install_conda,
                                               auto_ffmpeg=args.auto_install_ffmpeg)
    if "conda" in problems:
        write_warnings_file()
        print("\nInstall the missing prerequisites above, then re-run.")
        sys.exit(1)

    if args.check_only:
        write_warnings_file()
        print("\nCheck-only mode: nothing installed.")
        return

    base_ok = setup_base_env(conda)
    cb_ok = setup_chatterbox_env(conda, assume_yes=args.yes)
    if args.prefetch_weights and cb_ok:
        # Deliberately NOT part of all_ok: a failed pre-fetch means a slow first
        # narration, not a broken install, and prefetch_weights() already says
        # so. Counting it made the exit code contradict the message.
        prefetch_weights(conda)
    # ffmpeg_ok is reported but not gated on: a missing ffmpeg costs m4b/mp3
    # output, not the install. The exit code means "the Python environments are
    # broken", which is the only condition where launching is pointless.
    all_ok = verify(conda) and base_ok and cb_ok
    # Only meaningful once the env exists; a failure here is reported but does
    # not by itself mean the environments are broken, so it does not flip
    # all_ok. config.py's own detection still gets a chance.
    if cb_ok:
        pin_chatterbox_python(conda)

    write_warnings_file()
    hr()
    if all_ok:
        print("  Setup complete. Launch the app with:  Start_Audiobook_Studio.bat")
        print("  It opens in its own window (falls back to your browser if that fails).")
        if USER_WARNINGS:
            print("\n  Things to know about this machine:")
            for w in USER_WARNINGS:
                print(f"   - {w}")
    else:
        print("  Setup finished with problems (see [FAIL]/[WARN] above).")
        print("  Fix those and re-run  python setup.py  (it is safe to re-run).")
    hr()
    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
