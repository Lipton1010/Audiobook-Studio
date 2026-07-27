r"""
ffmpeg auto-fetch for machines that don't have it.

ffmpeg is not an "installed program" in the Windows sense (no installer, no
registry entries) -- it is a static executable. So instead of running an
installer, this downloads the gyan.dev "essentials" static build (a
widely-used, redistributable build of ffmpeg; LGPL/GPL depending on which
codecs are compiled in -- the essentials build's LICENSE file is copied
alongside the binary so that stays intact) and drops ffmpeg.exe into the
repo's own tools\ folder.

The app is pointed at this exact path (see config.py / narrate_worker.py), so
there is no PATH editing and no admin rights required. If the user already has
ffmpeg on PATH or at the chocolatey path, this is a no-op.

The download is ~110 MB (the whole essentials build; only ffmpeg.exe and the
LICENSE are kept). The zip URL is a moving "latest" alias, so the version that
arrives is whatever gyan.dev is publishing that day. Two guards against getting
a bad one: the publisher's own .sha256 is checked when it can be fetched, and
the extracted binary is run once with -version before this reports success.

Safe to re-run.
"""
import hashlib
import os
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
TOOLS_DIR = REPO / "tools"
FFMPEG_EXE = TOOLS_DIR / "ffmpeg.exe"
# The binary is extracted under this name and only renamed to ffmpeg.exe once it
# has been executed successfully. See install_ffmpeg() for why that matters.
FFMPEG_CANDIDATE = TOOLS_DIR / "_ffmpeg_candidate.exe"

# gyan.dev publishes a stable "release essentials" zip alias at this URL,
# alongside a matching .sha256 of the same name.
FFMPEG_URL = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"
FFMPEG_SHA_URL = FFMPEG_URL + ".sha256"


def runs_ok(exe):
    """Execute the binary rather than trusting that it exists.

    Existence is not evidence of a working ffmpeg. A truncated download, a file
    quarantined mid-write by antivirus, or a binary for the wrong architecture
    all leave a plausible-looking ffmpeg.exe on disk. Each of those otherwise
    surfaces at the END of a multi-hour narration, when the m4b encode fails."""
    try:
        r = subprocess.run([str(exe), "-version"], capture_output=True,
                           text=True, timeout=60)
    except Exception:
        return False
    return r.returncode == 0


def ffmpeg_already_available():
    """Path to a WORKING ffmpeg, or None. Order: PATH, our tools\ copy, choco."""
    candidates = [shutil.which("ffmpeg"), FFMPEG_EXE,
                  Path(r"C:\ProgramData\chocolatey\bin\ffmpeg.exe")]
    for cand in candidates:
        if cand and Path(cand).exists() and runs_ok(cand):
            return str(cand)
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


def verify_hash(zip_path):
    """Best effort. A mismatch is fatal (the download is corrupt or tampered
    with); an unreachable .sha256 is only a warning, since it would be silly to
    fail the whole install because a checksum file moved."""
    try:
        with urllib.request.urlopen(FFMPEG_SHA_URL, timeout=30) as r:
            published = r.read().decode("ascii", "ignore").split()[0].strip().lower()
    except Exception as e:
        print(f"  [WARN] could not fetch the published checksum ({e}); skipping hash check")
        return True
    h = hashlib.sha256()
    with open(zip_path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    actual = h.hexdigest().lower()
    if actual != published:
        print("  [FAIL] downloaded ffmpeg zip does not match the publisher's SHA-256.")
        print(f"         expected {published}")
        print(f"         got      {actual}")
        return False
    print("  [ OK ] archive checksum matches the publisher's SHA-256")
    return True


def install_ffmpeg():
    TOOLS_DIR.mkdir(parents=True, exist_ok=True)
    FFMPEG_CANDIDATE.unlink(missing_ok=True)
    zip_path = TOOLS_DIR / "_ffmpeg_download.zip"
    download(FFMPEG_URL, zip_path)

    if not verify_hash(zip_path):
        zip_path.unlink(missing_ok=True)
        return False

    print("  Extracting ffmpeg.exe...")
    with zipfile.ZipFile(zip_path) as z:
        # The zip contains a single versioned top-level folder, e.g.
        # ffmpeg-8.1.2-essentials_build/bin/ffmpeg.exe plus a LICENSE file.
        # Pull out just what the app needs rather than the whole build
        # (docs, ffplay, ffprobe) to keep the install small. Zip entry names
        # always use forward slashes per the spec, but normalise anyway so a
        # nonconforming archive can't silently match nothing.
        names = z.namelist()
        norm = {n: n.replace("\\", "/") for n in names}
        exe_member = next((n for n in names if norm[n].endswith("bin/ffmpeg.exe")), None)
        license_member = next(
            (n for n in names if norm[n].upper().endswith("LICENSE")
             or norm[n].upper().endswith("LICENSE.TXT")), None)
        if not exe_member:
            print("  [FAIL] Could not find ffmpeg.exe inside the downloaded archive.")
            print(f"         archive contained {len(names)} entries, e.g. {names[:3]}")
            return False
        with z.open(exe_member) as src, open(FFMPEG_CANDIDATE, "wb") as dst:
            shutil.copyfileobj(src, dst)
        if license_member:
            with z.open(license_member) as src, open(TOOLS_DIR / "FFMPEG_LICENSE.txt", "wb") as dst:
                shutil.copyfileobj(src, dst)
        else:
            print("  [WARN] no LICENSE file found in the archive; the binary is still "
                  "redistributable but its licence text was not copied.")

    zip_path.unlink(missing_ok=True)

    if not FFMPEG_CANDIDATE.exists():
        print("  [FAIL] ffmpeg.exe was not extracted.")
        return False

    # Validate BEFORE the binary takes its final name.
    #
    # Extracting straight to tools\ffmpeg.exe and validating in place was a real
    # bug: a failed check returned False but LEFT THE BROKEN BINARY ON DISK, and
    # every later check tested existence only (setup.py's _find_ffmpeg, this
    # module's own ffmpeg_already_available, config.warnings). A corrupt fetch
    # therefore reported overall success, wrote no warning, and surfaced hours
    # later as a failed m4b encode. The file only gets its real name once it has
    # actually run.
    try:
        r = subprocess.run([str(FFMPEG_CANDIDATE), "-version"],
                           capture_output=True, text=True, timeout=60)
    except Exception as e:
        print(f"  [FAIL] extracted ffmpeg.exe but could not run it: {e}")
        FFMPEG_CANDIDATE.unlink(missing_ok=True)
        return False
    if r.returncode != 0:
        print(f"  [FAIL] extracted ffmpeg.exe exited {r.returncode} on -version")
        FFMPEG_CANDIDATE.unlink(missing_ok=True)
        return False

    # Atomic on Windows when both paths are on the same volume, so a crash here
    # cannot leave a half-written ffmpeg.exe behind.
    try:
        os.replace(FFMPEG_CANDIDATE, FFMPEG_EXE)
    except Exception as e:
        print(f"  [FAIL] could not move the verified binary into place: {e}")
        FFMPEG_CANDIDATE.unlink(missing_ok=True)
        return False

    first = (r.stdout or "").splitlines()[:1]
    print(f"  [ OK ] {first[0] if first else 'ffmpeg runs'}")
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
