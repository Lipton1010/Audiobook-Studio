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
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

# Miniconda3 latest Windows 64-bit installer. Anaconda publishes a stable
# "latest" alias at this URL; pin a dated build here if that ever proves to
# drift under us (checked 2026-07-26).
MINICONDA_URL = "https://repo.anaconda.com/miniconda/Miniconda3-latest-Windows-x86_64.exe"
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


def install_miniconda(install_dir=DEFAULT_INSTALL_DIR):
    # gettempdir() honours TEMP/TMP; the previous hand-built
    # ~\AppData\Local\Temp path broke on any machine that redirects them.
    tmp = Path(tempfile.gettempdir()) / "miniconda_installer.exe"
    tmp.parent.mkdir(parents=True, exist_ok=True)
    download(MINICONDA_URL, tmp)

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
