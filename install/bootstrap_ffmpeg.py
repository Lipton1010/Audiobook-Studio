"""
ffmpeg auto-fetch for machines that don't have it.

ffmpeg is not an "installed program" in the Windows sense (no installer, no
registry entries) -- it is a static executable. So instead of running an
installer, this downloads the gyan.dev "essentials" static build (a
widely-used, redistributable build of ffmpeg; LGPL/GPL depending on which
codecs are compiled in -- the essentials build's LICENSE file is copied
alongside the binary so that stays intact) and drops ffmpeg.exe into the
repo's own tools\ folder.

The app is pointed at this exact path (see config.py / server.py), so there
is no PATH editing and no admin rights required. If the user already has
ffmpeg on PATH or at the chocolatey path, this is a no-op.

Safe to re-run.
"""
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
TOOLS_DIR = REPO / "tools"
FFMPEG_EXE = TOOLS_DIR / "ffmpeg.exe"

# gyan.dev publishes a stable "release essentials" zip alias at this URL.
# It is a static Windows build with the LICENSE bundled inside the zip.
FFMPEG_URL = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"


def ffmpeg_already_available():
    if shutil.which("ffmpeg"):
        return shutil.which("ffmpeg")
    if FFMPEG_EXE.exists():
        return str(FFMPEG_EXE)
    choco_path = Path(r"C:\ProgramData\chocolatey\bin\ffmpeg.exe")
    if choco_path.exists():
        return str(choco_path)
    return None


def download(url, dest):
    print(f"  Downloading {url}")

    def _progress(block_num, block_size, total_size):
        if total_size <= 0:
            return
        done = block_num * block_size
        pct = min(100, done * 100 // total_size)
        print(f"\r    {pct}% ({done // (1024*1024)} MB / {total_size // (1024*1024)} MB)", end="", flush=True)

    urllib.request.urlretrieve(url, dest, reporthook=_progress)
    print()


def install_ffmpeg():
    TOOLS_DIR.mkdir(parents=True, exist_ok=True)
    zip_path = TOOLS_DIR / "_ffmpeg_download.zip"
    download(FFMPEG_URL, zip_path)

    print("  Extracting ffmpeg.exe...")
    with zipfile.ZipFile(zip_path) as z:
        # The zip contains a single top-level folder like
        # ffmpeg-7.1-essentials_build/bin/ffmpeg.exe plus a LICENSE file.
        # Pull out just what the app needs rather than the whole build
        # (docs, ffplay, ffprobe) to keep the install small.
        members = {name: name for name in z.namelist()}
        exe_member = next((n for n in members if n.endswith("bin/ffmpeg.exe")), None)
        license_member = next((n for n in members if n.upper().endswith("LICENSE") or n.upper().endswith("LICENSE.TXT")), None)
        if not exe_member:
            print("  [FAIL] Could not find ffmpeg.exe inside the downloaded archive.")
            return False
        with z.open(exe_member) as src, open(FFMPEG_EXE, "wb") as dst:
            shutil.copyfileobj(src, dst)
        if license_member:
            with z.open(license_member) as src, open(TOOLS_DIR / "FFMPEG_LICENSE.txt", "wb") as dst:
                shutil.copyfileobj(src, dst)

    zip_path.unlink(missing_ok=True)

    if not FFMPEG_EXE.exists():
        print("  [FAIL] ffmpeg.exe was not extracted.")
        return False
    print(f"  [ OK ] ffmpeg.exe ready at {FFMPEG_EXE}")
    return True


def main():
    existing = ffmpeg_already_available()
    if existing:
        print(f"  [ OK ] ffmpeg already available: {existing}")
        return 0
    ok = install_ffmpeg()
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
