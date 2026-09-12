# PROJECT_STATE.md

Last audited: 2026-09-08, America/New_York. Storage inventories retain their explicitly dated September 4 measurements.

Audited checkout: `D:\Audiobook_Pipeline`, branch `master`, commit `8e4f73ee0fa96f9144a0bd3d47bc2e861f0b6c0f`. App version: `1.0.2`.

Latest narration verdict and continuation handoff: 2026-09-09. The active next-chat entry point is `HANDOFF_NEXT_SESSION.md`, with a copyable prompt in `HANDOFF_START_PROMPT.md`. These ignored local files and the audition evidence require the existing checkout, not a fresh worktree. Sections 23 through 29 distinguish the recent authorized experiments from the original audit roadmap.

Overall audit confidence: **Confirmed** for inspected source, Git refs, local file inventory and checks executed below; **Likely** for reconstructed product priorities; **Unclear** for the exact installed experience on other hardware and owner acceptance of the experimental product direction.

This is the canonical current-state assessment and roadmap, not permission to execute it. Read `AGENTS.md` and `CLAUDE.md` for standing instructions. This assessment reconciles their historical claims with observed reality without changing those instructions. Detailed chronological records remain under `.claude/skills/`. Update this document when material evidence changes rather than appending a session diary.

Initial audit scope: tracked source, configuration, UI, tests, installer designs, relevant installer and beta records, Git history and live remote refs, job/output metadata, and specifically referenced environments/model caches. The initial audit performed no feature implementation, cleanup, environment installation, release build, inference run, history rewrite, push, or publication. Paul subsequently authorized the isolated Breeze/Qwen audition and stale-file cleanup recorded in section 23. Ollama was initially stopped; it was started as a hidden service with Paul's authorization and left running with no model resident. Private book passages, voice content and credential values are deliberately absent from this document.

## 1. Project Summary

Audiobook Studio converts personally owned PDFs into locally generated audiobooks on Windows with an NVIDIA GPU. It combines PDF text extraction or OCR, narration-oriented text structure, cloned-reference Chatterbox speech, resumable segment generation and chaptered audio assembly behind a local UI.

**Confirmed:** This is beyond a prototype. Six completed historical jobs, real M4B containers, a working HTTP/UI source path, an isolated CUDA-capable narration environment, and 50 passing regression tests exist. It is still a private beta with incomplete release validation. The current local stabilization changes have not reached remote `master`.

The main gap is reliable operation and delivery on another person's machine. More narration features are not the immediate prerequisite for closing that gap.

## 2. Product Vision

**Likely:** The core product is a personal Windows audiobook appliance that a nontechnical owner or friend can install, feed a PDF and voice sample, and use without managing Python, segmentation or audio encoding manually.

Two directions coexist:

1. `master`: reliable single-narrator PDF conversion and a usable installer.
2. `codex/v1.1_character_discovery`: optional local character discovery, editable casting and multiple voices for prose novels.

The second is real experimental implementation, not merely a proposed feature, but is absent from the current checkout. Whether it defines the eventual finished product is **Unclear**. Do not silently treat that branch as either approved release scope or disposable clutter.

## 3. Intended User / Problem Solved

The initial user is Paul, with a 24 GB RTX 4090 desktop. Outside beta evidence includes an HP Omen with a 12 GB RTX 3060 and Brandon with a 16 GB RTX 4090 Laptop GPU. The July HP Omen record reports completed Shining/Sphere jobs, but not accepted listening quality or exact current-build validation. The later 16 GB OOM therefore does not establish a 16 GB minimum or show that smaller cards cannot finish; hardware support depends on workload, runtime and recovery as well as total VRAM. They want listenable, navigable personal audiobooks from purchased PDFs without running a collection of model scripts.

Novel prose, verse and designed reference books are materially different input classes. Reliable text preservation, correct starting pages, reading order, chapter navigation and acceptable listening quality matter more than raw GPU utilization.

## 4. Finished Product Description

The intended application opens from a Windows shortcut into a native window, with browser fallback. It presents a PDF library, voice catalog and persistent job cards.

The complete workflow is:

1. Install prerequisites and models into the managed application runtime, with actionable setup diagnostics.
2. Import a PDF and provide a permitted reference voice sample.
3. Review recommended extraction route and physical PDF page range, then choose voice and output format.
4. Extract faithful body text/headings while excluding recurring boilerplate, captions and unsuitable tables; preserve source provenance.
5. Narrate with visible progress, bounded failure recovery, cancellation and resume.
6. Assemble a complete audiobook with usable chapter marks and metadata.
7. Save audio, open its folder, inspect diagnostics when needed and explicitly reclaim resumable segment storage.

Inputs are PDFs, a selected physical page range, voice audio and job settings. Outputs are normally one M4B, optionally MP3 or WAV; very large WAV output can split. Local intermediates include source metadata, OCR page caches, blocks, plans, logs and segment WAVs. App-imported sources move to `processed_pdfs/` after successful delivery; configured external library sources are retained in place.

Expected deployment is a per-user Windows installation with private Miniconda/runtime/cache folders. Source development uses Paul's existing conda installation. This is not a hosted website or an authenticated multiuser service.

## 5. Definition of Prototype Done

**Met historically:** A short owned or synthetic PDF can be extracted, narrated with a reference voice and assembled into intelligible audio on the developer's machine. Historical records include real Path B UI output and full-book runs. Today's audit confirmed retained containers and infrastructure, but did not generate new speech or reassess intelligibility.

## 6. Definition of MVP Done

**Not fully met as a transferable product.** One supported Windows/NVIDIA configuration outside the development environment must complete installation, voice setup, PDF import, short narration, download and chapter navigation without developer intervention. Errors must be readable; cancel, resume and shutdown must preserve user data and control only owned processes.

Both supported extraction routes need representative validation. At minimum, document which novel, verse and complex-layout cases are supported instead of promising arbitrary PDF fidelity. A supported hardware floor must be measured, not inferred from the desktop GPU.

## 7. Definition of Useful/Operational Done

Multiple representative books complete with acceptable opening text, paragraph structure, omission behavior, speech and navigation. A user can recover from interruption without accidental reuse of stale extraction or needless full regeneration. Storage requirements are visible and cleanup is deliberate. Exact installer provenance and support diagnostics are trustworthy.

**Partially met for Paul; unproven for general beta use.** Long local runs exist, but a field OOM exposed a missed exception form, installed downloads needed correction, and the historical listening reports include unacceptable narration. Successful encoding is not equivalent to a satisfactory audiobook.

## 8. Long-Term / Final Vision

**Likely:** A dependable local personal audiobook tool, potentially with optional reviewed character casting and multivoice narration after the core is stable. Scene/section-aware timing is a plausible listening improvement, supported by the documented pause analysis, but remains unimplemented in `master`.

Out of current scope: cloud narration, automatic silent updates, commercial audiobook distribution, general document editing, EPUB ingestion, macOS/AMD/CPU narration support, unrelated transcription environments and model-training infrastructure. These are not established requirements. Do not expand scope merely because a model or framework is available.

## 9. Current State

| Area | Assessment | Evidence and limit |
| --- | --- | --- |
| Main application | Confirmed implemented | `app/server.py`, `app/static/index.html`, `app/launcher.py`; local HTTP root returned 200 |
| Path A extraction | Confirmed basic execution | Real PyMuPDF synthetic input preserved both audit sentences and page provenance; small sample selected verse mode, so this is not a prose-classification proof |
| Path B extraction | Implemented; historical real proof | Server OCR orchestration, rasterization, page caching and tagging exist; Ollama was restarted and both GLM models are listed, but no fresh OCR performed |
| Chatterbox runtime | Confirmed locally operable prerequisites | Torch imports, CUDA available, key pins match, `pip check` passes; no model loaded for this audit |
| Completed output | Confirmed historical artifacts | Six done jobs, six readable AAC M4Bs, chapter counts and completion log markers |
| Failure stabilization | Confirmed regression coverage | Shared CUDA OOM classifier, ordered bisection, capped-row handling, process ownership and download handling |
| Installed 1.0.2 behavior | Unproven | Local candidate exists; exact-build physical/clean-machine gates remain unchecked |
| Experimental 1.1 | Separate implemented branch | Three unmerged feature commits; branch records describe synthetic model/UI/GPU proof, not accepted multivoice listening quality |

All six retained jobs lack `source_page` in their saved blocks. They cannot prove the new provenance-based outline fallback or the current OOM changes. Five retain 24,157 segment WAVs in total; the sixth has no segment cache.

## 10. What Demonstrably Works

Checks re-executed on 2026-09-08:

1. **50 tests passed**, zero failures or skips, using `C:\Users\paulm\miniconda3\python.exe`. The real Windows Job Object child-termination test ran. The suite also exercises live local HTTP HEAD responses for synthetic downloads, plus mocked/dependency-light logic for other features.
2. All **41 tracked Python files** parsed with `ast.parse`; the single embedded UI script parsed with Node's `vm.Script`.
3. A local `ThreadingHTTPServer` using the real handler served the actual UI: HTTP 200, 31,475 bytes. It did not start the production job loop or alter existing jobs.
4. A real in-memory PyMuPDF fixture passed through `extract_path_a`; both invented sentences survived, all three blocks retained page 1, and the heuristic selected verse. This is a small extraction smoke check, not a layout benchmark.
5. Chatterbox environment reports Python 3.11.15, torch/torchaudio 2.6.0+cu124, torchvision 0.21.0+cu124, numpy 1.26.4, chatterbox-tts 0.1.7, transformers 5.2.0, soundfile 0.14.0 and resemble-perth 1.0.1. CUDA 12.4 is available. `pip check`: no broken requirements.
6. `ffmpeg` executes successfully. `ffprobe` reads six existing M4Bs: mono AAC at 24 kHz, approximately 3.62 to 19.02 hours long, with 5, 30, 16, 16, 24 and 16 chapters in job-ID order. No fresh listening or chapter-player navigation was performed.
7. Current tracked source has no matches for the inspected Discord webhook endpoint pattern and no tracked PDF/audio extensions. This is a bounded scan, not a proof that every possible sensitive string is absent.

