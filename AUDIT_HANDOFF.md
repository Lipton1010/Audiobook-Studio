# Audit handoff: pre-demo review of Audiobook Studio installer changes

## What this project is

A local, personal PDF-to-audiobook pipeline (OCR extraction + Chatterbox TTS narration) that runs entirely on the owner's own Windows machine (RTX 4090, conda). Repo: https://github.com/Lipton1010/Audiobook-Studio (public). Local copy: `D:\Audiobook_Pipeline`. Full standing rules and validated project history are in `CLAUDE.md` at the repo root — read that first, it is the authoritative source of truth for what's been built and tested so far, not this document.

## Why you're being asked to look at this

The owner wants to demo this to a friend and have the friend install it on their own Windows machine. The friend is not a developer. Two things were just built to make that possible:

1. A one-click installer (`install/AudiobookStudio.iss`, compiled with Inno Setup into `Setup_AudiobookStudio.exe`) that silently installs Miniconda and ffmpeg if missing, builds the app's conda environments, and pre-downloads the TTS model weights.
2. A native desktop launcher (`app/launcher.py`, invoked by `Start_Audiobook_Studio.bat`) that opens the app in its own window via `pywebview` instead of a browser tab.

**Critical constraint: none of this has been run on a real machine yet.** It was written by an AI assistant (a different Claude session) with no access to Windows, conda, GPU hardware, or Inno Setup — it was reasoned through against documentation and verified only by static means (Python syntax compilation, reading the actual Chatterbox source to confirm API assumptions, manual tracing of control flow). It has NOT been compiled with Inno Setup, NOT been run on a clean Windows machine, and NOT been tested against a real conda/GPU environment. Treat every claim of "should work" as unverified until you can show otherwise or flag it clearly as still-unverified.

The single commit that added all of this is `f9e04ad` ("inno launcher"), already pushed to `origin/master`. Diff it directly:

```
git show f9e04ad
```

or browse it on GitHub: https://github.com/Lipton1010/Audiobook-Studio/commit/f9e04ad

## Known non-issue, don't waste time on it

If you run `git diff` or `git status` against a *local* working copy at `D:\Audiobook_Pipeline` (as opposed to a fresh `git clone`), you may see almost every file in the repo showing as modified with equal insertions/deletions (e.g. `app/server.py` showing 964/964 changed lines). This is CRLF line-ending drift from the sandbox filesystem that produced these files, not real content changes — confirmed by stripping `\r` and md5-summing both sides, which match exactly. **Work from a fresh `git clone` of the GitHub repo, or from `git show f9e04ad` / the GitHub commit view, not from the raw working tree**, so you don't burn review budget on phantom diffs.

## Files to focus on (all new or changed in f9e04ad)

New files, never run:
- `app/launcher.py` — desktop window entry point
- `app/icon.ico` — generated placeholder icon (6 resolutions embedded; cosmetic only, not a logic concern)
- `install/AudiobookStudio.iss` — Inno Setup script, **never compiled**
- `install/bootstrap_conda.py` — silent Miniconda installer (Python)
- `install/bootstrap_ffmpeg.py` — static ffmpeg fetch (Python)
- `install/bootstrap_weights.py` — Chatterbox weights pre-fetch (Python)

Modified files, changes should be small and additive (diff each against its parent commit to confirm nothing else shifted):
- `Start_Audiobook_Studio.bat` — now launches `launcher.py` instead of opening a browser
- `setup.py` — added `--auto-install-conda`, `--auto-install-ffmpeg`, `--prefetch-weights` flags
- `app/config.py` — ffmpeg detection now also checks `tools\ffmpeg.exe`
- `app/narrate_worker.py` — same ffmpeg path addition in `find_ffmpeg()`
- `install/requirements-base.txt` — added `pywebview==5.4`
- `README.md`, `CLAUDE.md`, `.gitignore` — documentation and ignore-list updates

## Specific things to verify or attack

Please don't just skim for style. Actually trace these:

1. **`install/AudiobookStudio.iss` Pascal Script correctness.** This is Inno Setup's scripting language, not Python — nothing in this repo's CI or tooling checks its syntax. Look for: undefined identifiers, incorrect API usage against Inno Setup 6's documented `[Code]` functions (`DownloadTemporaryFile`, `Exec`, `ExpandConstant`, `WizardForm.StatusLabel`, `CurStepChanged`), whether `{tmp}`, `{app}`, `{%USERPROFILE}` constants are used correctly, and whether the `[Files]` `Excludes` glob syntax is valid Inno syntax. The `AppId` GUID was already caught as invalid once during self-review (was a fake non-hex string) and replaced — double check the current one is a real, well-formed GUID.

