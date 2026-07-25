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
- `Start_Audiobook_Studio.bat` — one-click launcher.

Books (PDFs), audio, and generated jobs are gitignored; only code and docs are tracked.

## Requirements

You provide these; the installer sets up everything else.

- **Windows** with an **NVIDIA GPU**, roughly **6 GB+ VRAM** (built on a 24 GB RTX 4090). This is a hard requirement for narration: the TTS model runs on CUDA, so a Mac, an AMD card, or integrated graphics **cannot generate audio**. Text extraction alone works without a GPU.
- **Miniconda** (or Anaconda) installed: https://docs.conda.io/en/latest/miniconda.html
- Roughly **10 GB of free disk** for the Python environment and the TTS models (models download on first narration).
- **ffmpeg** for `.m4b`/`.mp3` output with chapters and cover art. WAV works without it. Install from https://www.gyan.dev/ffmpeg/builds/ or `choco install ffmpeg`.
- **Your own** reference voice clip and books. The default voice sample is **not** shipped (see below), and PDFs are never included.
- Optional: **Ollama** with the `glm-ocr-doc` model, only for scanned-image books (Path B): `ollama create glm-ocr-doc -f samples/Modelfile`.

## Install

From the repo folder, run:

```
setup.bat
```

It checks your prerequisites (conda, GPU, ffmpeg, Ollama), then builds the two conda environments the app needs, pinned to known-good versions (Python 3.11, torch 2.6.0+cu124, chatterbox-tts 0.1.7, transformers 5.2.0 from `install/requirements-chatterbox.txt`). It is safe to re-run, and it never modifies Ollama. If anything is missing it tells you exactly what to install.

To only check prerequisites without installing: `python setup.py --check-only`.

## Configure (optional)

The app auto-detects your conda env and defaults every path relative to the repo, so it usually runs with no config. To override anything (folders, port, the chatterbox python), copy `app/config.example.json` to `app/config.json` and edit it. Settings can also come from environment variables. `app/config.json` is gitignored.

## Provide a voice and books

- **Voice:** the default narrator clip is not distributed. Upload your own in the UI (wav/mp3/flac/ogg), or drop a clip at `samples/Voice_Sample/male_ref.wav`. Per the project rule, a cloned voice must be **licensed, synthetic, or royalty-free** — not a real identifiable person without rights.
- **Books:** put PDFs of books you legally own under `samples/` or `source_pdfs/` (or set your own `library_roots` in config).

## Run

Double-click `Start_Audiobook_Studio.bat` (it finds your Python and opens the browser), then open http://localhost:8765, pick a PDF, choose pipeline/voice/page range, and start the job.

## Narration engines

Two narrators are available, selectable per job (default `batched`):

- **`batched`** — generates several text chunks in one GPU pass. Much faster than the parallel engine on short/medium chunks; a VRAM budget keeps it from exceeding your card on long chunks. Verified to produce audio equivalent to the parallel engine.
- **`parallel`** — the original one-chunk-at-a-time engine, run in several processes. Kept as a fallback (`v1-parallel` tag).

Set the default with the `AUDIOBOOK_ENGINE` environment variable, or per job in the UI.
