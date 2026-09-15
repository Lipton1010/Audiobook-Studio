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

import audiobook_files


FFMPEG = shutil.which("ffmpeg") or r"C:\ProgramData\chocolatey\bin\ffmpeg.exe"


def probe(path, entries):
    command = ["ffprobe", "-v", "error", "-show_entries", entries, "-of", "json", str(path)]
    return json.loads(subprocess.check_output(command, text=True))


def audio_packets(path):
    command = ["ffprobe", "-v", "error", "-select_streams", "a:0", "-show_packets", "-show_data_hash", "sha256", "-of", "json", str(path)]
    return json.loads(subprocess.check_output(command, text=True))["packets"]


def audio_packet_hashes(path):
    return [packet["data_hash"] for packet in audio_packets(path)]


def cover_image(path):
    return subprocess.check_output(["ffmpeg", "-y", "-loglevel", "error", "-i", str(path), "-map", "0:v:0", "-frames:v", "1", "-f", "image2pipe", "-vcodec", "png", "pipe:1"])


class ArtworkReplacementTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.artwork = self.root / "replacement.png"
        self._ffmpeg("-f", "lavfi", "-i", "color=cornflowerblue:s=32x32", "-frames:v", "1", str(self.artwork))
        self.source_art = self.root / "original.png"
        self._ffmpeg("-f", "lavfi", "-i", "color=orange:s=32x32", "-frames:v", "1", str(self.source_art))

    def tearDown(self):
        self.temp.cleanup()

    def _ffmpeg(self, *arguments):
        subprocess.run([FFMPEG, "-y", "-loglevel", "error", *arguments], check=True)

    def _audiobook(self, name, fmt):
        audio = self.root / f"{name}.{fmt}"
        metadata = self.root / f"{name}.ffmeta"
        metadata.write_text(";FFMETADATA1\ntitle=Synthetic Book\nartist=Test Narrator\nalbum=Synthetic Album\n[CHAPTER]\nTIMEBASE=1/1000\nSTART=0\nEND=1000\ntitle=Chapter One\n[CHAPTER]\nTIMEBASE=1/1000\nSTART=1000\nEND=2000\ntitle=Chapter Two\n", encoding="utf-8")
        codec = ("aac", "96k", "mp4") if fmt == "m4b" else ("libmp3lame", "96k", "mp3")
        self._ffmpeg("-f", "lavfi", "-i", "sine=frequency=1000:duration=2", "-i", str(metadata), "-i", str(self.source_art), "-map", "0:a", "-map", "2:v", "-map_metadata", "1", "-c:a", codec[0], "-b:a", codec[1], "-c:v", "mjpeg", "-disposition:v:0", "attached_pic", "-f", codec[2], str(audio))
        return audio

    def test_replaces_m4b_artwork_without_changing_audio_packets_chapters_or_metadata(self):
        source = self._audiobook("synthetic", "m4b")
        before_packets = audio_packet_hashes(source)
        old_cover = cover_image(source)
        before = probe(source, "format:format_tags:chapters")
        cover = self.root / "cover_override.png"
        backups = audiobook_files.replace_finished_artwork([source], self.artwork, FFMPEG, cover_target=cover)
        self.assertEqual(audio_packet_hashes(source), before_packets)
        after = probe(source, "format:format_tags:chapters")
        self.assertEqual(after["chapters"], before["chapters"])
        self.assertEqual({key: after["format"]["tags"][key] for key in ("title", "artist", "album")},
                         {key: before["format"]["tags"][key] for key in ("title", "artist", "album")})
        self.assertNotEqual(hashlib.sha256(cover_image(source)).hexdigest(), hashlib.sha256(old_cover).hexdigest())
        self.assertEqual(cover.read_bytes(), self.artwork.read_bytes())
        self.assertTrue(backups[source].is_file())

    def test_replaces_mp3_artwork_without_changing_audio_packets_or_gapless_metadata(self):
        source = self._audiobook("synthetic", "mp3")
        before_packets = audio_packet_hashes(source)
        before = probe(source, "format=start_time,duration:stream=codec_name,sample_rate,channels,start_time,duration:format_tags")
        audiobook_files.replace_finished_artwork([source], self.artwork, FFMPEG)
        self.assertEqual(audio_packet_hashes(source), before_packets)
        after = probe(source, "format=start_time,duration:stream=codec_name,sample_rate,channels,start_time,duration:format_tags")
        self.assertEqual(after["format"], before["format"])
        self.assertEqual(after["streams"], before["streams"])

    def test_partial_ffmpeg_stage_is_removed_when_encoding_fails(self):
        source = self._audiobook("synthetic", "m4b")

        def partial_failure(command, **_kwargs):
            Path(command[-1]).write_bytes(b"partial")
            return types.SimpleNamespace(returncode=1, stderr="synthetic failure", stdout="")

        with mock.patch.object(audiobook_files.subprocess, "run", side_effect=partial_failure):
            with self.assertRaises(audiobook_files.ArtworkReplacementError):
                audiobook_files.replace_finished_artwork([source], self.artwork, FFMPEG)
        self.assertFalse(list(self.root.glob(".*.artwork-*.tmp.*")))

    def test_ffmpeg_failure_keeps_audio_and_cover_override_unchanged(self):
        source = self._audiobook("synthetic", "m4b")
        cover = self.root / "cover_override.png"
        cover.write_bytes(b"old-cover")
        original_audio, original_cover = source.read_bytes(), cover.read_bytes()
        with self.assertRaises(audiobook_files.ArtworkReplacementError):
            audiobook_files.replace_finished_artwork([source], self.artwork, "missing-ffmpeg.exe", cover_target=cover)
        self.assertEqual(source.read_bytes(), original_audio)
        self.assertEqual(cover.read_bytes(), original_cover)

    def test_promotion_failure_rolls_back_all_audio_and_cover_files(self):
        first, second = self._audiobook("one", "m4b"), self._audiobook("two", "mp3")
        cover = self.root / "cover_override.png"
        cover.write_bytes(b"old-cover")
        original = {path: path.read_bytes() for path in (first, second, cover)}
        real_replace = audiobook_files.os.replace
        calls = 0

        def fail_second_install(source, destination):
            nonlocal calls
            calls += 1
            if calls == 5:
                raise OSError("synthetic promotion failure")
            return real_replace(source, destination)

        with mock.patch.object(audiobook_files.os, "replace", side_effect=fail_second_install):
            with self.assertRaises(audiobook_files.ArtworkReplacementError):
                audiobook_files.replace_finished_artwork([first, second], self.artwork, FFMPEG, cover_target=cover)
        for path, data in original.items():
            self.assertEqual(path.read_bytes(), data)

    def test_wav_reports_its_embedded_artwork_limitation(self):
        wav = self.root / "synthetic.wav"
        self._ffmpeg("-f", "lavfi", "-i", "anullsrc=r=24000:cl=mono", "-t", "0.1", str(wav))
        with self.assertRaisesRegex(audiobook_files.ArtworkReplacementError, "WAV files have no standard embedded cover artwork"):
            audiobook_files.replace_finished_artwork([wav], self.artwork, FFMPEG)

    def test_m4b_without_audio_is_not_promoted(self):
        source = self.root / "cover-only.m4b"
        self._ffmpeg("-loop", "1", "-i", str(self.source_art), "-t", "0.1", "-c:v", "mjpeg", "-f", "mp4", str(source))
        before = source.read_bytes()
        with self.assertRaises(audiobook_files.ArtworkReplacementError):
            audiobook_files.replace_finished_artwork([source], self.artwork, FFMPEG)
        self.assertEqual(source.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