2. **The bootstrapping order-of-operations problem.** On a machine with zero Python and zero conda, `bootstrap_conda.py` (a Python script) cannot be the thing that installs Miniconda, because there's nothing to run it with yet. The `.iss` script is supposed to solve this by doing the Miniconda download+install directly in Pascal Script (see `EnsureCondaAvailable` / `InstallMinicondaViaInno` in the `[Code]` section) and only handing off to Python (`setup.py`) after conda exists. Verify this ordering is actually correct in the `[Run]` section — i.e. that nothing tries to invoke a Python script before `CurStepChanged`'s `ssPostInstall` handler has run and resolved `CondaPythonPath`.

3. **Silent install flag correctness.** `bootstrap_conda.py` and the Pascal Script version in the `.iss` both use `/InstallationType=JustMe /RegisterPython=0 /S /D=<path>` for the Miniconda NSIS installer. Confirm against current Anaconda/Miniconda documentation that these flags are still correct and that `/D=` still must be the last, unquoted argument. Flag if Anaconda has changed their silent-install contract since this was written.

4. **ffmpeg static build extraction logic** (`install/bootstrap_ffmpeg.py`). It downloads a zip from `https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip` and searches the archive for a member path ending in `bin/ffmpeg.exe`. Confirm this glob-style match is robust to however gyan.dev currently names their build folder (version numbers change), and that the LICENSE file detection logic doesn't silently no-op.

5. **`install/bootstrap_weights.py` correctness against the real Chatterbox API.** It calls `hf_hub_download(repo_id="ResembleAI/chatterbox", filename=...)` for exactly 5 files (`ve.safetensors, t3_cfg.safetensors, s3gen.safetensors, tokenizer.json, conds.pt`). This was checked against chatterbox-tts 0.1.7's actual `tts.py` source at the time, but confirm: (a) that pinned version is what `install/requirements-chatterbox.txt` still specifies, (b) the repo_id and filenames still match upstream on HuggingFace, (c) the HF cache location this populates (`~/.cache/huggingface` or `HF_HOME`) is genuinely the same cache `ChatterboxTTS.from_pretrained()` reads from at runtime, not a divergent path.

6. **`app/launcher.py` threading and shutdown behavior.** It runs `server.py`'s `main()` (a blocking `ThreadingHTTPServer.serve_forever()`) on a background daemon thread, then calls `webview.start()` on the main thread. Check: does closing the pywebview window actually terminate the process cleanly, or does the daemon thread orphan and leave a Python process bound to the port? Is there a cleanup/shutdown path at all, or does the user have to kill it from Task Manager? This matters for a "friend demoing it casually" use case where they'll just close the window when done.

7. **Fallback-to-browser path.** If `pywebview` import fails or `webview.start()` throws, `launcher.py` falls back to `webbrowser.open()` plus a `_block_forever()` loop. Confirm this fallback actually keeps the server thread alive and reachable, and that the error messages printed would be legible to a non-technical user reading a console window (or whether they'd even see a console window at all, given the `.bat` launches it).

8. **`[Files]` section exclude patterns in the `.iss`.** Confirm the `Excludes:` glob correctly keeps out `.git/`, `app/jobs/`, generated audio/PDFs, etc., matching `.gitignore`'s intent, so the installer doesn't accidentally bundle a stray large file or, worse, miss excluding something and ship copyrighted PDFs/audio if the owner's local folder happens to have any sitting around at build time. This is a real risk: Inno Setup packages whatever is in the source folder at build time, regardless of `.gitignore` (which only governs git, not the Inno Setup compiler).

9. **Version/pin drift.** `install/requirements-base.txt` added `pywebview==5.4`. Confirm this version still exists on PyPI and installs cleanly with the existing pins (`pymupdf==1.28.0`, `requests==2.33.1`) without dependency conflicts, and that `pythonnet` (pywebview's Windows backend dependency) doesn't have its own gotchas on Python versions this project's base env might be running.

10. **Anything else that looks wrong.** The above is what's known to be unverified going in; you may find additional bugs, race conditions, or bad assumptions not listed here. Prioritize anything that would cause the installer to silently fail, hang, or leave the friend's machine in a half-configured state with no clear error message — that's the actual demo-day risk, more than cosmetic issues.

## What "done" looks like for this audit

A list of concrete bugs or risks, each with: the file and line/section, why it's a problem, and (if possible) a suggested fix. Distinguish clearly between "this will definitely break" vs "this is unverified and should be tested before the demo" vs "this is a style/robustness nitpick, not blocking." The owner's own standing rule for this project is candor over agreement — don't soften a real problem to be polite, and don't invent problems to seem thorough either.

## What you do NOT need to re-litigate

The core pipeline (OCR extraction, chunking/tagging, Chatterbox narration, the batched narration engine) is already validated per `CLAUDE.md` and out of scope here unless the installer changes above somehow touch it (they shouldn't — `app/server.py`, `app/pipeline_text.py`, `app/batched_narrate.py` etc. were not modified in this commit). Stay focused on the installer/launcher surface area listed above.
