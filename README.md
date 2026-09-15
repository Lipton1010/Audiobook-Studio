# Audiobook Pipeline

[![Latest release](https://img.shields.io/github/v/release/Lipton1010/Audiobook-Studio?label=download&color=blue)](https://github.com/Lipton1010/Audiobook-Studio/releases/latest)

Local PDF to audiobook pipeline for legally purchased books, personal use only. Storybird runs extraction and narration locally. New jobs use VibeVoice 1.5B, with Chatterbox available for existing jobs and as a selectable fallback.

**Current source: 1.0.7. Current private beta installers: 1.0.6.** The 1.0.7 source is locally tested; no 1.0.7 installer has been built. See [1.0.7 changes and verification limits](RELEASE_1_0_7.md). The public Releases page may contain an older version than the private beta handoff.

In 1.0.7, selecting a voice imports it immediately, new audiobooks appear at the top of the main window, and additional books queue automatically. Right-click a finished book for artwork, export, regeneration, and deletion options. Advanced options include a restore-defaults button. Automatic performance overlaps the next passage's GPU generation with the current passage's CPU check while preserving quality gates and checkpoints.

## What's here

- `app/` — Audiobook Studio, a local web app wrapping the whole pipeline.
  - `server.py` — stdlib HTTP server + job queue (base conda env). UI at http://localhost:8765. Runs every stage strictly sequentially so the OCR model and the TTS model never share the GPU.
  - `pipeline_text.py` — extraction and tagging. Path A: text-layer PDFs (adaptive prose paragraphing uses first-line indents when present and vertical spacing otherwise; verse uses sentence-run grouping). Path B: PyMuPDF rasterize, GLM-OCR via Ollama, block tagging. Visual passages retain their extracted source and require review before narration. Both paths retain source-page provenance.
  - `visual_review.py` — saved visual treatments and the narration adaptation, kept separately from original extraction.
  - `narrate_worker.py` — Chatterbox narration subprocess (chatterbox conda env). Per-chunk WAV checkpoints make multi-hour narrations resumable; output is a single file, default **m4b with navigable chapters**, or mp3 / lossless wav. Chapter marks use detected top-level headings and fall back to accurately mapped PDF-outline entries when the outline is more complete. m4b/mp3 are encoded straight from the segments via ffmpeg.
  - `convert_voice.py` — converts an uploaded voice sample (wav/mp3/flac/ogg) to a mono reference WAV for cloning.
  - `static/index.html` — the UI: PDF import and library, jobs with live progress, voice upload and per-job voice selection. Completed jobs have an explicit audio download, an **Open output folder** button, safe segment-cache cleanup, and a compressed beta-test report containing the job and available setup logs.
- `samples/` — the validated standalone scripts the app grew out of (`path_a.py`, `stage_two.py`, `harvest_lazy_dm.py`, `chunk_and_narrate.py`, `narrate_tagged.py`) and the Ollama `Modelfile` for the tuned `glm-ocr-doc` model.
- `CLAUDE.md` — standing rules and current validated state of the project.
- `Start_Audiobook_Studio.bat` — one-click launcher; opens the app in its own window (falls back to your browser if that fails).
- `install/AudiobookStudio.iss` — Inno Setup script that builds a single `Setup_AudiobookStudio.exe` (see Install below). Build it with `install\build_installer.bat`, which stages a clean copy of the repo with `git archive` first so only tracked files can be packaged, then verifies the compiled installer against Inno's own `OutputManifestFile` and fails the build if any book, audio file, voice clip or local config got embedded. (Do not try to audit the .exe with 7-Zip; it cannot open an Inno-compiled installer.)

Books (PDFs), audio, and generated jobs are gitignored; only code and docs are tracked.

For development validation, run `python -m unittest discover -s tests -v`. Release builds must also satisfy `RELEASE_CHECKLIST.md`.

## Requirements

You provide these; the installer sets up everything else, including Miniconda and ffmpeg if you don't already have them.

- **Windows** with an **NVIDIA CUDA GPU**. VibeVoice 1.5B has been exercised on a 24 GB RTX 4090; smaller cards have not been validated by this project. Text extraction alone works without a GPU.
- The legacy Chatterbox setup requires roughly **15 GB free disk**. The new VibeVoice and CPU checker add separate environments and model weights; their complete fresh-install footprint has not yet been measured. Generated audiobooks require additional space.
- **Your own** reference voice clip and books. The default voice sample is **not** shipped (see below), and PDFs are never included.
- Optional: **Ollama** with the `glm-ocr-doc` model, only for scanned-image books (Path B):
  ```
  ollama pull glm-ocr
  ollama create glm-ocr-doc -f samples/Modelfile
  ```

## Install

**[Public release downloads](https://github.com/Lipton1010/Audiobook-Studio/releases/latest)** are separate from the private beta handoff. Check the version before installing. Installers are release assets, not committed source files. Development builds use `install\build_installer.bat` and must satisfy `RELEASE_CHECKLIST.md`.

The current private beta files are `Installer_AudiobookStudio_1.0.6.exe` for a new installation and `Patch_AudiobookStudio_1.0.6.exe` for an existing installation. Future handoffs use the same versioned naming pattern, without timestamp or hash suffixes. Superseded installers belong under `Old, do not use`. Build records identify source commits, sizes, and SHA-256 values; `RELEASE_CHECKLIST.md` determines release readiness. See [the beta handoff procedure](install/BETA_HANDOFF.md).

**Why the .exe is easiest.** One installer, no terminal. It installs a private Miniconda and ffmpeg, builds the app's Python environment, and pre-downloads the ~3 GB of TTS model weights so the first narration doesn't have to. The complete setup downloads several gigabytes and uses roughly 10 GB on disk, so have at least 15 GB free before starting. All large app-owned pieces are kept below the single Audiobook Studio installation folder instead of creating Miniconda and model-cache folders across your user profile. Double-click it, click through the wizard, and it's done — a shortcut is added to your Start Menu (and Desktop, if you check that box). Those shortcuts launch the app without showing a Command Prompt window. This installer is built from source with Inno Setup (see `install/AudiobookStudio.iss`) rather than distributed as a signed release, so Windows SmartScreen will probably warn that it's from an unknown publisher the first time. That's expected for an unsigned personal-project installer, not a sign anything is wrong. If you see a blue **"Windows protected your PC"** box, click **More info**, then **Run anyway**. If you were sent a SHA-256 alongside the file, you can confirm it first by running this in PowerShell:

```
Get-FileHash .\Setup_AudiobookStudio.exe -Algorithm SHA256
```

If the wizard warns that **ffmpeg** could not be installed, the install is still fine: the app opens, WAV narration works, and the job dialog has an **Install ffmpeg** button that fetches it in one click and then re-enables the m4b and mp3 options. Only m4b and mp3 need it.

If the Python environment build fails or the wizard shows a warning box, everything after Miniconda is logged to `install_log.txt` in the install folder (usually `%LOCALAPPDATA%\Programs\AudiobookStudio`). Send that file. A Miniconda failure happens before that log exists, so send the error-code screenshot instead. You can retry the environment build without reinstalling by running `setup.bat` from that same folder.

The one-click folder layout is intentionally self-contained: `runtime/` holds private Miniconda, the Chatterbox environment, package caches, and model weights; `source_pdfs/` holds PDFs waiting to be processed; `processed_pdfs/` keeps app-imported sources after their audiobook completes; and `app/jobs/`, `app/voices/`, and `audiobooks/` hold user data. Windows still keeps the normal Start Menu shortcut and uninstall registration in its own system-managed locations. A source checkout continues to use the developer's existing conda installation unless `--runtime-root` is supplied explicitly.

**From source, for development or if you'd rather see what's happening:**

```
setup.bat
```

This checks prerequisites, then prepares the base app dependencies plus separate VibeVoice and CPU speech-checking environments under `runtime/`. It downloads pinned VibeVoice 1.5B, tokenizer and speech-recognition weights before recording the verified paths. Existing unrelated environments and Ollama are not modified. Use `python setup.py --narrator chatterbox` to prepare the legacy narrator instead.

Useful flags (all combinable): `--check-only` (report only, install nothing), `--auto-install-conda` (silently install Miniconda if missing), `--auto-install-ffmpeg` (fetch a static ffmpeg build into `tools\` if missing), `--prefetch-weights` (download the TTS weights now instead of on first narration), `--yes` (don't prompt).

## Configure (optional)

The app auto-detects your conda env and defaults every path relative to the repo, so it usually runs with no config. To override anything (folders, port, the chatterbox python), copy `app/config.example.json` to `app/config.json` and edit it. Settings can also come from environment variables. `app/config.json` is gitignored.

## Provide a voice and books

- **Voice:** the default narrator clip is not distributed. Upload your own in the UI (wav/mp3/flac/ogg), or drop a clip at `samples/Voice_Sample/male_ref.wav`. Per the project rule, a cloned voice must be **licensed, synthetic, or royalty-free** — not a real identifiable person without rights.
- **Books:** click **Add PDF to library** in the app and choose a PDF you legally own. The app copies it into its managed `source_pdfs/` library. After the audiobook completes, that imported source moves to `processed_pdfs/` and leaves the active library; it is retained, not deleted. PDFs from `samples/` or another configured external `library_roots` folder are never moved.

## Run

Double-click `Start_Audiobook_Studio.bat` (or the Start Menu / Desktop shortcut if you used the installer). It opens Audiobook Studio in its own window — no browser tab, no address bar. Click **Add PDF to library**, choose **Create Audiobook**, review the recommended pipeline and starting page, then choose the voice, output format and page range.

**First narration only, if you skipped the pre-fetch step above:** Chatterbox downloads about 3 GB of model weights with no progress bar. It can look frozen for several minutes; let it run. Later runs are fast, since the weights are cached.

## Narration engines

New jobs default to **VibeVoice 1.5B**. Select **Chatterbox** in the job dialog when needed; jobs saved without a backend retain their legacy Chatterbox behavior. VibeVoice uses whole passages, native timing, and gain-only loudness adjustment. Its checkpoints and quality receipts are separate from Chatterbox's segment cache. The CPU speech checker rejects major missing or extra wording; it cannot certify pronunciation, naturalness, or the absence of every audible artifact.

To reuse an existing VibeVoice environment without modifying it, run `install/bootstrap_vibevoice.py --configure-existing` with `--python`, `--model-dir`, `--cache-dir`, `--quality-python`, and `--quality-model`. `--check-only` verifies the same supplied paths without writing configuration. See `app/config.example.json` for portable configuration keys. Fresh runtime installation and installer execution are separate checks from narration in a verified existing environment.

Storybird pauses after extraction when it flags visual passages. Select **Review narration text** to see each passage, nearby prose and its original PDF page when available. Choose **Keep as spoken text**, **Replace with a spoken description**, or **Skip: surrounding prose conveys it**. Save each treatment, open **Inspect final narration text**, then select **Start narration**. Saved treatments can be revisited from the job's controls.

Descriptions are manual adaptations, not automatic interpretations. Preserve important counts, changes, warnings and discovery order. If the graphic is missing, Storybird says so; do not reconstruct details absent from the source. Prose-only jobs continue through the ordinary workflow. See [visual review behavior and verification](VISUAL_REVIEW.md) for cached-job handling and test coverage.

Chatterbox has two execution modes (default `batched`):

- **`batched`** — generates several text chunks in one GPU pass. Much faster than the parallel engine on short/medium chunks; a VRAM budget keeps it from exceeding your card on long chunks. Verified to produce audio equivalent to the parallel engine.
- **`parallel`** — the original one-chunk-at-a-time engine, run in several processes. Kept as a fallback (`v1-parallel` tag).

Set the default with the `AUDIOBOOK_ENGINE` environment variable, or per job in the UI.
