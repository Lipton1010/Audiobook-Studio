"""VibeVoice's dependency-light equivalent of the production stream assembler."""

import re
import shutil
import subprocess
import os
from pathlib import Path

import numpy as np
import soundfile as sf
from assembly_metadata import is_outline_chapter_title, outline_chapter_marks


AAC_BITRATE = "64k"

def _ffmpeg():
    return shutil.which("ffmpeg") or str(Path(__file__).resolve().parent.parent / "tools" / "ffmpeg.exe")


def _ffmeta_escape(value):
    value = str(value).replace("\\", "\\\\").replace("\n", " ")
    for character in ("=", ";", "#"):
        value = value.replace(character, "\\" + character)
    return value


def _metadata(job_dir, total_ms, metadata, chapters):
    lines = [";FFMETADATA1"]
    for key, value in (metadata or {}).items():
        if value:
            lines.append(f"{_ffmeta_escape(key)}={_ffmeta_escape(value)}")
    for index, (start, title) in enumerate(chapters):
        end = chapters[index + 1][0] if index + 1 < len(chapters) else total_ms
        lines.extend(["[CHAPTER]", "TIMEBASE=1/1000", f"START={start}", f"END={max(end, start + 1000)}", f"title={_ffmeta_escape(title)}"])
    path = Path(job_dir) / "vibevoice.ffmeta"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _encode(fmt, chunks, sr, output, metadata, log, cover):
    codec = ["-c:a", "aac", "-b:a", AAC_BITRATE, "-f", "mp4"] if fmt == "m4b" else ["-c:a", "libmp3lame", "-b:a", AAC_BITRATE, "-f", "mp3"]
    command = [_ffmpeg(), "-y", "-loglevel", "warning", "-f", "s16le", "-ar", str(sr), "-ac", "1", "-i", "pipe:0", "-i", str(metadata)]
    maps = ["-map", "0:a", "-map_metadata", "1"]
    if cover and Path(cover).is_file():
        command.extend(["-i", str(cover)])
        maps.extend(["-map", "2:v", "-c:v", "mjpeg", "-disposition:v:0", "attached_pic"])
    command.extend([*maps, *codec, str(output)])
    process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=log, stderr=log)
    try:
        for audio in chunks:
            process.stdin.write((np.clip(audio, -1, 1) * 32767).astype("<i2").tobytes())
        process.stdin.close()
    except BaseException:
        if process.stdin:
            process.stdin.close()
        process.terminate()
        process.wait()
        raise
    if process.wait():
        raise RuntimeError("ffmpeg failed VibeVoice assembly; see log")


def assemble(job_dir, passages, config, segment_path, cancelled=lambda: False):
    """Write the requested final format without importing Chatterbox."""
    job_dir = Path(job_dir)
    output_dir = job_dir / "output"
    output_dir.mkdir(exist_ok=True)
    fmt = config.get("format", "m4b").lower()
    if fmt not in {"wav", "m4b", "mp3"}:
        raise ValueError(f"unsupported VibeVoice format {fmt}")
    title = re.sub(r"[^\w -]", "", config.get("title", "audiobook")).strip() or "audiobook"
    paths = [segment_path(p["index"]) for p in passages]
    if not paths:
        raise RuntimeError("cannot assemble an empty VibeVoice plan")
    sr = sf.info(str(paths[0])).samplerate
    cursor, detected_chapters, page_starts, seen_pages = 0, [], [], set()
    for passage, path in zip(passages, paths):
        if passage.get("heading") and is_outline_chapter_title(passage["heading"]):
            detected_chapters.append((int(cursor / sr * 1000), passage["heading"]))
        for page in passage.get("source_pages", []):
            if page not in seen_pages:
                page_starts.append((page, int(cursor / sr * 1000)))
                seen_pages.add(page)
        cursor += int(sr * passage.get("before_ms", 0) / 1000)
        cursor += sf.info(str(path)).frames
        cursor += int(sr * passage.get("after_ms", 0) / 1000)
    outline_chapters = outline_chapter_marks(config.get("pdf_outline"), page_starts)
    chapters = outline_chapters if len(outline_chapters) > len(detected_chapters) else detected_chapters
    if chapters and chapters[0][0] > 1500:
        chapters.insert(0, (0, "Opening"))

    def chunks():
        for passage, path in zip(passages, paths):
            if cancelled():
                raise SystemExit(2)
            before = int(sr * passage.get("before_ms", 0) / 1000)
            if before:
                yield np.zeros(before, dtype=np.float32)
            audio, actual_sr = sf.read(str(path), dtype="float32")
            if actual_sr != sr or audio.ndim != 1 or not np.isfinite(audio).all():
                raise RuntimeError(f"invalid VibeVoice segment {path.name}")
            yield audio
            after = int(sr * passage.get("after_ms", 0) / 1000)
            if after:
                yield np.zeros(after, dtype=np.float32)

    metadata_path = _metadata(job_dir, int(cursor / sr * 1000), config.get("metadata"), chapters)
    output = output_dir / f"{title}.{fmt}"
    temporary = output.with_name(f".{output.stem}.tmp{os.getpid()}{output.suffix}")
    try:
        if fmt == "wav":
            wav_options = {"format": "RF64"} if cursor * 2 + 44 > int(3.9 * 1024 ** 3) else {}
            with sf.SoundFile(str(temporary), "w", samplerate=sr, channels=1, subtype="PCM_16", **wav_options) as handle:
                for audio in chunks():
                    handle.write(audio)
        else:
            with (job_dir / "log.txt").open("a", encoding="utf-8") as log:
                _encode(fmt, chunks(), sr, temporary, metadata_path, log, config.get("cover_image"))
        if cancelled():
            raise SystemExit(2)
        temporary.replace(output)
    finally:
        temporary.unlink(missing_ok=True)
    for stale in output_dir.glob(f"{title}.*"):
        if stale != output and stale.suffix.lower() in {".wav", ".m4b", ".mp3"}:
            stale.unlink()
    return output
