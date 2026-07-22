# Local PDF to Audiobook Pipeline — Standing Rules

Personal project. Local build on my own hardware, for legally purchased books, personal use only.

## Hardware and environment

RTX 4090 (24 GB VRAM), i9-13900K, 32 GB RAM, Windows, Anaconda. Driver supports CUDA 13.3. Stages run sequentially, never concurrently; treat the full GPU as available to whichever single stage is running.

Project root: D:\Audiobook_Pipeline. Conda envs and the fish-speech repo live OUTSIDE this root so data cleanup can't touch model code or weights.

## HARD RULE: do not upgrade Ollama

Working version is ~0.24.x. The 0.30.x line breaks qwen2.5vl:32b vision projector loading. Auto-update stays disabled. Never propose an install or command that could bump Ollama without flagging it first, even if the command doesn't look Ollama-related on its face.

## Environment isolation

THREE isolated conda envs. Never let them cross-contaminate or share packages.
- chatterbox: Python 3.11, torch 2.6.0+cu124. TTS narrator.
- fish-speech: Python 3.12, torch 2.8.0+cu126. Repo at D:\ml_repos\fish-speech, weights at checkpoints\s2-pro. Fallback TTS only, deferred.
- dnd-transcribe: WhisperX, torch 2.8.0+cu128 (unrelated project, pre-existing, do not touch).

## TTS

Chatterbox is the chosen narrator, using voice cloning from a reference clip. Voice cloning is allowed; the reference must NOT be a real identifiable person without rights (licensed, synthetic, or royalty-free only). Default reference clip as of 2026-07-21: D:\Audiobook_Pipeline\samples\Voice_Sample\male_ref.wav (converted from Voice Sample Male.mp3, 20s). The older ref_15s.wav was rejected by the user on listening quality; do not switch back to it. Chatterbox scripts must stub the watermarker (resemble-perth 1.0.1 is missing perth_implicit) and read the mp3 reference with soundfile, not torchaudio, on Windows.

## Extraction models (textbook path, Ollama at http://localhost:11434)

GLM-OCR is primary, run via a tuned Modelfile (glm-ocr-doc) on the /api/generate endpoint with a plain Markdown transcription prompt and num_ctx 16384. Do NOT force JSON on GLM-OCR; it collapses and drops the page. qwen2.5vl:7b is a weak fallback (hallucinated on the test page); 32b is reserve for hard pages only, use /api/chat with base64 images, temperature 0, JSON output.

## Extraction rule

Read body text and section headings. Never read captions, figure/table labels, or repeating boilerplate (title, author, running headers, footers, page numbers). Tables and number-heavy data lists are replaced with a short spoken omission marker, not narrated. Section headings get an audible pause/cue before the body.

## Working style

- Candid tone. Tell me directly when something is a bad idea or won't work. Don't just agree.
- No dashes in any output meant for me to copy and paste.
- Give exact commands. Flag torch/CUDA version pitfalls before they happen.
- Don't debug extraction and narration at the same time; isolate which stage failed.
- Verify claims against real output before asserting they're fixed. Don't assume a fix works from pattern matching alone if a quick test can confirm it.

## Current validated state (updated 2026-07-21)

NOTE: audiobook_pipeline_plan.md referenced by earlier versions of this file does not exist on disk anymore; this section is the authoritative state now.

NOTE: Ollama is at 0.32.1 (upgraded externally, likely for the Map Categorizer project). GLM-OCR verified working on it (full harvest + full-book extraction ran clean). qwen2.5vl:32b reserve is UNTESTED on this version and per the hard rule above may be broken; test before relying on it.

- Checkpoints 0, 1, 2 validated (extraction on DMG test pages, Path A on Project Hail Mary, Chatterbox voice cloning proven).
- Checkpoint 3 complete: page-number leak fix verified on a real harvest rerun (all 7 pages clean); the page 9 duplicate "13" blocks are gone.
- chunk_and_narrate.py (Path A) and narrate_tagged.py (Path B) remain as validated standalone scripts. Tuned pauses: Path B 50ms intra-block, 100ms inter-block, 200ms/150ms heading before/after; Path A 150ms chunk gap, 400ms paragraph gap; 30ms fades.

## Audiobook Studio app (built 2026-07-21)

D:\Audiobook_Pipeline\app\ is a local web app wrapping the whole pipeline, PDF to audiobook. Start it with D:\Audiobook_Pipeline\Start_Audiobook_Studio.bat, UI at http://localhost:8765.

- server.py runs in BASE miniconda (stdlib + fitz + requests only, nothing installed). One worker thread runs all stages strictly sequentially, so Ollama extraction and Chatterbox narration never share the GPU.
- pipeline_text.py: shared tagging/extraction. Carries the verified page-number filter plus: headings may end in ? or !, markdown emphasis stripped, cross-page mid-sentence stitching, Path A prose mode (path_a.py x-indent rule, font-size-based drop-cap merge) and verse mode (sentence-run grouping, Book N headings), auto-detected by capitalized-line-start fraction (>0.45 = verse).
- narrate_worker.py runs in the chatterbox env as a subprocess. Per-chunk WAV segments make narration resumable; parts assembled at block boundaries, ~60 min each, PCM_16 24kHz.
- Jobs live in app\jobs\<id>\ (state.json, pages\, segments\, output\, log.txt). Path B caches per-page OCR .md so extraction also resumes. Finished parts are also copied to D:\Audiobook_Pipeline\audiobooks\<title>\.
- GLM-OCR degenerates on full-page ARTWORK pages (endless code fences, empty HTML tables, or looped short tokens). Guards in pipeline_text.tag_blocks: markup-only and code-fence lines dropped, consecutive duplicate body blocks collapsed, and any page whose blocks are >=20 with <30% unique text returns empty (art page). ocr_page caps num_predict at 4096. narrate_worker fingerprints the chunk plan and wipes stale segments if blocks change.
- Voice cloning: users can upload a voice sample in the UI (wav/mp3/flac/ogg, converted via convert_voice.py in the chatterbox env, soundfile only, trimmed to 20s) and pick a voice per job. Default voice is samples\Voice_Sample\male_ref.wav ("Default narrator (male sample)"). The rights rule above applies to uploads.
- Repo cleaned 2026-07-21 for GitHub: deleted audio_raw\, extracted\, narration_input\, harvest_output\, image_samples\, one-off run_*/inspect_* scripts and glm_* artifacts, and the 7 redundant single-page L_D_M PDFs (full book kept). git init done, no commits yet; .gitignore excludes all PDFs/audio/jobs so only code and docs (15 files) are tracked. README.md added.
- Design decisions applied (were open threads 3/4): CHECKLIST FOR X sections get normal heading treatment; epigraphs stay plain body.
- Verified end to end 2026-07-21: 1-page Path B job produced 53.7s of real narrated audio through the UI. Full Odyssey extraction dry-run: verse mode, 4465 blocks, all 24 Book headings detected.

## Book-specific notes

- Return of the Lazy Dungeon Master (samples\L_D_M): 88 pages, Path B. Full-book job queued 2026-07-21.
- The Odyssey (samples\The Odyssey): 793 pages, Path A verse. The poem is pages 78 to 610; pages 1-77 are front matter and 611+ are notes/commentary, so create the job with that range. Roughly 14 hours of audio.
- PHM (samples\Novel sample): 523 pages, Path A prose, was the checkpoint 1 test book.
