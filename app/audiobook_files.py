"""Transactional artwork updates for completed MP3 and M4B audiobooks."""

import os
from pathlib import Path
import shutil
import subprocess
import uuid


class ArtworkReplacementError(RuntimeError):
    """An artwork update left every target in its original state."""


def replace_finished_artwork(audio_paths, artwork_path, ffmpeg_path, *, cover_target=None):
    """Embed a staged PNG in each finished audio file and optionally save it as a cover override.

    ``audio_paths`` and ``cover_target`` must already have been authorized by the
    caller.  On success, returns ``{target: original_backup}``; callers may use
    those retained files as output history.  On failure, the function removes its
    staged files and restores every original it moved.
    """
    artwork = Path(artwork_path)
    targets = _audio_targets(audio_paths)
    _validate_png(artwork)
    token = uuid.uuid4().hex
    staged = []
    temporaries = []
    try:
        for target in targets:
            temporary = _temporary_path(target, token, "tmp")
            temporaries.append(temporary)
            _replace_embedded_artwork(target, artwork, temporary, ffmpeg_path)
            if not temporary.is_file() or not temporary.stat().st_size:
                raise ArtworkReplacementError(f"ffmpeg did not create artwork update for {target.name}")
            staged.append((target, temporary))
        if cover_target is not None:
            cover = Path(cover_target)
            if cover.suffix.lower() != ".png" or cover in targets:
                raise ArtworkReplacementError("Cover override must be a separate PNG path.")
            temporary = _temporary_path(cover, token, "tmp")
            temporaries.append(temporary)
            shutil.copyfile(artwork, temporary)
            staged.append((cover, temporary))
        return _promote(staged, token)
    except ArtworkReplacementError:
        raise
    except Exception as error:
        raise ArtworkReplacementError(f"Could not replace audiobook artwork: {error}") from error
    finally:
        for temporary in temporaries:
            temporary.unlink(missing_ok=True)


def _audio_targets(audio_paths):
    targets = []
    seen = set()
    for raw_path in audio_paths:
        path = Path(raw_path)
        key = os.path.normcase(str(path.resolve()))
        if key in seen:
            continue
        seen.add(key)
        if path.suffix.lower() == ".wav":
            raise ArtworkReplacementError("WAV files have no standard embedded cover artwork; choose MP3 or M4B.")
        if path.suffix.lower() not in {".m4b", ".mp3"}:
            raise ArtworkReplacementError(f"Artwork replacement supports only MP3 and M4B, not {path.suffix or 'this file'}.")
        if not path.is_file():
            raise ArtworkReplacementError(f"Finished audiobook file is missing: {path}")
        targets.append(path)
    if not targets:
        raise ArtworkReplacementError("No finished MP3 or M4B files were supplied.")
    return targets


def _validate_png(path):
    try:
        header = path.read_bytes()[:8]
    except OSError as error:
        raise ArtworkReplacementError(f"Artwork file is unavailable: {path}") from error
    if header != b"\x89PNG\r\n\x1a\n":
        raise ArtworkReplacementError("Artwork must be a validated PNG image.")


def _temporary_path(target, token, role):
    return target.with_name(f".{target.stem}.artwork-{token}.{role}{target.suffix}")


def _replace_embedded_artwork(source, artwork, temporary, ffmpeg_path):
    command = [
        str(ffmpeg_path), "-y", "-loglevel", "error", "-i", str(source), "-i", str(artwork),
        "-map", "0:a", "-map", "1:v:0", "-map_metadata", "0", "-map_chapters", "0",
        "-c:a", "copy", "-c:v", "mjpeg", "-disposition:v:0", "attached_pic",
    ]
    if source.suffix.lower() == ".mp3":
        command.extend(["-metadata:s:v", "title=Album cover", "-metadata:s:v", "comment=Cover (front)", "-id3v2_version", "3"])
    command.append(str(temporary))
    result = subprocess.run(command, capture_output=True, text=True, timeout=300)
    if result.returncode:
        detail = (result.stderr or result.stdout or "unknown ffmpeg failure").strip()
        raise ArtworkReplacementError(f"ffmpeg could not update {source.name}: {detail}")


def _promote(staged, token):
    backups = {}
    moved = []
    installed = []
    try:
        for target, _ in staged:
            if target.exists():
                backup = _temporary_path(target, token, "artwork-backup")
                os.replace(target, backup)
                backups[target] = backup
                moved.append((target, backup))
        for target, temporary in staged:
            os.replace(temporary, target)
            installed.append(target)
        return backups
    except Exception as error:
        rollback_errors = []
        for target, backup in reversed(moved):
            try:
                os.replace(backup, target)
            except Exception as rollback_error:
                rollback_errors.append(f"{target.name}: {rollback_error}")
        for target in installed:
            if target not in backups:
                try:
                    target.unlink(missing_ok=True)
                except OSError as rollback_error:
                    rollback_errors.append(f"{target.name}: {rollback_error}")
        suffix = f" Rollback also failed for {', '.join(rollback_errors)}." if rollback_errors else ""
        raise ArtworkReplacementError(f"Could not promote updated artwork.{suffix}") from error