The standard command `C:\Users\paulm\miniconda3\python.exe -m unittest discover -s tests -v` passed all 50 tests in 1.703 seconds with approved filesystem access, without a custom temp-root runner. The first sandboxed attempt failed on temporary-fixture access before affected assertions, consistent with the September 4 sandbox limitation; it is not evidence of a product regression. Use the explicit base interpreter rather than the WindowsApps `python` alias.

Additional bounded checks: live remote hashes and candidate identity remain unchanged; all eight patch manifest hashes match CRLF-serialized HEAD content. An offline comparison established that both local configured and effective crash-report endpoints match the publicly embedded endpoint, without sending a request or printing its value. A direct synthetic chapter-helper check returned no mark for an outline destination at page 6 when audio first exists on page 7, while an interior page-8 destination with audio on pages 7 and 9 maps to page 9. This demonstrates the leading-boundary limitation described below; it is not an installed-player or full assembly test.

Follow-up synthetic failure checks on the same audited source exposed gaps outside the 50-test suite:

- A temporary real HTTP handler accepted an encoded parent-directory component in a voice-delete name and deleted a synthetic WAV outside its patched voices directory. The request also carried an unrelated `Origin`, which was not rejected. Only disposable test data was affected. This proves missing server-side path containment and origin rejection, not an end-to-end browser attack.
- The real `worker_loop`, with narration/reporting mocked and a synthetic `copy2` failure injected, deleted the prior library audio before the failed copy. The job became failed, the library had neither version, and the new job-local output survived.
- With an existing synthetic default sample and an absent named sample, `voice_wav_path` selected the default and `missing_voice_error` returned no error. No inference was run.
- One deliberately malformed synthetic `state.json` caused both `list_jobs` and `mark_interrupted_jobs` to raise, despite a second valid job. This proves a per-job read failure is not isolated from listing/startup recovery; it does not establish that ordinary writes currently corrupt records.

## 11. What Exists But Is Unproven or Fragile

1. **GPU recovery:** The classifier now accepts Brandon's exact `RuntimeError: CUDA error: out of memory` form. Bisection ordering and hard single-item failure have tests. Real recovery on his 16 GB laptop is still unverified. The initial batch budget is a linear estimate, not a measured hardware guarantee.
2. **OCR/TTS GPU handoff:** One worker serializes active pipeline calls, but `ocr_page` does not explicitly unload Ollama or set `keep_alive`, and the transition does not verify released OCR residency before starting TTS. This is a missing ownership safeguard, not proof of observed concurrent computation. Other local applications are outside this queue's control.
3. **Extraction cache identity:** `worker_loop` skips extraction whenever `blocks.json` exists. OCR caches are keyed by page filenames. Neither path automatically versions extraction implementation/model settings into cache validity. Resume after an extraction change can therefore retain old text. Segment hash safety does not repair an extraction that never reran.
4. **Chapter repair:** Current source preserves pages and maps outline destinations within the narrated-page interval; existing synthetic mapping tests pass. The broad first-audio-on-or-after claim needs a boundary caveat: `assembly_metadata.outline_chapter_marks` rejects destinations below the first narrated page. A selected decorative chapter opener on page 6 with first narration on page 7 therefore loses its outline mark. The helper receives no selected page range to distinguish this from a deliberately excluded earlier chapter. Direct synthetic execution confirmed this limitation; full assembly and installed-player impact remain untested. Existing blocks without provenance are a separate issue. Do not approximate old timestamps from page proportions.
5. **Narration quality:** T3 token equivalence and historical speed results do not establish waveform identity or universal listening quality. S3Gen is stochastic. Long-form OOM/capped-row recovery and voice quality need current-build real output checks.
6. **Native shell:** Base Python currently lacks pywebview. This checkout would take the documented browser fallback. The September 1 native-download proof used an isolated pywebview 5.4 test target, not this base installation or a validated 1.0.2 install.
7. **Packaging:** A patch checks only for an existing `app/server.py`; it does not establish a full minimum-compatible base version. Its eight-file list assumes other required modules and runtime already exist. Verify the actual target install before treating patch success as complete compatibility proof.
8. **Privacy boundaries:** Crash reporting is opt-in by default in current source, but both the local configured and effective endpoint still match the credential exposed in remote source, confirmed by offline comparison. No environment override was present and no request was sent to the endpoint. This establishes endpoint identity, not whether the provider has revoked it. Removing injection from a patch also does not remove an existing local setting. Reporting forwards exception text/title; beta ZIPs include full job state/logs and machine paths. An allowlist of filenames is not content redaction.


9. **Local HTTP trust boundary:** Binding to loopback does not validate callers or filenames. The voice-delete route decodes a user-controlled name and unlinks `VOICES_DIR / (name + ".wav")` without a resolved-path containment check. This escaped the voices directory in a synthetic HTTP test. The handler has no application-level Origin/Host validation or authorization for mutations. Browser/network restrictions were not tested, so remote-web exploitability remains unproven; the local deletion primitive is confirmed. Prioritize containment and a deliberate local-request policy before broader distribution.
10. **Delivery is not transactional:** Assembly deletes prior job-local audio before encoding, and library delivery deletes prior library audio before copying. An injected copy failure reproduced an empty library destination with a failed job, even though new job-local output survived. This is broader than title collisions: failure during an intended replacement can lose the prior delivered version. Validate disk-full/copy/cancel behavior and preserve accepted output until its replacement is verified.
11. **Selected voice is not a binding commitment:** Missing non-default voice names silently resolve to `REFERENCE_WAV`. This also passes job-creation preflight when the default exists. Deleting a selected voice while a job waits, or before resume, can therefore select a different narrator instead of requiring a decision. The fallback was directly reproduced; a wrong-voice audiobook was not generated. Distinguish an unspecified voice from an explicitly selected but unavailable one.
12. **A damaged job can affect the whole app:** `load_state` does not isolate JSON decoding failures; `list_jobs` and startup `mark_interrupted_jobs` propagate them. Both failed on one corrupt synthetic record. In addition, `worker_loop` loads state before its protected pipeline block, and its error handler writes a log without protecting against another write failure. Atomic/retried state writes are useful but do not establish fault isolation for malformed records or disk-full failures. Corrupt-state behavior was reproduced; actual disk exhaustion and worker-thread failure were not exercised.
13. **Diagnostics do not establish the actual runtime build:** `beta_test_report` includes base Python, machine/GPU details and job state, but does not explicitly capture app version/commit, patch/base provenance, Chatterbox package/model revisions or the job's effective worker configuration. Complete logs can help but are not a guaranteed build fingerprint. This leaves field failures harder to reproduce and mixed patch installations harder to identify. A documented acceptance sample set and machine-readable run identity should accompany physical validation.

## 12. What Is Broken / Missing

**Confirmed release blockers:** the voice-delete path escapes its intended directory; remote `master` still has the old credential-bearing installer source; local stabilization is unpublished to that branch; provider revocation is unconfirmed; exact-build installation/GPU/download/shutdown/player checks remain open.

**Confirmed documentation problems:** README says a VRAM budget keeps narration within the card, despite actual 16 GB OOM evidence. Its roughly 6 GB minimum is unvalidated. It describes optional OCR only for scanned books, while complex text-layer multicolumn books also require Path B. `CLAUDE.md` still contains superseded PID cleanup, single-branch and Fish environment claims alongside newer corrections. The suite now has 50 tests, not the latest narrative count of 48. `config.example.json` includes machine-specific example paths that must be edited, and detection still falls back to Paul's hardcoded Chatterbox interpreter.

**Confirmed implementation limitations:** no scene-break category on `master`; no automatic extraction-version invalidation; no explicit Ollama-to-TTS residency handoff; outline destinations before the first narrated page are discarded even when that page could be inside the selected extraction range. `worker_loop` derives library destinations from sanitized title and deletes existing audio in that directory before copying replacements. Distinct jobs whose titles map to the same directory can replace earlier library outputs. Job-local output may remain, but the library is not versioned.

No new audio-generation failure was reproduced during this audit. Do not label all untested behavior broken, or interpret a passing unit suite as full installation/extraction/listening proof.

## 13. Architecture

| Layer | Implementation |
| --- | --- |
| Launch | `Start_Audiobook_Studio.bat` resolves base Python and managed-runtime environment; `launcher.py` starts server and pywebview/browser shell |
| HTTP/UI | Loopback `127.0.0.1:8765`, stdlib threaded HTTP server, one HTML/JS UI with polling |
| Jobs | Filesystem JSON state, in-memory queue, one sequential pipeline worker; startup marks interrupted jobs |
| Extraction | `pipeline_text.py`: Path A geometry/text, rasterization and Markdown tagging; `server.py:run_extraction` owns Path B page caches/provenance and calls `server.py:ocr_page` for Ollama transcription |
| Narration | `narrate_worker.py` subprocess in isolated Chatterbox environment; `batched_narrate.py` batches token-length buckets in one process; parallel engine retained as fallback |
| Recovery | `gpu_oom.py`, `narration_safety.py`, versioned segment plan hashes, PID-unique temporary segments, live process handles and Windows Job Object |
| Assembly | `assembly_metadata.py`, segment streaming to ffmpeg, chapter metadata/cover embedding, optional WAV assembly |
| Delivery | Job-local output copied into audiobook library; imported PDF archived; explicit downloads, reports and completed-cache cleanup |
| Install | `setup.py`, bootstrappers, pinned manifests, full and patch Inno scripts, canonical `git archive HEAD` builder |

No external database, Ollama replacement, ComfyUI, training pipeline or hosted backend is required by `master`. The Cursor environment is a limited Linux development configuration; it does not establish a supported Linux narration product.

## 14. Data / Models / External Dependencies

Observed local dependencies. Runtime versions and availability below were rechecked September 8; environment/cache sizes and Fish residual inventory remain September 4 observations:

