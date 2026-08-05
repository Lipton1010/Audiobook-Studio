# Audiobook Studio agent entry point

Read `CLAUDE.md` completely before changing this project. It is the
authoritative current-state record despite its historical filename.

Load only the relevant detailed record under `.claude/skills/` when working on
installer/release, extraction/performance, narration auditions, book-specific
notes, or beta field reports. Those files are chronological evidence; later
entries and `CLAUDE.md` supersede earlier snapshots.

Hard project rules:

1. OCR and TTS never overlap on the GPU.
2. Keep the chatterbox, fish-speech, and dnd-transcribe environments isolated.
3. Never track or distribute purchased book text, PDFs, generated audio, or
   unlicensed voice samples.
4. Verify extraction and narration separately and test claims against real or
   synthetic output before marking them fixed.
5. Run Git writes from native Windows because `core.autocrlf` protects this
   CRLF working tree. Do not stage from Linux tooling.
6. Run `python -m unittest discover -s tests -v` before a release commit.
7. Build installers only with `install\build_installer.bat` from clean `HEAD`.
8. Do not publish a release until `RELEASE_CHECKLIST.md` is fully satisfied.
