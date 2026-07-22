# Audiobook Pipeline

Local PDF to audiobook pipeline for legally purchased books, personal use only. Runs entirely on my own hardware (RTX 4090, Windows): OCR and text extraction feed a tagging stage, then Chatterbox TTS narrates with a cloned voice.

## What's here

- `app/` — Audiobook Studio, a local web app wrapping the whole pipeline.
  - `server.py` — stdlib HTTP server + job queue (base conda env). UI at http://localhost:8765. Runs every stage strictly sequentially so the OCR model and the TTS model never share the GPU.
  - `pipeline_text.py` — extraction and tagging. Path A: text-layer PDFs (prose via x-indent paragraphing, verse via sentence-run grouping, auto-detected). Path B: PyMuPDF rasterize, GLM-OCR via Ollama, block tagging (headings, dialogue, tables and data lists become short spoken omission markers).
  - `narrate_worker.py` — Chatterbox narration subprocess (chatterbox conda env). Per-chunk WAV checkpoints make multi-hour narrations resumable; output is assembled into ~60 minute parts.
  - `convert_voice.py` — converts an uploaded voice sample (wav/mp3/flac/ogg) to a mono reference WAV for cloning.
  - `static/index.html` — the UI: library, jobs with live progress, voice upload and per-job voice selection.
- `samples/` — the validated standalone scripts the app grew out of (`path_a.py`, `stage_two.py`, `harvest_lazy_dm.py`, `chunk_and_narrate.py`, `narrate_tagged.py`) and the Ollama `Modelfile` for the tuned `glm-ocr-doc` model.
- `CLAUDE.md` — standing rules and current validated state of the project.
- `Start_Audiobook_Studio.bat` — one-click launcher.

Books (PDFs), audio, and generated jobs are gitignored; only code and docs are tracked.

## Requirements

- Windows, NVIDIA GPU with enough VRAM for the models (built on a 24 GB RTX 4090)
- Ollama with the `glm-ocr-doc` model (`ollama create glm-ocr-doc -f samples/Modelfile`)
- A conda env `chatterbox` (Python 3.11, torch + chatterbox-tts + soundfile)
- Base Python with PyMuPDF and requests for the server
- A reference voice clip at `samples/Voice_Sample/male_ref.wav` (licensed, synthetic, or royalty free only), or upload one in the UI

## Run

Double-click `Start_Audiobook_Studio.bat`, or:

```
python app/server.py
```

then open http://localhost:8765, pick a PDF from the library, choose pipeline, voice, and page range, and start the job.