| Dependency | Current evidence / hidden state |
| --- | --- |
| Base interpreter | `C:\Users\paulm\miniconda3\python.exe`, Python 3.13.13; PyMuPDF 1.28.0 and requests 2.33.1 present; pywebview missing |
| Narration environment | `C:\Users\paulm\miniconda3\envs\chatterbox`, about 5.45 GiB logical file size; package check passes |
| Hardware | RTX 4090, 24,564 MiB reported total, driver 616.64; this is the developer machine, not the laptop |
| Voice/config | Ignored `app/config.json`, private `samples/Voice_Sample/male_ref.wav`, optional uploaded voices; a clone intentionally does not contain working personal samples |
| Chatterbox models | Hugging Face `ResembleAI/chatterbox`; five named files prefetched without a pinned revision; local cache under the user's `.cache/huggingface/hub` |
| Model-cache size | About 2.97 GiB of Chatterbox blobs; recursively summing blobs and linked snapshots gives 5.95 GiB, so do not claim twice the storage is reclaimable |
| OCR service | Initially stopped: direct localhost status requests were refused even outside the sandbox. Started with Paul's authorization; API version 0.33.3, both `glm-ocr` and `glm-ocr-doc` listed at about 2.2 GB each, potentially sharing blobs; `/api/ps` empty. Availability restored, no OCR or model-load validation performed |
| Reserve models | Documented qwen2.5vl reserves are absent from the current model list. The 1.1 branch's default `qwen3-vl:32b-instruct-q4_K_M` is present. Other listed models were not inspected or classified as project cleanup candidates |
| Fish Speech | Documented env, `D:\ml_repos\fish-speech` and its `checkpoints/s2-pro` path do not exist. The Hugging Face Fish cache contains one tiny residual file, not retained model weights |
| ffmpeg | Working Chocolatey binary; installer can fetch an app-owned binary instead |
| Build tool | External Inno Setup compiler required; existing candidate proves a prior compile, not that a new build was executed today |

Downloads/setup depend on Anaconda, Python package indexes, PyTorch CUDA wheels, Hugging Face and an ffmpeg distribution. Miniconda is version/hash pinned; Python requirements are pinned but not a hash-locked download set; ffmpeg release download and model revisions can drift. Current installed dependency consistency is confirmed; fresh network resolution was not retried.

GitHub hosts source/releases and supplies an optional update notification check. Crash reporting can use a locally configured Discord webhook. No mandatory paid API key is required for the core pipeline. The unrelated `dnd-transcribe` environment was not touched. Installer runtime/cache behavior must be validated separately from the existing development environment.

## 15. Git / Repo State

**Confirmed by live `git ls-remote` on the audit date:**

| Ref / worktree | State |
| --- | --- |
| Local `master` | `8e4f73e`, three commits ahead of remote |
| Remote `master` | `f9d15993a16b842695e1b48be06d1fe1bfe652be` |
| Local-only master commits | `19f74df` stabilization; `308564a` 1.0.2 preparation; `8e4f73e` candidate-validation documentation |
| `codex/v1.1_character_discovery` | Local/remote `99e4647`; three unmerged feature commits: discovery, multivoice rendering, voice-type casting |
| `cursor/setup-cloud-dev-environment-75aa` | Local/remote `828aa7b`, already merged into master; checked out at `D:\Audiobook_Pipeline_1_1` |
| Linked worktree | Clean at inspection, but it contains the merged cloud-setup branch, not the character-discovery branch its folder name might imply |
| Tag | Only `v1-parallel`, annotated tag object `360b379`, peeled commit `ad3eb38` |

The September 8 audit began with untracked `PROJECT_STATE.md` from the September 4 assessment and two pre-existing tracked modifications: `.gitignore` adds protection for `Ozymandias_20260903/`; `CLAUDE.md` removes two voice-rights sentences. These were preserved. No other ordinary untracked files were reported; ignored data and scratch handoffs are extensive. This audit modifies only `PROJECT_STATE.md` as its persistent repository change. Nothing was staged or committed.

The single-branch standing description is factually stale. The character branch changes 14 files, roughly 3,518 additions/83 deletions relative to its merge base, and predates September stabilization. Do not merge it without reconciling failure recovery, process ownership, downloads and plan semantics. Its tests were not run in this audit.

A pattern scan confirms credential endpoints exist in both Inno scripts at `3351d47` **and at current remote master**. They are absent from the local current tracked files. Thus the problem is not limited to buried public history. Provider revocation is still a separate unconfirmed action. Prior purchased-excerpt purge completion is supported by the project record; this audit did not redo GitHub Support's purge verification or inspect all remote caches/releases.

## 16. Stale Artifacts / Cleanup Candidates

Storage sizes below are approximate logical file sizes measured September 4, not a freshly repeated storage census. Installer sizes/hashes and patch manifest agreement were rechecked September 8. After this inventory, Paul authorized stale-file cleanup; deleted items are marked below and recorded with hashes in the private cleanup receipt in section 23.

| Path | Category / size | Why review; confidence | Removal risk / recommendation |
| --- | --- | --- | --- |
| `app/jobs/*/segments/` | Five caches, about 9.81 GiB | Completed jobs retain regenerable PCM; Confirmed | Loses resume/reassembly and comparison evidence. Verify accepted output and repair needs, then consider the existing completed-cache action |
| `app/jobs/` overall | About 12.51 GiB | Logs, blocks, images, outputs and PCM mixed together; Confirmed | Do not delete wholesale. Keep job records/provenance and needed diagnostic evidence |
| Job-local `output/` and `audiobooks/` | About 2.32 GiB and 1.82 GiB respectively | Delivery intentionally copies audio; several job versions exist; Confirmed duplication mechanism, not byte identity of every pair | Keep accepted library outputs. Manually verify versions/backups before considering old output removal |
| `Output/Reference_Audio/` | About 975.48 MiB | Private comparative listening source dominates `Output`; Likely no runtime role | Keep private; archive if no more timing/listening analysis is needed |
| `Output/Narration_Gap/` | About 146.52 MiB | Completed pause audition artifacts; Likely | Preserve verdicts and representative anchors; archive audio after review |
| `Output/Narration_AB/`, `Narration_Stage0/`, `Narration_Stage2/`, `Benchmarks/` | About 38.6 MiB combined | Historical experiments, not runtime dependencies; Confirmed | Archive after checking which results explain current defaults; do not erase the evidence supporting those defaults |
| `ab_samples/` | 19.19 MiB | Private A/B material referenced by retained harnesses; Confirmed | Keep ignored; archive only with harness/evidence review. Previously scrubbed book prose must not be republished |
| `Output/Setup_AudiobookStudio.exe` | Formerly 2,232,352 bytes, August 23 | Predates credential-removal stabilization; Confirmed obsolete for current delivery | Deleted September 8 with owner authorization, along with its 10,552-byte manifest; hashes retained in receipt |
| `Output/Setup_AudiobookStudio_Patch.zip` | Formerly 1,557,799 bytes; inner EXE 2,127,381 bytes | August 23 ZIP contained an older patch, not the retained 1.0.2 EXE; Confirmed | Deleted September 8 with owner authorization; hash retained in receipt |
| `Output/Setup_AudiobookStudio-build-info.txt` | Formerly 344 bytes | Described commit `1184951`, a 2,225,261-byte executable and a different hash; did not describe the adjacent full EXE; Confirmed | Deleted September 8 with owner authorization; hash retained in receipt |
| `Output/Setup_AudiobookStudio_Patch.exe` and manifest | Current local candidate, details below | Required validation subject; Confirmed | Keep; not approved for release |
| `Output/pre_history_scrub_e020cf8.bundle` and checksum | About 0.37 MiB | Deliberate pre-purge recovery copy containing sensitive history; Confirmed | Keep private per release record. Never publish or restore indiscriminately |
| `Output/guest_*`, `headless_*`, `test_tos_fix_*`, `.wsb` | A few MiB | Older sandbox/install diagnostic evidence; Likely | Archive after current installation proof, retain failures useful for regression diagnosis |
| Root `AUDIT_*.md`, `HANDOFF_*.md` | Small ignored notes | Old hashes/plans duplicate and contradict newer records; Confirmed examples | Archive after checking unique evidence; not authoritative next-step instructions |
| `FishS2_directed.wav` | Formerly 2,465,836 bytes | Rejected narrator experiment output | Deleted September 8 with owner authorization; listening verdict remains in narration-auditions record |
| Fish Hugging Face cache directory | One tiny residual file | Env/repo removed; Confirmed | Negligible value to cleanup; verify manually, no large weights to reclaim |
| Chatterbox cache/environment | Required active model/runtime | Working dependencies; Confirmed | Keep. Do not remove linked snapshots as assumed duplicates |
| `samples/` | 96.36 MiB | Mixed tracked scripts/Modelfile and private inputs/voices; Confirmed | Keep code and active samples. Review individual private artifacts, never blanket-delete |
| `source_pdfs/`, `processed_pdfs/` | 135.40 MiB / 2.68 MiB | User source data, not disposable build output | Keep unless Paul explicitly decides otherwise |
| `Ozymandias_20260903/` | 65.72 MiB, recent unrelated creative work | Off-product scope, protected by pre-existing ignore edit; Confirmed | Keep; not stale merely because unrelated. Separate organizational decision only |
| Python `__pycache__` folders | Small | Regenerable caches; Confirmed | Low-priority deletion candidates after review, no meaningful space benefit |
| Merged Cursor branch/worktree | No unique branch commits over master | Historical development surface; Confirmed | Verify owner usage before archive/removal; do not confuse it with unmerged 1.1 work |

Retained candidate identity, freshly measured:

1. Path: `Output/Setup_AudiobookStudio_Patch.exe`.
2. Bytes: `2139828`.
3. SHA-256: `0a55443ce6082221afe017ff65f88b518e563f0077f476533be6534be8d0199c`.
4. Manifest: eight explicit app files, no media or local config entry. Every manifest file hash matches the corresponding current HEAD content when serialized with CRLF. Raw LF Git blob hashes differ, as expected.
5. Build source attribution: consistent with `8e4f73e` and the recorded clean-HEAD build; these eight app files also existed at the preceding preparation commit, so the manifest alone cannot distinguish the exact build commit. No independent exact-commit sidecar for this patch was found in `Output`. Preserve the distinction between matching packaged content and fully proven build provenance.

The older full executable's measured SHA-256 is `8e82d9f3b83d7c1f0c5714e8189a18da65453ba1398c234162b1213ac4470a62`, matching the old installer record, not its stale adjacent build-info file. No installer was executed or rebuilt during this audit.

## 17. Major Decisions and Directional Observations

