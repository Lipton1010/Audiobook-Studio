# Local PDF to Audiobook Pipeline — Standing Rules

Personal project. Local build on my own hardware, for legally purchased books, personal use only.

## Hardware and environment

RTX 4090 (24 GB VRAM), i9-13900K, 32 GB RAM, Windows, Anaconda. Driver supports CUDA 13.3.

GPU concurrency rule (revised 2026-07-22): DIFFERENT stages never overlap on the GPU. OCR (Ollama) and TTS (Chatterbox) must not run at the same time; the running stage owns the whole GPU. But WITHIN the narration stage, multiple Chatterbox worker processes MAY run concurrently, because a single autoregressive stream leaves the 4090 ~55% idle. The app sizes the worker count to the GPU's VRAM (each worker ~9-10 GB; 4090 -> 2 workers, 12 GB card -> 1, CPU/unknown -> 1), so it should make the most of whatever hardware it runs on. This supersedes the old "stages run sequentially, never concurrently; one stage owns the GPU" wording, which conflated same-stage parallelism with cross-stage overlap.

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

- server.py runs in BASE miniconda (stdlib + fitz + requests only, nothing installed). One worker thread runs the STAGES strictly sequentially, so Ollama extraction and Chatterbox narration never share the GPU. Within the narration stage it launches N parallel Chatterbox processes: narration_worker_count() reads total VRAM via nvidia-smi and returns clamp(1..MAX_WORKERS=4) of (VRAM - 1.5) / ~10 GB per worker; env AUDIOBOOK_NUM_WORKERS pins it, AUDIOBOOK_VRAM_PER_WORKER_GB tunes the budget. 4090 -> 2 workers.
- Parallel narration design: work is split by chunk index modulo N (disjoint, no coordination, still skips existing segments so resume-safe). Server flow: ensure_segments_fresh (wipes segments if blocks/voice/PLAN_VERSION changed, via plan_hash.txt) -> launch N `narrate_worker.py --shard K --num-shards N` -> wait all -> one `--assemble` pass (no model load). Progress is computed server-side by counting segments/seg_*.wav vs plan_total.txt (aggregates across workers). Expected ~1.8x on the 4090 with 2 workers (fills the ~45% idle a single stream leaves); verify against a real 2-worker run before quoting a firm number.
- pipeline_text.py: shared tagging/extraction. Carries the verified page-number filter plus: headings may end in ? or !, markdown emphasis stripped, whitespace collapsed, cross-page mid-sentence stitching, Path A prose mode (path_a.py x-indent rule, font-size-based drop-cap merge) and verse mode (sentence-run grouping), auto-detected by capitalized-line-start fraction (>0.45 = verse). HEADING_LINE_RE detects chapter divisions numbered as digits, roman numerals, OR spelled-out words ("Chapter One", "Chapter Twenty-One") plus standalone Prologue/Epilogue/Introduction/Preface/Foreword/Afterword; all-caps short lines are still headings via is_heading (this can catch rare in-story all-caps like "DANGEROUS", which get a heading pause but are NOT chapters since the worker's CHAPTER_RE only marks division words).
- narrate_worker.py runs in the chatterbox env as a subprocess. Per-chunk WAV segments make narration resumable. Output is ONE single file, DEFAULT m4b, chosen by config["format"] (m4b | mp3 | wav). m4b/mp3 are encoded by streaming raw PCM straight into ffmpeg (no giant intermediate WAV) at 64k AAC/MP3, mono 24kHz. m4b/mp3 carry navigable CHAPTERS: one per top-level heading (CHAPTER_RE = BOOK/CHAPTER/PART/CANTO/PROLOGUE/EPILOGUE/INTRODUCTION/PREFACE), written via an ffmetadata file; sub-section headings are not chapters. wav is the lossless master and is the only format that can split (only if it would top the ~4 GB WAV cap, ~22+ hr book; fallback_part_minutes default 240). ffmpeg is required for m4b/mp3 (chocolatey install present; find_ffmpeg falls back to that path).
- Jobs live in app\jobs\<id>\ (state.json, pages\, segments\, output\, log.txt). Path B caches per-page OCR .md so extraction also resumes. Finished parts are also copied to D:\Audiobook_Pipeline\audiobooks\<title>\.
- GLM-OCR degenerates on full-page ARTWORK pages (endless code fences, empty HTML tables, or looped short tokens). Guards in pipeline_text.tag_blocks: markup-only and code-fence lines dropped, consecutive duplicate body blocks collapsed, and any page whose blocks are >=20 with <30% unique text returns empty (art page). ocr_page caps num_predict at 4096. narrate_worker fingerprints the chunk plan and wipes stale segments if blocks change.
- Voice cloning: users can upload a voice sample in the UI (wav/mp3/flac/ogg, converted via convert_voice.py in the chatterbox env, soundfile only, trimmed to 20s) and pick a voice per job. Default voice is samples\Voice_Sample\male_ref.wav ("Default narrator (male sample)"). The rights rule above applies to uploads.
- Repo cleaned 2026-07-21 for GitHub: deleted audio_raw\, extracted\, narration_input\, harvest_output\, image_samples\, one-off run_*/inspect_* scripts and glm_* artifacts, and the 7 redundant single-page L_D_M PDFs (full book kept). git init done, no commits yet; .gitignore excludes all PDFs/audio/jobs so only code and docs (15 files) are tracked. README.md added.
- Design decisions applied (were open threads 3/4): CHECKLIST FOR X sections get normal heading treatment; epigraphs stay plain body.
- Verified end to end 2026-07-21: 1-page Path B job produced 53.7s of real narrated audio through the UI. Full Odyssey extraction dry-run: verse mode, 4465 blocks, all 24 Book headings detected.

## Book-specific notes

- Return of the Lazy Dungeon Master (samples\L_D_M): 88 pages, Path B. COMPLETE 2026-07-21: 3.62 hours, single file at audiobooks\Return of the Lazy Dungeon Master\. ffmpeg (chocolatey) is available on this machine for lossless concat / future m4b/mp3 encoding.
- The Odyssey (samples\The Odyssey): 793 pages, Path A verse. The poem is pages 78 to 610; pages 1-77 are front matter and 611+ are notes/commentary, so create the job with that range. Roughly 14 hours of audio.
- PHM (samples\Novel sample): 523 pages, Path A prose, was the checkpoint 1 test book.
- The Power of the Dog - Don Winslow (source_pdfs): 818 pages, Path A prose. Novel proper is pages 5 to 818 (p1 cover, p2 title/dedication, p3 synopsis blurb, p4 Psalm epigraph, p5 Prologue, THE END on p818). User chose to start at the Prologue (page 5). m4b job started 2026-07-22, default male voice; 16 chapters (Prologue, Chapter One..Fourteen, Epilogue), ~18-20 h of audio. Chapter headings are spelled-out ("Chapter One"), which is why HEADING_LINE_RE had to grow spelled-out-number support.
