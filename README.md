# Audiobook Pipeline

Local PDF to audiobook pipeline for legally purchased books, personal use only. Runs entirely on my own hardware (RTX 4090, Windows): OCR and text extraction feed a tagging stage, then Chatterbox TTS narrates with a cloned voice.

## What's here

- `app/` — Audiobook Studio, a local web app wrapping the whole pipeline.
  - `server.py` — stdlib HTTP server + job queue (base conda env). UI at http://localhost:8765. Runs every stage strictly sequentially so the OCR model and the TTS model never share the GPU.
  - `pipeline_text.py` — extraction and tagging. Path A: text-layer PDFs (prose via x-indent paragraphing, verse via sentence-run grouping, auto-detected). Path B: PyMuPDF rasterize, GLM-OCR via Ollama, block tagging (headings, dialogue, tables and data lists become short spoken omission markers).
  - `narrate_worker.py` — Chatterbox narration subprocess (chatterbox conda env). Per-chunk WAV checkpoints make multi-hour narrations resumable; output is a single file, default **m4b with navigable chapters** (one per top-level heading), or mp3 / lossless wav. m4b/mp3 are encoded straight from the segments via ffmpeg.
  - `convert_voice.py` — converts an uploaded voice sample (wav/mp3/flac/ogg) to a mono reference WAV for cloning.
  - `static/index.html` — the UI: library, jobs with live progress, voice upload and per-job voice selection.
- `samples/` — the validated standalone scripts the app grew out of (`path_a.py`, `stage_two.py`, `harvest_lazy_dm.py`, `chunk_and_narrate.py`, `narrate_tagged.py`) and the Ollama `Modelfile` for the tuned `glm-ocr-doc` model.
- `CLAUDE.md` — standing rules and current validated state of the project.
- `Start_Audiobook_Studio.bat` — one-click launcher; opens the app in its own window (falls back to your browser if that fails).
- `install/AudiobookStudio.iss` — Inno Setup script that builds a single `Setup_AudiobookStudio.exe` (see Install below). Build it with `install\build_installer.bat`, which stages a clean copy of the repo with `git archive` first so only tracked files can be packaged.

Books (PDFs), audio, and generated jobs are gitignored; only code and docs are tracked.

## Requirements

You provide these; the installer sets up everything else, including Miniconda and ffmpeg if you don't already have them.

- **Windows** with an **NVIDIA GPU**, roughly **6 GB+ VRAM** (built on a 24 GB RTX 4090). This is a hard requirement for narration: the TTS model runs on CUDA, so a Mac, an AMD card, or integrated graphics **cannot generate audio**. Text extraction alone works without a GPU. Nothing can auto-install a GPU or its driver; if you don't have one, the installer will tell you clearly rather than fail partway through.
- Roughly **15 GB of free disk**: about 10 GB for the Python environment and TTS models, plus a few GB of headroom for the audio you generate.
- **Your own** reference voice clip and books. The default voice sample is **not** shipped (see below), and PDFs are never included.
- Optional: **Ollama** with the `glm-ocr-doc` model, only for scanned-image books (Path B):
  ```
  ollama pull glm-ocr
  ollama create glm-ocr-doc -f samples/Modelfile
  ```

## Install

**Easiest: `Setup_AudiobookStudio.exe`.** One installer, no terminal. It silently installs Miniconda and ffmpeg if you don't already have them, builds the app's Python environment, and pre-downloads the ~3 GB of TTS model weights so the first narration doesn't have to. Double-click it, click through the wizard, and it's done — a shortcut is added to your Start Menu (and Desktop, if you check that box). This installer is built from source with Inno Setup (see `install/AudiobookStudio.iss`) rather than distributed as a signed release, so Windows SmartScreen may warn that it's from an unknown publisher the first time; that's expected for an unsigned personal-project installer, not a sign anything is wrong.

If the install fails or the wizard shows a warning box, everything it did is logged to `install_log.txt` in the install folder (usually `%LOCALAPPDATA%\Programs\Audiobook Studio`). Send that file. You can retry the environment build without reinstalling by running `setup.bat` from that same folder.

**From source, for development or if you'd rather see what's happening:**

```
setup.bat
```

This checks your prerequisites (conda, GPU, ffmpeg, Ollama) and reports what's missing rather than installing it automatically. It then builds the two conda environments the app needs, pinned to known-good versions (Python 3.11, torch 2.6.0+cu124, chatterbox-tts 0.1.7, transformers 5.2.0 from `install/requirements-chatterbox.txt`). It is safe to re-run, and it never modifies Ollama.

Useful flags (all combinable): `--check-only` (report only, install nothing), `--auto-install-conda` (silently install Miniconda if missing), `--auto-install-ffmpeg` (fetch a static ffmpeg build into `tools\` if missing), `--prefetch-weights` (download the TTS weights now instead of on first narration), `--yes` (don't prompt).

## Configure (optional)

The app auto-detects your conda env and defaults every path relative to the repo, so it usually runs with no config. To override anything (folders, port, the chatterbox python), copy `app/config.example.json` to `app/config.json` and edit it. Settings can also come from environment variables. `app/config.json` is gitignored.

## Provide a voice and books

- **Voice:** the default narrator clip is not distributed. Upload your own in the UI (wav/mp3/flac/ogg), or drop a clip at `samples/Voice_Sample/male_ref.wav`. Per the project rule, a cloned voice must be **licensed, synthetic, or royalty-free** — not a real identifiable person without rights.
- **Books:** put PDFs of books you legally own under `samples/` or `source_pdfs/` (or set your own `library_roots` in config).

## Run

Double-click `Start_Audiobook_Studio.bat` (or the Start Menu / Desktop shortcut if you used the installer). It opens Audiobook Studio in its own window — no browser tab, no address bar. Pick a PDF, choose pipeline/voice/page range, and start the job.

**First narration only, if you skipped the pre-fetch step above:** Chatterbox downloads about 3 GB of model weights with no progress bar. It can look frozen for several minutes; let it run. Later runs are fast, since the weights are cached.

## Narration engines

Two narrators are available, selectable per job (default `batched`):

- **`batched`** — generates several text chunks in one GPU pass. Much faster than the parallel engine on short/medium chunks; a VRAM budget keeps it from exceeding your card on long chunks. Verified to produce audio equivalent to the parallel engine.
- **`parallel`** — the original one-chunk-at-a-time engine, run in several processes. Kept as a fallback (`v1-parallel` tag).

Set the default with the `AUDIOBOOK_ENGINE` environment variable, or per job in the UI.