1. **Reliability before additional casting features.** Preserve the 1.1 work, but do not let it bypass the unresolved 1.0.2 field-validation gate. Its tiny synthetic render reportedly used the same reference for three roles, proving routing rather than distinct-character listening quality.
2. **Measure supported hardware.** The README's roughly 6 GB claim is unvalidated. An older build completed jobs on a 12 GB RTX 3060, while the later 16 GB laptop failed through an uncaught exception form. Neither observation establishes a universal capacity threshold. Record exact build/runtime, workload, recovery events, peak memory and listening result; recovery plus an honest support range is more useful than another guessed budget reduction.
3. **Keep batching and environment isolation.** Existing records show weak gains from Windows multiprocess concurrency and rejected larger token budgets/vocoder overlap. No new evidence from this audit justifies reopening those paths.
4. **Do not solve timing structure with uniformly larger gaps.** Current Path A paragraph gap is 650 ms, chunk gap 150 ms; historical auditions already rejected larger uniform paragraph gaps. Scene/section structure is a separate future experiment.
5. **Distinguish patch and fresh-install validation.** The checklist combines a patch candidate, which requires an existing app, with an empty-machine install gate. A complete distribution needs a separately identified full installer and a known compatible patch base; an eight-file patch cannot satisfy the clean-machine gate alone.
6. **Documentation must stop overstating proof.** A past done job, manifest, passing unit test and native UI test each prove different things. Current `CLAUDE.md` is valuable but mixes superseded snapshots; use this evidence map before repeating historical investigations.
7. **Cleanup is not the main engineering task.** Most space is legitimate recoverability or private audio. Selective cache reclamation could be worthwhile, but indiscriminate deletion would sacrifice the evidence needed to assess quality and old chapter mappings.

## 18. Gap Between Current State and End State

| Gap | Present reality | Required outcome |
| --- | --- | --- |
| Public source safety | Remote branch still carries old webhook | Revocation confirmed and intended corrected source synchronized through normal reviewed Git work |
| Repeatable distribution | Old full installer, newer patch, stale sidecar | Exact full/patch/base provenance and matching validation evidence |
| Hardware robustness | Desktop-calibrated budget; historical 12 GB completion and later 16 GB recovery failure | Controlled 16 GB recovery and shutdown proof, measured support statement |
| Fidelity/navigation | Heuristics and historical outputs; old blocks lack pages; leading decorative outline entry can be lost | Representative current extraction checks and installed M4B navigation |
| Listening acceptance | Some accepted improvements, some rejected books | Short controlled owner acceptance before full-book commitments |
| Cache/data lifecycle | Resume works but extraction can be stale; title-based replacement | Clear re-extraction behavior, preserved outputs and intentional cleanup |
| Product scope | Single voice master plus substantial unmerged 1.1 | Explicit decision on whether reviewed multivoice belongs in the near-term product |

## 19. Recommended Roadmap

This roadmap is dependency-aware and intentionally unexecuted.

| Milestone | Dependencies | Work / acceptance evidence | Risks and reason for order |
| --- | --- | --- | --- |
| M0: Secure and reconcile the handoff | None | Confirm old webhook revocation and deliberately replace/disable the matching local setting; contain local API file mutations and validate the request boundary; preserve existing user edits; reconcile local stabilization with intended remote; identify exact candidate/base/full-build provenance | Current remote source and ambiguous artifacts can undermine every later validation. History rewrite remains a separately authorized decision |
| M1: Establish supported installation and runtime | M0 | Separate full-install and patch-upgrade test tracks; verify native launch, config/env selection, downloads, data-preserving uninstall and all mandatory checklist items applicable to each artifact | A working developer environment does not prove another user's setup. Do not publish until the entire mandatory checklist is satisfied |
| M2: Prove bounded GPU operation | M0 and an identified compatible installed candidate | Short synthetic/licensed 16 GB run, recoverable OOM split/order/resume, single-item hard-failure message, cancel/app-close ownership; validate explicit OCR-to-TTS release behavior; derive hardware guidance from measurements | Avoid wasting a full-book run and avoid asking the tester to reproduce the touchpad failure. Can proceed alongside M1's fresh-install track |
| M3: Close fidelity and lifecycle gaps | M1/M2 for installed acceptance; extraction-only checks can precede them | Representative prose/verse/complex-layout checks; character and heading preservation; correct opening pages; cache invalidation policy; leading decorative-page chapter boundary and real player navigation; output-name collision decision and transactional replacement; missing-voice handling; corrupt-job isolation; short listening acceptance | Cheap synthetic extraction, chapter-boundary and output-identity checks can start independently of M0/M1; actual fixes require separate authorization. Text correctness and output identity must precede expensive generation; extraction and narration must be validated separately |
| M4: Release a bounded single-voice MVP | M0 through M3 and all `RELEASE_CHECKLIST.md` gates | Clean synchronized release commit, full suite, canonical build, exact artifact/hash, installed evidence, accurate requirements and limitations, then separately authorized publication | Shipping a minimally tested patch as a clean installer would recreate the prior failure pattern |
| M5: Decide and evaluate 1.1 | Core reliability evidence and Paul's scope decision | Review/reconcile character branch with stabilization; source-preserving attribution validation; independent distinct-voice listening; measure latency and reference management; only then choose merge/release scope | Branch adds substantial complexity and predates critical fixes. Routing smoke evidence is insufficient for cast quality |
| M6: Improve quality and reclaim storage selectively | Stable core; owner acceptance and retention decisions | Controlled scene-break audition, then any justified implementation; archive obsolete artifacts and approved completed caches | Quality experiments need preserved baselines. Cleanup follows ownership/evidence review, not filename guessing |

Recommended next deliverable: a candidate with the confirmed local deletion and data-preservation gaps addressed, a precisely identified compatible beta base, and a short installed validation protocol. The retained 1.0.2 patch is a historical candidate, not automatically the right next artifact after these findings. Run full fresh-install validation as a separate track. Do not make a multivoice scope decision or historical cleanup a prerequisite for core reliability work. Before a long-book rerun, resolve extraction freshness and library-output identity as well as short listening acceptance.

Do not work on larger token budgets, overlapping T3/S3Gen, more Windows narration processes, production integration of new TTS engines, generic expressive dialogue profiles, UI rebranding, cloud deployment or wholesale dependency pruning yet. No evidence makes them prerequisites for the current release or field failures. Paul separately authorized the isolated Breeze/Qwen listening audition in section 23 and the subsequent Chatterbox V3 audition in section 25; neither is approval to change production narration. Keep the existing A/B harnesses and runtime dependency closure.

## 20. Immediate Next Actions

1. Prioritize the reproduced voice-delete containment defect alongside provider-side revocation evidence and the decision whether reporting should be disabled or configured with a replacement. The current local endpoint is now confirmed to be the exposed one; its provider status remains unknown. Never copy a credential into tracked source or this document.
2. Review the two pre-existing edits and the three local stabilization commits, then make an explicit source/remote handoff decision. This audit does not authorize pushing or rewriting history.
3. Establish which full installer version is actually installed on the beta laptop and associate the retained patch with that base. Resolve exact build provenance before sending any file.
4. Prepare a short synthetic/licensed installed test plan for downloads, OOM recovery, ownership and chapters, plus failed delivery, unavailable selected voices and damaged job records; arrange fresh-install validation separately. Follow the release record's current prohibition on sending/publishing until its prerequisites are satisfied.
5. Validate extraction separately before the next narration, including a selected decorative opener before the first spoken page. Existing blocks will not automatically refresh when extraction code changes. Resolve output-name collision and failed-replacement behavior before rerunning into an accepted library title. Preserve historical evidence; prefer a new controlled job to an unreviewed destructive cache reset.
6. Paul's near-term listening goal is now one narrator with consistent character delivery and emotional continuity across dialogue, not separate cloned character voices. Preserve the multivoice branch; its merge is not a prerequisite for this goal. The intended purpose of `D:\Audiobook_Pipeline_1_1` still needs clarification before resuming work there.

## 21. Open Questions / Needed Human Decisions

1. Has the exposed webhook been revoked, and should local reporting continue with a replacement? Offline comparison now confirms the configured/effective endpoint is the old one. No live credential test was attempted.
2. Is the next deliverable a private patch for existing beta installs, a first broadly usable full installer, or both?
3. What exact app/runtime version is installed on Brandon's machine, and can a controlled short test be arranged? Has he already tested anything newer than the documented failing build?
4. Paul has chosen one narrator who consistently differentiates characters through delivery and preserves emotion across their replies. Whether separate character casting belongs in a later release remains undecided; it is not the current listening requirement.
5. Which books/outputs are accepted reference results, and which old segment caches must remain for comparisons or chapter repair?
6. What measured minimum GPU/support range and listening-quality threshold should the product promise?
7. Are same-title reruns supposed to replace library outputs, and should independently created jobs ever do so?
8. Which additional voice/reference assets are approved for future synthetic or licensed validation? The September 8 audition uses the established default male reference locally; no reference audio is redistributed or tracked.

## 22. Codex Handoff Readiness

**Ready for a bounded follow-up, not a release handoff.** A fresh agent has source, tests, historical evidence, current artifact identities and a prioritized roadmap. It still needs human/provider evidence and physical-machine validation to close the release gates.

For the active narration continuation, read `AGENTS.md`, all of `CLAUDE.md`, and the updated `HANDOFF_NEXT_SESSION.md`; use this document for the broader audit and sections 23 through 29 for the recent experiments. Load the relevant detailed skill record. Read `RELEASE_CHECKLIST.md` before any release work, which is not the active task. Treat later records and verified source/runtime evidence as superseding earlier narrative snapshots. Recheck branch/status before editing; this document records a point-in-time audit.

Use native Windows for Git writes. Keep narration and OCR isolated on the GPU and keep unrelated environments untouched. Do not start or resume existing jobs just to demonstrate launch, because startup/resume can change job state and reuse stale extraction. Use synthetic inputs for new validation and distinguish extraction fidelity, TTS output, assembly and installed UI proof.

Only the requested state document was intentionally edited by the initial audit; it remains untracked. The pre-existing `.gitignore` and `CLAUDE.md` edits were preserved. Ollama was started at Paul's request and left running idle. No production roadmap item, branch change, release build or publication occurred. The later authorized private audition and cleanup are recorded below.

## 23. Authorized TTS Audition and Stale-File Cleanup, September 8

Paul subsequently asked to check out Breeze and Qwen and clean up old outputs or stale files. This authorized a private engine audition and the scoped deletions below, not a production engine change or release. All new scripts, weights, reference derivatives, transcripts and audio are under ignored `Output/TTS_Comparison_20260908/`. The existing chatterbox, fish-speech and dnd-transcribe environments were not modified.

