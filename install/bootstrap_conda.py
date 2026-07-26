"""
Silent Miniconda bootstrap for machines that don't have conda yet.

Only runs the official Miniconda Windows installer with its documented
silent-install flags:

    /InstallationType=JustMe   (no admin required, current user only)
    /RegisterPython=0          (does not hijack the system 'python' command)
    /S                         (silent, no UI, no prompts)
    /D=<path>                  (install location; must be the LAST argument
                                and must not be quoted, per Miniconda's own
                                installer docs)

This does not create any conda environments and does not install ffmpeg or
any project dependency; it only gets a working `conda` executable onto the
machine so setup.py's existing logic (find_conda / setup_base_env /
setup_chatterbox_env) can take over exactly as it does today when a human
already has conda installed.

Safe to re-run: if conda is already found, this is a no-op.
"""
import argparse
import hashlib
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

# PINNED, not "latest", for two reasons.
#
# 1. Reproducibility. Miniconda3-latest-Windows-x86_64.exe is a moving alias:
#    on 2026-07-08 it became byte-identical to the py314 build (same SHA-256,
#    124.7 MB). So an unpinned install gives a friend whatever base Python
#    Anaconda shipped that week, while this machine keeps the 3.13 base that
#    everything was actually verified on. Pinning py313 makes their base env
#    match the one that works here. (Checked 2026-07-26: the base pins would
#    ALSO have survived 3.14, since pymupdf 1.28.0 ships a cp310-abi3 wheel and
#    pythonnet 3.1.0 ships real cp314 wheels. So this is about determinism, not
#    about dodging a live breakage.)
# 2. A pinned filename has a published SHA-256, so this 125 MB executable can be
#    verified before it is run. The "latest" alias changes hash by design and
#    cannot be checked at all.
#
# To bump: take the name and SHA-256 from the table at
# https://repo.anaconda.com/miniconda/ and update BOTH constants, and the
# matching pair in install/AudiobookStudio.iss.
MINICONDA_FILE = "Miniconda3-py313_26.5.3-1-Windows-x86_64.exe"
MINICONDA_URL = "https://repo.anaconda.com/miniconda/" + MINICONDA_FILE
MINICONDA_SHA256 = "c229a161e9fad48fd7d2c701da363e6a307b233eba379cd967bc26aa2cb3fa68"
DEFAULT_INSTALL_DIR = str(Path.home() / "miniconda3")


def find_conda():
    # Reuse the exact same discovery logic setup.py uses, so this script's
    # notion of "already installed" can never disagree with setup.py's.
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from setup import find_conda as _find
    return _find()


def download(url, dest):
    print(f"  Downloading {url}")
    print(f"    -> {dest}")

    def _progress(block_num, block_size, total_size):
        if total_size <= 0:
            return
        done = block_num * block_size
        pct = min(100, done * 100 // total_size)
        print(f"\r    {pct}% ({done // (1024*1024)} MB / {total_size // (1024*1024)} MB)", end="", flush=True)

    urllib.request.urlretrieve(url, dest, reporthook=_progress)
    print()


def verify_hash(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    actual = h.hexdigest().lower()
    if actual != MINICONDA_SHA256:
        print("  [FAIL] downloaded Miniconda installer does not match its published SHA-256.")
        print(f"         expected {MINICONDA_SHA256}")
        print(f"         got      {actual}")
        print("         Refusing to run it. If Anaconda has replaced this build, update")
        print("         MINICONDA_FILE and MINICONDA_SHA256 from https://repo.anaconda.com/miniconda/")
        return False
    return True


def install_miniconda(install_dir=DEFAULT_INSTALL_DIR):
    # gettempdir() honours TEMP/TMP; the previous hand-built
    # ~\AppData\Local\Temp path broke on any machine that redirects them.
    tmp = Path(tempfile.gettempdir()) / "miniconda_installer.exe"
    tmp.parent.mkdir(parents=True, exist_ok=True)
    download(MINICONDA_URL, tmp)

    # Verify before executing. This is a 125 MB executable fetched over the
    # network and then run silently; the check is not optional the way the
    # ffmpeg one is.
    if not verify_hash(tmp):
        tmp.unlink(missing_ok=True)
        return False
    print("  [ OK ] installer checksum matches Anaconda's published SHA-256")

    print(f"  Installing Miniconda to {install_dir} (silent, current user only)...")
    # /D must be unquoted and must be the final argument per Anaconda's own
    # NSIS-installer documentation; do not add anything after it.
    cmd = (
        f'"{tmp}" /InstallationType=JustMe /RegisterPython=0 /S /D={install_dir}'
    )
    r = subprocess.run(cmd, shell=True)
    tmp.unlink(missing_ok=True)
    if r.returncode != 0:
        print(f"  [FAIL] Miniconda installer exited with code {r.returncode}")
        return False
    print("  [ OK ] Miniconda installed")
    return True


def main():
    ap = argparse.ArgumentParser(description="Silently install Miniconda if not already present")
    ap.add_argument("--install-dir", default=DEFAULT_INSTALL_DIR)
    ap.add_argument("--force", action="store_true", help="install even if conda is already found")
    args = ap.parse_args()

    existing = None if args.force else find_conda()
    if existing:
        print(f"  [ OK ] conda already present: {existing}")
        return 0

    ok = install_miniconda(args.install_dir)
    if not ok:
        return 1

    # Sanity-check the freshly installed conda actually runs before handing
    # control back to the installer/setup.py, rather than assuming success
    # from the exit code alone.
    conda_exe = str(Path(args.install_dir) / "Scripts" / "conda.exe")
    r = subprocess.run([conda_exe, "--version"], capture_output=True, text=True)
    if r.returncode == 0:
        print(f"  [ OK ] {r.stdout.strip()}")
        return 0
    print("  [FAIL] conda.exe installed but did not run cleanly; check the path manually.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
