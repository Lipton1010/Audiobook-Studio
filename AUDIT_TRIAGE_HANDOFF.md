# Handoff: triage and fix audit findings on the Audiobook Studio installer

## Context

This is a personal, local PDF-to-audiobook pipeline (OCR extraction + Chatterbox TTS narration), built and run entirely on the owner's own Windows machine (RTX 4090, conda). Repo: https://github.com/Lipton1010/Audiobook-Studio (public). Local copy: `D:\Audiobook_Pipeline`. `CLAUDE.md` at the repo root is the authoritative standing-rules and validated-state document for this whole project — read it before touching anything, it explains hardware constraints, environment isolation rules, the hard "never upgrade Ollama" rule, and what has and hasn't been verified so far.

The owner wants to demo this to a friend, who will install it on their own Windows machine. Since neither the owner nor the assistant building this has access to a second Windows/GPU machine to test on, a prior session had multiple other models independently audit a specific set of new changes for bugs before anything gets sent out. **That audit already ran and the results are being pasted into this conversation next.** Your job starts once you have those results in front of you.

## What was audited

A single commit, `f9e04ad` ("inno launcher"), already pushed to `origin/master` on GitHub. It added a one-click Windows installer and a native desktop window, on top of an existing, already-validated pipeline. Specifically:

- `install/AudiobookStudio.iss` — Inno Setup script, compiles into `Setup_AudiobookStudio.exe`. Silently installs Miniconda (if missing) via Pascal Script, then hands off to Python for the rest.
- `install/bootstrap_conda.py` — standalone silent Miniconda installer (Python), used by `setup.py` directly, and mirrored (not called) in Pascal Script inside the `.iss` for the case where no Python exists yet.
- `install/bootstrap_ffmpeg.py` — fetches a static ffmpeg build (gyan.dev) into `tools\`, no PATH edit, no admin.
- `install/bootstrap_weights.py` — pre-downloads Chatterbox's ~3 GB of TTS weights via `hf_hub_download`, no CUDA/inference involved.
- `app/launcher.py` — new desktop entry point; runs `server.py`'s HTTP server on a background thread, opens a native window via `pywebview` instead of a browser tab, falls back to `webbrowser.open()` if `pywebview`/WebView2 aren't available.
- `app/icon.ico` — generated placeholder icon, cosmetic only.
- Small, additive edits to `Start_Audiobook_Studio.bat`, `setup.py` (new `--auto-install-conda` / `--auto-install-ffmpeg` / `--prefetch-weights` flags), `app/config.py` and `app/narrate_worker.py` (both now also check `tools\ffmpeg.exe` for a bundled ffmpeg), `install/requirements-base.txt` (added `pywebview==5.4`), plus README/CLAUDE.md/`.gitignore` doc updates.

**None of this had been run on a real Windows machine, real conda environment, or compiled with Inno Setup at the time it was written** — it was reasoned through against documentation and verified only statically (Python syntax compilation, reading the actual Chatterbox source to confirm API assumptions, manual control-flow tracing). The audit's job was to catch what that static review couldn't.

The full audit brief the other models worked from is `D:\Audiobook_Pipeline\AUDIT_HANDOFF.md` if you want the original ask in detail — it lists 10 specific areas of concern (Pascal Script correctness in the `.iss`, the bootstrapping chicken-and-egg problem of installing conda before any Python exists, silent-install flag correctness, ffmpeg zip extraction robustness, HF cache path correctness, launcher thread/shutdown behavior, the browser-fallback path, installer `[Files]` exclude correctness, and dependency version drift).

## Your job

1. Read the pasted audit results carefully. Multiple models ran this independently, so expect overlap, some disagreement, and possibly some false positives — models auditing Pascal Script and Inno Setup mechanics without being able to run the compiler themselves may guess wrong on niche syntax.
2. Triage every finding into: **definitely broken** (fix it), **plausible risk worth hardening** (fix if cheap, otherwise flag clearly to the owner), or **false positive / not actually a problem** (explain why you're dismissing it, don't just drop it silently).
3. For anything you fix, make the actual edit to the real files in `D:\Audiobook_Pipeline` (Read the current file first, then Edit — don't just describe the fix). Files most likely to need changes: `install/AudiobookStudio.iss`, `install/bootstrap_conda.py`, `install/bootstrap_ffmpeg.py`, `install/bootstrap_weights.py`, `app/launcher.py`.
4. Update `CLAUDE.md`'s "One-click installer" section (search for `## One-click installer` — it already documents this feature and explicitly flags it as unverified) to record what the audit caught and what you fixed, following the project's own established pattern of that file: candid, dated, specific about what changed and why, no marketing language. This project's standing rule is to keep that file as the authoritative running log — don't let it go stale.
5. Do NOT touch the validated pipeline code (`app/server.py`, `app/pipeline_text.py`, `app/batched_narrate.py`, `app/narrate_worker.py`'s narration logic, etc.) unless a finding specifically and correctly implicates one of the small edits made to `app/config.py` or `app/narrate_worker.py`'s `find_ffmpeg()` in the audited commit. Everything else in the pipeline is out of scope and already trusted.
6. This installer still cannot be compiled or run in this environment (no Windows, no Inno Setup, no conda, no GPU available here either). Be explicit in your final summary about what you fixed via static reasoning versus what genuinely still needs a real Windows test run before the owner sends anything to their friend. Don't claim something is "fixed and verified" if all you did was reason about it.
7. Once done, give the owner a plain-language punch list: what got fixed, what's still a real risk, and what specifically they should watch for when they finally do run `Setup_AudiobookStudio.exe` on a real machine (their own, or their friend's).

## Working style for this project (from CLAUDE.md, applies here too)

Candid tone, tell the owner directly if something is a bad idea or won't work, don't just agree. No dashes in any output meant for the owner to copy and paste. Give exact commands. Don't assume a fix works from pattern-matching alone if there's a way to actually verify it (even a partial static check, like re-running `python -m py_compile` on anything you touch).

The audit results are being pasted in as the next message.