**Chatterbox version distinction:** [Resemble's official announcement](https://www.resemble.ai/resources/chatterbox-multilingual-v3-tts-with-embedded-watermarking-for-25-languages) dates Multilingual V3 to June 10, 2026. The app imports `chatterbox.tts.ChatterboxTTS`, the original English model, with installed chatterbox-tts 0.1.7. V3 was not included in this first comparison; the later authorized V3 audition is recorded in section 25.

**Completed listening artifact:** `Output/TTS_Comparison_20260908/listening/index.html`, also served locally at `http://127.0.0.1:8796/`. Eighteen clips cover three engines, four original synthetic passages and second seeds for quiet prose and emotional speech. Each passage was verified to remain one unchanged production-plan chunk. Anonymous A/B/C labels stay consistent throughout. Paul completed all six listening notes before the mapping was revealed; the owner verdict is recorded in section 24.

The final common reference is a 17.31-second complete-sentence crop of the established male sample; the original 20-second file is unchanged. Initial CPU ASR found an added opening “and” in all six Qwen renders with the original reference, which itself ends mid-sentence on “and.” A same-seed crop probe removed the addition, so the entire comparison was regenerated with the cropped reference for every engine, retaining the original seeds. All six final Qwen clips are free of that opening addition in CPU ASR. This is measured reference sensitivity, not a general hallucination-rate result. The reference transcript is machine-derived, not independently verified by a human. The initial round is retained as diagnostic evidence.

Final audio validation verified all 18 blind files against their intended raw renders, exact text/seed pairs and common reference hash. Constant gain only, no compression or pause editing; all clips are mono 24 kHz PCM, measured from -22.03 to -21.96 LUFS with maximum true peak -1.16 dBTP. CPU ASR found no large omissions or repeated passages. Remaining differences include ambiguous homophones and pronunciation/number readings that need listening, not automatic classification as model defects. All 18 audio HTTP endpoints returned 200 with the expected byte sizes; browser rendering and actual play/pause were checked. The page was left open, paused at the beginning of the first clip.

| Engine / execution path | Six clips: audio seconds | Generation seconds | Aggregate generation/audio ratio | Peak PyTorch allocated GiB |
| --- | ---: | ---: | ---: | ---: |
| Existing English Chatterbox, individual neutral requests | 87.16 | 45.37 | 0.521 | 3.76 |
| Breeze TTS 2, native Windows eager BF16, fast paths disabled | 103.76 | 258.98 | 2.496 | 8.07 |
| Qwen3-TTS 1.7B Base, BF16 SDPA, transcript-conditioned cloning | 91.68 | 152.66 | 1.665 | 4.44 |

These are short-request observations, not full-book or production-batching benchmarks. Startup is excluded; Qwen and Chatterbox cache reference preparation before requests, whereas Breeze's measured request includes reference encoding. No whole-book speedup or support promise follows from these numbers. Breeze officially specifies Linux, but its eager path produced all clips on this Windows machine. Optimized Breeze inference was not tested. Its model and self-hosted output license is research/noncommercial, separate from the Apache-licensed source; no model or generated audio was bundled into the application.

The disposable runtime uses Python 3.11, torch/torchaudio 2.9.1+cu128, qwen-tts 0.1.1 and transformers 4.57.3; `pip check` passed and the full freeze is retained. Breeze source is pinned to `e2c5ac2f54fe15daa94237a7dbf31e446660a4c9`, Breeze weights to `799624c0b4a1daa8db6d28bbd9850043c0270734`, and Qwen Base weights to `fd4b254389122332181a7c3db7f27e918eec64e3`. Models ran sequentially on the RTX 4090 with Ollama idle and no OCR overlap. About 12.2 GB of audition checkpoints plus the isolated runtime were added; this work is not a net disk-space reduction.

**Cleanup completed:** five verified obsolete files were removed, totalling 6,266,883 bytes: the August full installer and its manifest, stale mismatched full-installer build-info, old patch ZIP, and rejected root-level Fish WAV. `cleanup-receipt.json` records their exact paths, sizes, hashes and reasons. Deletion was verified. The retained current patch hash and original voice hash are unchanged. Books, PDFs, accepted audio, all jobs and segment caches, prior listening baselines, and the history-scrub bundle/checksum were preserved.

Detailed evidence and reproduction instructions live in the private audition `README.md`, `audio-qa.json`, `verification-summary.json`, runtime freeze and generation logs. The local listening server is started hidden, binds only 127.0.0.1:8796 and serves only the listening folder; its PID is recorded in `listening-server.pid`. No application code, configured production narrator, release artifact, branch or commit was changed. Paul's blind listening notes and the disclosed mapping are recorded in section 24. Further narration trials and any integration remain separate decisions.

## 24. Owner Listening Verdict, September 8

Paul completed all six note fields on the comparison page before the engine identities were revealed. Exact browser-entered notes are preserved in ignored `Output/TTS_Comparison_20260908/owner-feedback.json`; the detailed interpretation is in `LISTENING_VERDICT.md` in the same folder. The existing mapping was read back and agrees with the earlier waveform verification: A is Breeze TTS 2, B is Qwen3-TTS 12Hz 1.7B Base, and C is the current original English Chatterbox, not Multilingual V3.

- Quiet prose: A led B and C for delivery on both takes. C was rushed for the material. On take two, A also sounded least natural, with an uncertain reverb-like quality. Delivery and timbre judgments must remain separate.
- Short dialogue: B had the best opening voice differentiation, but a later return voice sounded off. A lost character differentiation after the opening exchange; C was poor and rapid.
- Emotional speech: C was best by far on seed 42, but flat on seed 142; A won the second take over B and C. The text, reference and generation settings were identical across takes, with different seeds. This is evidence of variable delivery on this passage, not a general failure-rate estimate.
- Names and numbers: C was preferred for character separation despite reading 6:45 as six thousand forty five. The pronunciation error is now confirmed by owner listening as well as the earlier ASR flag. This synthetic input was supplied directly to narration, so PDF extraction did not cause this error. No correction was implemented.

Paul subsequently clarified the main acceptance criterion: one narrator who consistently differentiates recurring characters through delivery, with each character's emotional tone carrying over through back-and-forth dialogue. He explicitly selected that approach over separate stable cloned voices for characters. Character and emotional continuity matter more to him than generic quiet-prose preference. The original clarification wording is preserved with his notes in `owner-feedback.json`.

The round does not establish a clear production replacement on that criterion. Qwen's opening dialogue separation weakened on a returning voice; Breeze lost character differentiation; current Chatterbox had strong character delivery in some clips but poor or flat delivery in others. Breeze's quiet-prose wins do not settle this requirement. Keep production unchanged pending a controlled continuity audition and a separate integration decision. Do not infer that per-passage engine switching or a merge of the multivoice branch is wanted or validated.

The six comparisons comprise four passages, one listener and one cropped reference. First-place counts are not independent votes or a statistical ranking, and the precision-case preference is not fidelity acceptance. Recommended next work is a bounded single-narrator dialogue-continuity audition: repeated character returns, intervening narration, story-driven emotional development, several seeds and more than one scene, followed by explicit production-chunk boundary checks. Each current sample was generated in one call, so these observed dialogue failures are not solely a chunk-boundary problem. Persistent character delivery cues and scene context are candidate controls, not implemented functionality. A verified time-format narration correction and investigation of Breeze's perceived resonance remain separate issues. This feedback turn did not start new generation, implement narration changes or modify the user's browser notes.

The sample server was also restored after it had stopped later that evening. `Listen_to_Samples.bat` now starts it when needed and opens the page. Both reuse of a running server and startup from a stopped server were checked, along with all 18 audio endpoints. The page remains available at `http://127.0.0.1:8796/` while its local server is running.

## 25. Authorized Chatterbox V3 Follow-up, September 8

Paul explicitly requested a Chatterbox V3 audition after clarifying the single-narrator continuity requirement. This adds an isolated listening experiment, not a production change. The original A/B/C mapping has been disclosed; this second round saves a new consistent X/Y mapping privately for disclosure after the owner's verdict. The first comparison page and browser note keys are preserved.

The actual V3 API is `ChatterboxMultilingualTTS.from_local(..., t3_model='v3')`, explicitly selecting `t3_mtl23ls_v3.safetensors` and English. Official source is pinned to `5de7a54aa4e5e2baadb0182dde554908b48b85c2` and `ResembleAI/chatterbox` weights to `5bb1f6ee58e50c3b8d408bc82a6d3740c2db6e18`. The upstream package still calls itself 0.1.7, so that version string alone cannot identify the model. Its pretrained multilingual loader defaults to V2 unless V3 is explicitly selected.

A new `runtime-v3` virtual environment contains Python 3.11, torch/torchaudio 2.6.0+cu124 and transformers 5.2.0. `pip check` passed, and a full freeze and weight hashes are retained. Existing production and unrelated environments were not modified. The existing project watermarker compatibility stub was applied in both arms; this trial does not validate upstream watermarking. Ollama was stopped; GPU process checks preceded each sequential model run. V3's tokenizer created an ancillary pkuseg download/extracted cache under `C:\Users\paulm\.pkuseg`; this is the exception to the otherwise ignored audition-folder storage. A failed offline Cangjie mapping lookup affects an untested Chinese path; this experiment contains English only.

Eighteen comparison clips comprise six original passages/takes paired between V3 and the exact retained current-English renders, plus three takes of a new ten-turn synthetic dialogue rendered by both versions. All use the same complete-sentence 17.31-second reference. The scene focuses on recurring character delivery, intervening narration and anger easing into cautious cooperation. Production `narrate_worker.build_plan` produced ten chunks per scene, with the actual profile A gaps of 150/650 ms. Both versions receive identical chunk texts, per-chunk seeds, neutral settings, 30 ms edge fades and assembly gaps. Each chunk starts from the reference without previous dialogue history or character-specific controls. The six original cases remain single calls. This is one scene with three seeds, not broad continuity acceptance.

Raw-render verification passed for all input text/seed/reference identities, chunk hashes and reconstructed scene assembly. On the original six clips, V3 produced 89.32 seconds in 49.69 seconds of inference (ratio 0.556), versus current English's retained 87.16 seconds in 45.37 seconds (0.521). Across the three scene takes, V3 produced 149.95 seconds including added gaps in 79.68 seconds of inference; current English produced 133.11 seconds in 67.98 seconds. Excluding added gaps from the denominator, those ratios are 0.602 and 0.588. Peak PyTorch allocated memory was at most 3.77 GiB. Startup and reference preparation are excluded; individual-request timings do not establish production-batching or full-book performance.

The completed artifact is `Output/TTS_Comparison_20260908/listening/v3/index.html`, served at `http://127.0.0.1:8796/v3/`, with `Listen_to_V3.bat` to restart its local server and reopen it. All 18 listening files passed waveform mapping and gain-only verification, measuring -23.31 to -23.26 LUFS with maximum true peak -1.13 dBTP. CPU ASR preserved the full continuity scene in every render after allowing Lena/Lina spelling variation. Remaining flags include missed train/mistrain, names, number/currency readings and word-boundary spelling. These require listening; no pronunciation fix or character-continuity winner is claimed. All 18 audio endpoints returned 200 with correct byte lengths. Browser layout and play/pause were verified, and the first player was reset to 0:00. Owner listening is pending.

Detailed methodology is in `V3_README.md`; exact inputs and evidence are in `v3-plan.json`, `v3-render-verification.json`, `v3-audio-qa.json`, `v3-verification-summary.json` and `v3-browser-verification.json`. No app code, default narrator, branch, commit, release artifact or production job was changed.

## 26. V3 Mobile Listening and Owner Verdict, September 9

Paul requested a private Google Drive copy for mobile listening, then explicitly authorized an exception to the project rule against distributing generated audio after automatic review blocked the upload. Eighteen WAVs were uploaded into nine numbered subfolders of `Chatterbox V3 - Blind Listening - 2026-09-09`, two files named X.wav and Y.wav per folder. Connector readback verified all names, folder placement and exact sizes (22,059,324 bytes total). The root folder remained private, with only the owner's account listed. `Output/TTS_Comparison_20260908/drive-upload-receipt.json` records the authorized scope, IDs and verification. No reference audio or engine-mapping file was uploaded.

The owner then supplied feedback for all nine folders before this round's identities were revealed. The saved mapping was read back: **X is Chatterbox Multilingual V3; Y is current original English Chatterbox.** Exact notes are in ignored `v3-owner-feedback.json`; the detailed interpretation is in `V3_LISTENING_VERDICT.md`. This supersedes the pending-listening status at delivery in section 25.

Y was preferred in folders 01, 02, 06, 07, 08 and 09; X in 03, 04 and 05. This 6–3 count is descriptive, not a general quality rate. In the returning-character scene, Y won takes 1 and 2, while X won take 3 strongly and may have been the owner's favorite of the six scene renders. However, X's take 2 opening was rejected before completion, and its winning take 3 ending still sounded strange. X won both quiet-prose takes. Y was much better in the short dialogue and better in both emotional-speech takes, where X sounded flat; the second emotional win was narrow. Y was preferred for dialogue in the precision passage, but both models' time/currency readings were rejected. The new feedback does not establish the exact erroneous phrase for each model; no normalization fix is claimed.

Distracting breaths were specifically reported for Y in folders 01, 03 and 04. Their source and the right intervention remain unverified. Do not infer that silence trimming, faster speech, a different reference or blanket breath removal is accepted. The current English model remains the better-supported baseline for the owner's dialogue/emotion goal in this set; V3's best scene take is worth retaining as a quality reference, but it does not establish a reliable replacement. Neither version met consistent continuity and numerical-fidelity acceptance across this small set.

The proposed next controlled work is to identify and reduce distracting breaths while preserving expressive delivery, separately verify speech-text normalization for time/currency, and test whether V3's best scene delivery repeats on fresh takes and another scene. These were proposed experiments at this feedback turn; section 27 records the subsequent authorization and completed local auditions. No new audio, production engine switch, reference change, per-passage engine routing, Drive mutation or application-code change occurred in the feedback turn itself.

## 27. Continuity, Breaths and Pronunciation Follow-up, September 9

Paul authorized the four proposed experiments with “Alright, let’s make it happen.” Work is contained in ignored `Output/TTS_Comparison_20260908/followup_20260909` and the adjacent isolated audition harness. No application code, production narrator/settings, canonical text, reference audio or existing jobs were changed. The user's original uncommitted repository edits remain intact.

Fourteen new renders were completed: Qwen on the original ten-turn scene at seeds 42/142/242; current English, V3 and Qwen on a second eleven-turn scene at seeds 742/842/942; and one time/currency alias render each for current English and V3. The second scene tests hope, disappointment and resolve with the same two recurring characters. Retained current/V3 originals supply the first scene and written-number controls. Breeze remains on hold. Models ran sequentially with GPU/Ollama checks, using their isolated environments and the same complete-sentence reference. Production `build_plan` generated the actual chunk plans, with the earlier scene asserted identical. All models still receive independent chunks, without new character-history controls or multiple actor voices. Concurrent CPU analysis means generation timings are not a controlled performance benchmark.

The completed local page `http://127.0.0.1:8796/followup/` contains 28 WAVs in 11 groups. Groups 01–03 compare three engines on the returning-character scene; 04–06 compare three original/current-English performances against conservative pause-noise attenuation; 07–08 compare written and explicitly spoken time/currency wording; 09–11 compare three engines on the second scene. Fresh anonymous labels remain undisclosed pending owner feedback. `Listen_to_Followup.bat` restarts the local server when needed.

The breath trial protects exact-text CTC-aligned words with 80 ms margins, widened to 120 ms for uncertain alignments. Eligible unvoiced pause noises receive up to 9 dB attenuation with 30 ms ramps. One, six and eight candidate events were changed in the quiet clip and two scenes. The approximately 360 MiB CPU alignment model is stored inside the ignored follow-up folder; package environments were not changed. All final breath pairs retain identical duration, playback gain, and PCM outside selected windows. These are estimated pause-noise events, not owner-confirmed breath timestamps; breathy delivery within words is not treated. Listening must still judge benefit, missed breaths and speech damage.

Pronunciation aliases change only the narration input for `6:45` and `$37.50` to “six forty-five” and “thirty-seven dollars and fifty cents.” Canonical text remains intact and no production normalizer is implemented. Digit-suppressed CPU ASR recognized both intended phrases in both new renders, versus failed readings in the retained written controls. V3's otherwise unchanged `208 miles` was recognized as “twenty-eight miles,” requiring owner review. This does not establish general numerical-fidelity acceptance.

All fourteen new renders passed text/reference/seed/hash and assembly verification. All 28 final files passed gain-only waveform verification at -23.51 to -23.46 LUFS, maximum true peak -1.33 dBTP. All audio HTTP endpoints returned 200 with matching byte counts; browser layout and play/pause were verified and the first player reset to 0:00. Focused ASR recovered three apparently missing final “Eat” words and “The shore is close” that full-scene recognition had missed. Current-English second-scene take 2 still produced a “He gave”/“They give” recognition disagreement; this and remaining name/word/number differences need listening. No clips were regenerated to select better outcomes. Verification evidence and limitations are retained in the follow-up README and JSON reports.

The private Drive folder `Narration followup 2026-09-09` (ID `1CRblvYUrTGvWRU-2a0jJnU7dT7S6lYnj`) and eleven numbered subfolders were created for the established mobile-listening workflow. Automatic approval review initially blocked the first WAV upload because it treated the earlier exception as limited to the previous eighteen clips. Paul then explicitly authorized the new batch with “Good to upload to drive.” All 28 WAVs (56,294,188 bytes) and a 755-byte `START_HERE.txt` listening guide were uploaded. Folder readback verified exact counts, file names and byte sizes for every clip; all report private status and root permissions contain only the owner's account. No reference or identity-mapping file was uploaded. `drive-upload-receipt.json` records completed delivery and authorization; `drive-upload-status.json` retains the historical pre-approval snapshot. Both local and Drive delivery are complete. The subsequent owner verdict is recorded in section 28; production acceptance remains unmet.

## 28. Follow-up Owner Verdict and Voice Inventory, September 9

Paul provided all eleven folder verdicts before the mapping was disclosed. Exact notes are in ignored `Output/TTS_Comparison_20260908/followup_20260909/owner-feedback.json`; `LISTENING_VERDICT.md` retains the interpretation and proposed next experiment. H is current English Chatterbox, J is V3, K is Qwen. M is reduced candidate pause noise and N the original; P is written time/currency and Q the spoken aliases.

No engine meets consistent naturalness, character continuity and emotional-delivery acceptance. H was strongly preferred in folders 02 and 10, although 10 still had a tone discontinuity around 0:25. J in folder 03 was the owner's strongest take heard, but this is the same retained V3 seed-242 render previously preferred, not a fresh successful replication. Folder 01 was inconsistent across all three; folder 09 rejected all three; folder 11 had flat or incongruent delivery without an accepted winner. Qwen was repeatedly robotic/monotone and had clipped words, with some clips abandoned early. Its tested configuration is deprioritized, not declared universally inferior across other voices/models.

The breath trial did not solve the defect. Folder 04 was hard to distinguish, 05 weakly favored M, and 06 rejected both for robotic reverberation and clipped sentences. This rules out treating simple pause attenuation as an accepted fix. Digital waveform headroom and ASR word recognition do not establish intact audible word endings or natural speech. The owner-confirmed artifacts remain unresolved.

The explicit spoken time/currency trial earned positive feedback, especially V3 Q in folder 08, whose written control read the currency as “thirty seven point five fifty pies.” Current-English P in 07 read the time as “six thousand forty five”; Q improved it but read the otherwise unchanged `208 miles` digit by digit. This supports the specific alias approach while showing that a complete typed-number normalization policy is still needed. No production normalizer was implemented.

Both synthetic scenes contain zero contractions. “I am staying,” “I do not need,” and similar full forms were in the assistant-authored source, not expanded by the pipeline. This was a test-writing weakness that may contribute to stiffness; it does not account for every synthetic artifact. Paul expects natural contractions and context-sensitive emphasis where an author deliberately chooses a full form. Preserve book wording; do not automatically contract all full forms or force stress on every one.

Read-only local inspection found 18 alternative voice WAVs: five female-labeled, thirteen male-labeled, all 25 seconds at 44.1 kHz stereo, with finite decoded samples. They are under `samples/Voice_Sample`; no additional Drive link is needed. File labels are not independent identity or reference-quality verification. Their hashes and metadata are saved in `feedback-diagnostics.json`; no voice sample was changed.

The same diagnostic inspected 189 raw scene chunks before the audition fades. Twelve Qwen chunks carry detectable sound within their final 30 ms, so the applied fade can overlap it, including two folder-02 K chunks. This is a concrete boundary-test target, not proof of which words were truncated. The metric detects energy rather than phonemes and does not exclude earlier model truncation or internal artifacts in Chatterbox. Assembly deletes no samples and applies no speed change; upstream V3 additionally crops roughly one final 40 ms speech token before returning its waveform. Neither behavior was changed and no causal fix is claimed.

Every tested scene still uses independent chunks with a shared reference and no persistent character or scene state. This limits what the comparison tests, but earlier one-call dialogue drift means chunking is not established as the sole cause. Paul has reopened different voices per character as a possible solution, not approved a production casting change. A bounded next comparison should first isolate rough endings and reference quality, then compare a selected single narrator with the same narrator plus fixed Lena/Daniel references on one naturally written scene, same engine/role boundaries/seeds, with a second matched take. This isolates speaker identity from engine changes and reduces listener burden to four clips. No new generation, voice casting implementation, production change or Drive upload occurred in this feedback-review turn.

## 29. New-chat Handoff and Graft Workflow, September 9

Paul requested that the next narration work happen in a new chat, with an extensive handoff and a starter prompt, and specifically noted the Graft installation. `HANDOFF_NEXT_SESSION.md` has been rewritten as the active narration continuation record. Its obsolete installer-first contents were preserved at `Output/TTS_Comparison_20260908/HANDOFF_NEXT_SESSION_before_20260909.md`. `HANDOFF_START_PROMPT.md` contains the prompt to paste into the new chat. No separate task was launched from this handoff turn.

The handoff carries the owner's priorities and all three rounds' verdicts, historical blind mappings, reused-versus-new render distinctions, the contraction-writing flaw, unresolved breath/clipping/numerical issues, actual reference inventory, exact model/runtime pins, artifact and harness paths, verification limits, private Drive delivery receipts, preserved Git state, cleanup history, and the proposed four-clip casting pilot. It distinguishes the new audition scope from the unrelated release and audit backlog.

Graft was actually run in the existing checkout: the map reported 41 files, 416 symbols and 1,108 edges, and source queries returned relevant spans. Follow AGENTS.md's graph-first workflow, read full truncated spans, use exhaustive Graft searches for exhaustive tasks, and rebuild after substantial source changes. Ignored audition files may be outside the graph and are directly addressable through the handoff's artifact paths. No graph rebuild is needed for this documentation-only update.

Use the existing `D:\Audiobook_Pipeline` checkout directly. The ignored handoff, models, samples, runtimes and audio are not carried into a fresh worktree. Native Windows readback still shows master at `8e4f73e`, the existing character branch at `99e4647`, the separate cursor worktree, and the pre-existing tracked/untracked edits preserved. No Git write, production code change, generation, cleanup or release action occurred during handoff preparation.

At the handoff status check around 15:58 Eastern, the local listening URL and Ollama endpoint were not reachable and no TTS/OCR model process appeared in the GPU listing. The audio files remain on disk and the completed Drive deliveries remain recorded. The handoff provides the restart helper; old saved PIDs are not current process authority.

The starter prompt explicitly describes the four-clip private casting experiment and its intended Drive delivery. It is a draft for Paul to submit in the new chat, not an independent instruction to perform the new upload before he sends it. No production casting change or general distribution exception is implied.

## 30. Authorized Casting Pilot Completed and Delivered, September 9

Paul submitted the starter request, authorized the local experiment with existing samples, and explicitly authorized upload of its four finished synthetic WAVs and guide into a new private subfolder of the existing follow-up folder. Work ran directly in D:/Audiobook_Pipeline. Graft map, source queries, skeleton and callers supplied context before production-planner lookup. No production source or graph rebuild was needed.

The completed [12 Casting pilot 2026-09-09](https://drive.google.com/drive/folders/1BCxi_dA8UuOPMP1f1igzi3qrndHY6sVb) contains exactly four WAVs (9,705,912 bytes, 202.20 seconds total) and START_HERE.txt (1,872 bytes). Connector readback verified names, sizes, counts and private status. Its only folder permission is the owner. Source samples, source transcripts, private plans/mappings, raw chunks, diagnostic pairs, model assets and book files were not uploaded. The completed receipt is `Output/TTS_Comparison_20260908/casting_pilot_20260909/drive-upload-receipt.json`. Local SHA-256 hashes record provenance; remote hashes were not independently fetched.

The 147-word original synthetic scene has natural contractions and purposeful full-form emphasis, with twelve manually assigned intact role paragraphs. The existing production build_plan(profile A) gives the same text, boundaries and 650 ms paragraph pauses in both arms. Current original English Chatterbox at neutral defaults compares the same established narrator reference for every role against that narrator with fixed Lena/Daniel references. Seeds 1209 and 2209 are matched by canonical character offset. Every planned take was retained; forty unique calls generated the four scenes, with the four narrator raw segments reused exactly within each seed's two arms. This isolates references within a manual role structure; it is not automatic attribution, persistent emotional state or byte-exact production batching.

Four alternative references were inspected with CPU ASR and waveform/spectrogram checks, and two complete-phrase copies selected privately. Source hashes were preserved. No subjective voice-cleanliness claim is made: the session could not ingest audio. Quiet boundaries and no obvious persistent backing at the inspected scale do not prove a single speaker, lack of subtle music/reverb or intact audible phonemes. The narrator remains the exact corrected crop used previously, avoiding a narrator-reference change between arms.

Retained diagnostic scenes reconstruct bit for bit. Qwen continuity_142 chunk 04's fade overlaps strong terminal audio at 20.330 to 20.360 seconds and reduces its final 30 ms by 3.84 dB. That demonstrates attenuation, not a heard repair. All ten current-English continuity_242 fades lie in measured quiet tails, so the reported roughness remains unexplained. Same-sample terminal-fade diagnostic pairs and CPU evidence are retained locally. The pilot uses zero fades in both arms, keeping all returned samples, padding and planned pauses, followed by constant level-matching gain. This prevents added attenuation of generated endings but cannot repair missing generated phonemes. Production assembly is unchanged.

All forty calls reached EOS in 44 to 164 tokens. Sample-exact assembly, all inserted silences, four distinct final waveforms, reference/seed routing and constant gain mapping passed. The four final 24 kHz mono PCM16 WAVs measure -23.51 to -23.50 LUFS and at most -2.39 dBTP, without amplitude saturation. All raw tails have 90 to 420 ms below the speech-relative activity threshold, with no final-30-ms flag and maximum endpoint step -59.86 dBFS. An independent reviewer passed nineteen checks including delivery metadata privacy.

Initial CPU ASR checked all forty raw chunks and four final scenes. Two raw omission flags recovered in full scenes and focused recognition. Independent greedy Wav2Vec2 and alternate focused Whisper recognition confirmed those passages and did not reproduce an apparent extra here from one full-scene transcript. No audio was regenerated. Remaining name/word-boundary spelling variations are not demonstrated spoken errors. Word recognition and quiet endpoints do not establish acting quality or complete audible word endings.

New local evidence is entirely under ignored `Output/TTS_Comparison_20260908/casting_pilot_20260909`. README.md, CONTENT_QA.md, private plan/mapping, raw/assembled/delivery directories, reference/diagnostic records, provenance and verification reports preserve the method. HANDOFF_NEXT_SESSION.md section 16 is the active continuation record, with prior handoff/project-state copies saved inside the pilot.

R and S keep the same concealed casting assignments in pair one (01 versus 02) and pair two (03 versus 04). Owner listening and acceptance are pending. Keep the mapping private until feedback; a pair may have no winner. The previous V3 standout remains a reused quality reference, not a fresh success. No cast, reference, engine or ending treatment is promoted to production. All sixty-four tracked starting files retain their original hashes, including pre-existing edits. No Git write, branch/worktree change, existing job mutation, package/model installation, release build or publication occurred. Release validation remains a separate task.

## 31. Casting Pilot Owner Verdict, September 9

This supersedes section 30's pending-listening status. Paul supplied all four notes before the mapping was disclosed. Saved mapping, listening manifest and unchanged audio hashes matching the completed Drive receipt confirm R is the cast (established narrator plus fixed Lena/Daniel references) and S is the same established narrator used for every role, both in current original English Chatterbox.

Pair 1 R had robotic female-role cadence around 0:17 and slightly unnatural Daniel delivery around 0:47, but was not bad overall; Paul tentatively preferred its multiple narrators. Pair 1 S had robotic cadence around 0:30 and was not horrible overall. Pair 2 R was mechanical, uncanny and soulless. Pair 2 S was fantastic, with an all-around thumbs up. Exact wording is in `Output/TTS_Comparison_20260908/casting_pilot_20260909/owner-feedback.json`, with analysis in LISTENING_VERDICT.md.

The strongest result is a newly generated single-narrator performance. Keep Pair 2 S and assembled/single_2209.wav as an accepted quality reference. Neither setup has demonstrated dependable naturalness across these two takes; fixed cast voices did not prevent the rejected second performance. Do not reduce the result to one win per arm, infer a generally good seed, or count replaying this successful file as another success. The different strengths of the two preferences matter.

Read-only timestamp attribution maps Pair 1 R's 17-second complaint to Lena's 13.03 to 17.71 second turn, and its 47-second complaint to Daniel's 44.70 to 47.74 second turn. Narration returns at 48.39. Pair 1 S's 30-second complaint lies in the semantic Lena turn from 26.62 to 30.70, followed by narration at 31.35. owner-timestamp-context.json retains exact chunk spans, nearby synthetic text, approximate ASR timing and hashes. No new listening, ASR or audio generation was done for these timestamp lookups.

The practical next baseline is the single-narrator pilot configuration, with repeatability on a fresh short scene and predetermined seeds as a proposed next test. Sampling mechanisms and causes of robotic cadence are not isolated. Because natural text, role segmentation and zero fades are shared across all four new clips, this pilot cannot credit one of those changes for the standout versus earlier rounds. Positive overall acceptance of one clip does not establish a general ending/reverb fix or authorize production changes.

HANDOFF_NEXT_SESSION.md section 17 is the active continuation record. Original generation plans, blind-at-delivery mapping, verification and delivered audio remain immutable; new feedback records carry the current status. No production setting, job, source reference, prior audition, Drive file, branch or release changed. No further renders or uploads began in this feedback turn.

The owner clarified that occasional cast unnaturalness came from almost imperceptible word separations, instead of the natural flow of one word's ending into the next. `owner-clarification-connected-speech.json` preserves the wording. Treat connected-speech flow, linking/coarticulation and phrase rhythm within a turn as explicit quality criteria. Whole dialogue turns are generated in single calls; no per-word clips or inserted gaps exist in this pilot. The specific cause inside the returned audio is unmeasured, and this does not authorize word crossfades, indiscriminate silence removal or any new generation. The prior four-file preference remains unchanged.

## 32. Authorized Fresh-scene Repeatability Test, September 9

Paul requested the next implementation step. The new local set under ignored `Output/TTS_Comparison_20260908/connected_speech_20260909` contains three fresh single-narrator takes of At the station, plus the byte-identical accepted Pair two S reference and a listening guide. The 152-word original synthetic scene has twelve whole role paragraphs with contractions and purposeful emphasis. Three predeclared seeds produce 36 retained calls without replacements. Exact prior reference, engine/runtime/source/weight hashes, neutral settings, per-offset seeding, planner/profile and zero-fade sample-preserving assembly remain fixed. This tests short-scene repeatability/generalization; it implements no connected-speech repair or production feature.

The four PCM16 mono 24 kHz WAVs total 189.16 seconds and 9,079,992 bytes. T is 46.91 seconds, U 46.31 and V 47.35; the reused anchor is 48.59. Levels span -23.51 to -23.48 LUFS with maximum true peak -2.81 dBTP. All 36 raw calls reach EOS in 33 to 130 tokens. Raw/metadata/token/reference hashes, every assembled sample/silence, constant-gain mapping and anchor identity pass checks. CPU recognition checks all 36 raw chunks and three final scenes; all three full scenes match the normalized expected words. Five isolated raw flags recover in full-scene context, with additional content and independent-review evidence retained. No audible naturalness or complete-phoneme acceptance is inferred from those checks.

The parallel CPU diagnostic compares six prior utterances and preserves all source hashes. One low-energy candidate near Pair one R's "everything / alone" occurs at scene 17.065 to 17.100 seconds, 35 ms at the main threshold and 15 to 45 ms across thresholds; no corresponding interval appears at that boundary in the accepted counterpart. Other inspected contexts lack the same pattern, and an accepted within-word trough is longer than in the complained version. This supports one focused listening target, not blanket silence deletion or a causal coarticulation diagnosis. Approximate CTC alignment, reference/seed confounding and lack of agent audio perception remain explicit limits in the diagnostic report.

Independent unprompted greedy Wav2Vec2 recognition also recovered all five raw flagged passages, with only the name-spelling variation Lena/LEENA. diagnostics/CONTENT_QA.md and content_followup.json preserve the automated coverage evidence. The independent review passed 27 raw/delivery checks, including exact placement/silence, half-LSB final gain mapping, anchor identity, concealed mapping, metadata privacy and tracked-file preservation. Its separate ebur128 loudness check also confirms close interclip matching; filter-specific values and limits are recorded in independent-review-private.json.

HANDOFF_NEXT_SESSION.md section 18 is current. The new T/U/V mapping stays private until verdict. Owner listening is pending: rate each new take acceptable/borderline/unacceptable, with word-flow and acting timestamps. The reused anchor is excluded from the three new trials; three acceptable short takes would justify only a longer test. The new delivery directory contains four WAVs and a 2,070-byte guide, prepared locally. It has not been uploaded; the earlier Drive permission named the original casting set. All 64 tracked file hashes and existing edits are preserved. Production settings/jobs, source samples, prior auditions, packages/models, Git state and releases remain unchanged; no release validation is claimed. Before-update handoff/project-state copies are preserved in the new root.

## Drive delivery completed, September 9

Paul explicitly authorized the new upload with "Yes please. Upload to Google Drive." The new set is now delivered in [13 Single-narrator repeatability 2026-09-09](https://drive.google.com/drive/folders/1ZZvKHDWMfYZ_iJIkVL7wD9gzH38GJRmK), under the existing Narration followup folder. This supersedes the earlier local-only status and upload-permission requirement above. Connector readback verified exactly four finished WAVs (9,079,992 bytes) and START_HERE.txt (2,070 bytes), matching all expected names and sizes. The folder has only the owner's permission and all five files report not shared. No source reference, raw chunk, diagnostic, private mapping or book content was uploaded. drive-upload-receipt.json in the connected_speech_20260909 root preserves the completed result; remote content hashes were not independently fetched. The accepted anchor remains reused evidence, the T/U/V mapping remains private, and owner listening is the next action.

## 33. Repeatability owner verdict: all new takes fantastic, September 9

Paul returned home and said "All sound samples sound fantastic." This accepts all three fresh T/U/V takes and the retained reference in the current set. It is not a revision of older rejected auditions. No ranking, problem timestamp or separate word-flow/acting score was supplied. Exact feedback is in connected_speech_20260909/owner-feedback.json and the current interpretation in LISTENING_VERDICT.md.

All three predeclared-seed fresh readings of At the station meet the experiment's short-scene listening criterion. This is consistent acceptance within the tested scene and the strongest repeatability evidence yet for the established current-English single-narrator setup. The accepted anchor is reused and adds no new trial. The original first single-narrator casting take remains flawed; no universal seed quality or full-book reliability is inferred.

The post-verdict mapping is T = 4209, U = 3209, V = 5209. All use the same narrator reference/configuration. The four delivered file hashes and mapping were verified before feedback was saved. Original plan, mapping, raw/final audio and technical evidence are unchanged; their pending/concealed statuses are historical and superseded by this verdict record.

Keep the exact accepted setup as the short-scene baseline. The next useful test is a longer naturally written passage containing sustained narration, returning dialogue and emotional changes, with predetermined takes and the same configuration. No new generation begins from this feedback alone. Long-form consistency, a causal connected-speech repair and production acceptance remain unestablished.

Delivery preference has changed: Paul is home and no longer needs Google Drive for new samples. Use local delivery unless he requests otherwise. The prior authorized upload is already complete and remains untouched; no deletion was requested. No production source/settings, existing job, reference, prior audio, branch or release changes in this feedback turn.

## 34. Authorized longer two-take trial prepared locally, September 9

After all three short-scene takes were accepted, Paul asked what was next and then authorized the proposed longer passage with "Let's do it." The completed trial is under ignored Output/TTS_Comparison_20260908/longer_passage_20260909. Owner listening is pending. The local player is http://127.0.0.1:8796/longer_20260909/ and the WAVs plus START_HERE.txt are in delivery/. LISTENING_NOTES.md gives optional timestamp checks without revealing the seed mapping. No Google Drive upload was made, following Paul's local-delivery preference.

The workshop is an original 992-word synthetic passage in 36 whole role paragraphs, with sustained narration and returning Daniel/Lena dialogue moving through light conversation, frustration, grief and warmth. Two seeds were declared before generation and all 72 calls retained without replacement. The exact accepted narrator/reference source, current original English Chatterbox, runtime/model/source hashes, neutral settings, reference preparation seed, per-offset seeding, build_plan profile A and zero-fade sample-preserving assembly remain unchanged. Each paragraph fits in one call, maximum 278 characters; 650 ms planned paragraph gaps remain fixed. No persistent acting state, automatic attribution or production batching was introduced.

| Listening file | Duration | Bytes | LUFS | True peak dBTP |
| --- | ---: | ---: | ---: | ---: |
| 01 Longer take W.wav | 300.07 seconds | 14,403,438 | -23.49 | -2.79 |
| 02 Longer take X.wav | 296.15 seconds | 14,215,278 | -23.50 | -2.85 |

Both files are mono 24 kHz PCM16. W is 70 ms beyond the strict five-minute target, recorded explicitly rather than trimmed or stretched; the player displays 5:00 and 4:56. There is no reused reference in this two-file test. Keep the W/X seed mapping private until the verdict.

All 72 calls reached actual EOS in 33 to 384 tokens. Raw text/reference/plan/token hashes, every assembled sample/silence and constant-gain mapping pass. Separate checking code passed thirteen checks, reconstructing each final directly from raw within half a PCM16 unit, checking metadata privacy, all 64 tracked starting-file hashes and both prior listening sets. This is separate code in the same session, not another agent's or human's review. HTTP readback of the two WAVs, guide and page matched exact bytes/hashes; browser controls loaded the correct durations, played, paused the other take automatically, and reset to zero. No assistant auditory quality claim is made.

Word-fidelity acceptance is NOT passed. CPU small.en checked 72 raw chunks and both final scenes: eighteen raw chunks flag differences, with twelve full-scene difference operations in W and nineteen in X. Independent unprompted greedy Wav2Vec2 checked 32 affected utterances. Some opening omissions and apparent full-scene additions do not reproduce, but possible substitutions persist across recognizers, including said/set in both takes and you/he, they were/they're, I'd still rather/it's still ready and that/them in X. Name/articulation ambiguities also remain. These are listening concerns, not confirmed audible errors. See CONTENT_QA.md, LISTENING_NOTES.md and the two initial plus follow-up ASR reports.

Two raw tails trigger the narrow last-30-ms energy flag, near W 0:28 and X 3:58. Both closing phrases are fully recognized by both raw recognizers; no sample was removed or faded. The inspected endpoint figure shows low-level terminal energy rather than establishing a clipped phoneme. Final endpoint-step estimates at those joins are approximately -49.93 and -63.47 dBFS. Do not use this alone to justify editing tails or declaring them inaudible.

Next action is owner listening to EACH full take, rating acceptable, borderline or unacceptable with timestamps for wording, voice drift, emotional transitions, word linking, rough endings and fatigue. Both must pass before a chapter-length trial is justified. Neither take has been accepted yet. Production source/settings/jobs, source samples, earlier audio, packages/models, Git state and releases are unchanged. No release validation or graph rebuild is claimed; new harnesses and evidence are ignored local files. Prior handoff and project-state copies are preserved here as *.before-longer-trial.
