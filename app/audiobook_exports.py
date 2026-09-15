"""CPU-only format exports for completed audiobooks."""

import os
from pathlib import Path
import subprocess
import uuid


class AudiobookExportError(RuntimeError):
    """A completed audiobook could not be exported safely."""


def export_finished_audio(source_path, target_path, format, ffmpeg_path, *, metadata_path=None, cover_path=None):
    """Export one completed audiobook without changing its source file.

    The caller owns destination naming and reuse.  This helper refuses an
    existing target, writes a hidden sibling stage, and atomically promotes it
    only after FFmpeg succeeds.
    """
    source, target, fmt = _validate_paths(source_path, target_path, format)
    metadata = _optional_file(metadata_path, "Metadata")
    cover = _optional_file(cover_path, "Cover")
    temporary = target.with_name(f".{target.stem}.export-{uuid.uuid4().hex}.tmp{target.suffix}")
    try:
        result = subprocess.run(_command(source, temporary, fmt, ffmpeg_path, metadata, cover),
                                capture_output=True, text=True, timeout=300)
        if result.returncode:
            detail = (result.stderr or result.stdout or "unknown ffmpeg failure").strip()
            raise AudiobookExportError(f"ffmpeg could not export {source.name}: {detail}")
        if not temporary.is_file() or not temporary.stat().st_size:
            raise AudiobookExportError(f"ffmpeg did not create {target.name}")
        os.link(temporary, target)
        return target
    except AudiobookExportError:
        raise
    except subprocess.TimeoutExpired as error:
        raise AudiobookExportError("Audiobook export timed out.") from error
    except Exception as error:
        raise AudiobookExportError(f"Could not export audiobook: {error}") from error
    finally:
        temporary.unlink(missing_ok=True)


def _validate_paths(source_path, target_path, format):
    fmt = str(format).lower()
    if fmt not in {"m4b", "mp3", "wav"}:
        raise AudiobookExportError("Export format must be M4B, MP3, or WAV.")
    source, target = Path(source_path), Path(target_path)
    if not source.is_file():
        raise AudiobookExportError(f"Finished audiobook file is missing: {source}")
    if source.resolve() == target.resolve():
        raise AudiobookExportError("Export target must be different from its source file.")
    if target.exists():
        raise AudiobookExportError(f"Export target already exists: {target}")
    if target.suffix.lower() != f".{fmt}":
        raise AudiobookExportError(f"Export target must use the .{fmt} extension.")
    if not target.parent.is_dir():
        raise AudiobookExportError(f"Export folder is unavailable: {target.parent}")
    return source, target, fmt


def _optional_file(path, label):
    if path is None:
        return None
    path = Path(path)
    if not path.is_file():
        raise AudiobookExportError(f"{label} file is unavailable: {path}")
    return path


def _command(source, temporary, fmt, ffmpeg_path, metadata=None, cover=None):
    command = [str(ffmpeg_path), "-y", "-loglevel", "error", "-i", str(source)]
    metadata_index = None
    if metadata:
        metadata_index = 1
        command.extend(["-i", str(metadata)])
    cover_index = 2 if metadata else 1
    if cover:
        command.extend(["-i", str(cover)])
    command.extend(["-map", "0:a", "-map_metadata", str(metadata_index if metadata else 0)])
    if fmt == "wav":
        return [*command, "-map_chapters", "-1", "-c:a", "copy" if source.suffix.lower() == ".wav" else "pcm_s16le",
                "-f", "wav", str(temporary)]
    if cover:
        command.extend(["-map", f"{cover_index}:v:0"])
    else:
        command.extend(["-map", "0:v:disp:attached_pic?"])
    command.extend(["-map_chapters", str(metadata_index if metadata else 0)])
    if fmt == "m4b":
        codec = "copy" if source.suffix.lower() == ".m4b" else "aac"
        command.extend(["-c:a", codec])
        if codec != "copy":
            command.extend(["-b:a", "96k"])
        command.extend(["-c:v", "mjpeg", "-disposition:v:0", "attached_pic", "-f", "mp4"])
    else:
        codec = "copy" if source.suffix.lower() == ".mp3" else "libmp3lame"
        command.extend(["-c:a", codec])
        if codec != "copy":
            command.extend(["-b:a", "96k"])
        command.extend(["-c:v", "mjpeg", "-disposition:v:0", "attached_pic",
                        "-metadata:s:v", "title=Album cover", "-metadata:s:v", "comment=Cover (front)",
                        "-id3v2_version", "3", "-f", "mp3"])
    return [*command, str(temporary)]
