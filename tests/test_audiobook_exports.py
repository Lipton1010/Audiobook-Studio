import hashlib
import json
import shutil
import subprocess
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))

import audiobook_exports


FFMPEG = shutil.which("ffmpeg") or r"C:\ProgramData\chocolatey\bin\ffmpeg.exe"


def probe(path, entries):
    return json.loads(subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", entries, "-of", "json", str(path)], text=True))


def artwork(path):
    return subprocess.check_output(["ffmpeg", "-loglevel", "error", "-i", str(path), "-map", "0:v:0", "-frames:v", "1", "-f", "image2pipe", "-vcodec", "png", "pipe:1"])


class FinishedAudiobookExportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.cover = self.root / "cover.png"
        self._ffmpeg("-f", "lavfi", "-i", "color=plum:s=32x32", "-frames:v", "1", str(self.cover))
        self.source = self.root / "source.m4b"
        metadata = self.root / "chapters.ffmeta"
        metadata.write_text(";FFMETADATA1\ntitle=Synthetic Book\nartist=Test Narrator\nalbum=Synthetic Album\n[CHAPTER]\nTIMEBASE=1/1000\nSTART=0\nEND=1000\ntitle=Chapter One\n[CHAPTER]\nTIMEBASE=1/1000\nSTART=1000\nEND=2000\ntitle=Chapter Two\n", encoding="utf-8")
        self._ffmpeg("-f", "lavfi", "-i", "sine=frequency=880:duration=2", "-i", str(metadata), "-i", str(self.cover), "-map", "0:a", "-map", "2:v", "-map_metadata", "1", "-c:a", "aac", "-b:a", "96k", "-c:v", "mjpeg", "-disposition:v:0", "attached_pic", "-f", "mp4", str(self.source))
        self.source_hash = hashlib.sha256(self.source.read_bytes()).hexdigest()

    def tearDown(self):
        self.temp.cleanup()

    def _ffmpeg(self, *arguments):
        subprocess.run([FFMPEG, "-y", "-loglevel", "error", *arguments], check=True)

    def test_m4b_export_preserves_metadata_chapters_artwork_and_source(self):
        target = self.root / "export.m4b"
        before = probe(self.source, "format_tags:chapters")
        self.assertEqual(audiobook_exports.export_finished_audio(self.source, target, "m4b", FFMPEG), target)
        after = probe(target, "format_tags:chapters")
        self.assertEqual(after["chapters"], before["chapters"])
        self.assertEqual({key: after["format"]["tags"][key] for key in ("title", "artist", "album")},
                         {key: before["format"]["tags"][key] for key in ("title", "artist", "album")})
        self.assertEqual(hashlib.sha256(artwork(target)).hexdigest(), hashlib.sha256(artwork(self.source)).hexdigest())
        self.assertEqual(hashlib.sha256(self.source.read_bytes()).hexdigest(), self.source_hash)

    def test_mp3_export_preserves_metadata_chapters_and_artwork_without_touching_source(self):
        target = self.root / "export.mp3"
        self.assertEqual(audiobook_exports.export_finished_audio(self.source, target, "mp3", FFMPEG), target)
        tags = probe(target, "format_tags")["format"]["tags"]
        self.assertEqual({key: tags[key] for key in ("title", "artist", "album")},
                         {"title": "Synthetic Book", "artist": "Test Narrator", "album": "Synthetic Album"})
        self.assertEqual(probe(target, "chapters")["chapters"], probe(self.source, "chapters")["chapters"])
        self.assertTrue(artwork(target).startswith(b"\x89PNG"))
        self.assertEqual(hashlib.sha256(self.source.read_bytes()).hexdigest(), self.source_hash)

    def test_wav_export_is_riff_without_embedded_artwork_or_chapters(self):
        target = self.root / "export.wav"
        audiobook_exports.export_finished_audio(self.source, target, "wav", FFMPEG)
        self.assertTrue(target.read_bytes().startswith(b"RIFF"))
        details = probe(target, "stream=codec_type:chapters")
        self.assertEqual([stream["codec_type"] for stream in details["streams"]], ["audio"])
        self.assertEqual(details["chapters"], [])
        self.assertEqual(hashlib.sha256(self.source.read_bytes()).hexdigest(), self.source_hash)

    def test_wav_export_uses_job_metadata_and_cover_when_creating_m4b(self):
        wav = self.root / "master.wav"
        metadata = self.root / "job.ffmeta"
        metadata.write_text(";FFMETADATA1\ntitle=Recovered Book\nartist=Recovered Narrator\n"
                            "[CHAPTER]\nTIMEBASE=1/1000\nSTART=0\nEND=2000\ntitle=Recovered Chapter\n",
                            encoding="utf-8")
        self._ffmpeg("-f", "lavfi", "-i", "sine=frequency=550:duration=2", "-c:a", "pcm_s16le", str(wav))
        target = self.root / "recovered.m4b"
        audiobook_exports.export_finished_audio(wav, target, "m4b", FFMPEG,
                                                metadata_path=metadata, cover_path=self.cover)
        details = probe(target, "format_tags:chapters")
        self.assertEqual(details["format"]["tags"]["title"], "Recovered Book")
        self.assertEqual(details["format"]["tags"]["artist"], "Recovered Narrator")
        self.assertEqual(details["chapters"][0]["tags"]["title"], "Recovered Chapter")
        self.assertTrue(artwork(target).startswith(b"\x89PNG"))

    def test_failure_leaves_no_published_target_or_stage(self):
        target = self.root / "export.m4b"
        with self.assertRaises(audiobook_exports.AudiobookExportError):
            audiobook_exports.export_finished_audio(self.source, target, "m4b", "missing-ffmpeg.exe")
        self.assertFalse(target.exists())
        self.assertFalse(list(self.root.glob(".*.export-*.tmp.*")))

    def test_partial_failed_stage_is_removed(self):
        target = self.root / "export.m4b"

        def partial_failure(command, **_kwargs):
            Path(command[-1]).write_bytes(b"partial")
            return types.SimpleNamespace(returncode=1, stderr="synthetic failure", stdout="")

        with mock.patch.object(audiobook_exports.subprocess, "run", side_effect=partial_failure):
            with self.assertRaises(audiobook_exports.AudiobookExportError):
                audiobook_exports.export_finished_audio(self.source, target, "m4b", FFMPEG)
        self.assertFalse(target.exists())
        self.assertFalse(list(self.root.glob(".*.export-*.tmp.*")))

    def test_target_created_during_export_is_preserved(self):
        target = self.root / "export.m4b"

        def competitor(command, **_kwargs):
            Path(command[-1]).write_bytes(b"finished export")
            target.write_bytes(b"another writer")
            return types.SimpleNamespace(returncode=0, stderr="", stdout="")

        with mock.patch.object(audiobook_exports.subprocess, "run", side_effect=competitor):
            with self.assertRaises(audiobook_exports.AudiobookExportError):
                audiobook_exports.export_finished_audio(self.source, target, "m4b", FFMPEG)
        self.assertEqual(target.read_bytes(), b"another writer")
        self.assertFalse(list(self.root.glob(".*.export-*.tmp.*")))

    def test_ordinary_video_is_not_exported_as_artwork(self):
        source = self.root / "video.m4b"
        self._ffmpeg("-f", "lavfi", "-i", "sine=frequency=440:duration=1",
                     "-f", "lavfi", "-i", "color=red:s=32x32:d=1",
                     "-c:a", "aac", "-c:v", "mpeg4", "-f", "mp4", str(source))
        target = self.root / "audio_only.m4b"
        audiobook_exports.export_finished_audio(source, target, "m4b", FFMPEG)
        self.assertEqual([s["codec_type"] for s in probe(target, "stream=codec_type")["streams"]], ["audio"])

    def test_existing_target_is_never_overwritten(self):
        target = self.root / "export.mp3"
        target.write_bytes(b"keep")
        with self.assertRaisesRegex(audiobook_exports.AudiobookExportError, "already exists"):
            audiobook_exports.export_finished_audio(self.source, target, "mp3", FFMPEG)
        self.assertEqual(target.read_bytes(), b"keep")


if __name__ == "__main__":
    unittest.main()
