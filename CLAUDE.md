# Local PDF to Audiobook Pipeline — Standing Rules

Personal project. Local build on my own hardware, for legally purchased books, personal use only.

## Hardware and environment

RTX 4090 (24 GB VRAM), i9-13900K, 32 GB RAM, Windows, Anaconda. Driver supports CUDA 13.3.

GPU concurrency rule (revised 2026-07-24): DIFFERENT stages never overlap on the GPU. OCR (Ollama) and TTS (Chatterbox) must not run at the same time; the running stage owns the whole GPU. That part has never changed.

What changed on 2026-07-24 is HOW the narration stage fills the GPU. The default engine is now "batched": ONE process that puts several text chunks into a single T3 forward pass. It deliberately runs a single worker, because on Windows extra CUDA processes only time-slice against each other (no CUDA MPS), so multiprocessing bought almost nothing. See the batched engine section below.

The older multi-process design is still there as engine="parallel" and still sizes its worker count to VRAM (each worker ~9-10 GB; 4090 -> 2 workers, 12 GB card -> 1, CPU/unknown -> 1). Keep it as the fallback, not the default.

Project root: D:\Audiobook_Pipeline. Conda envs and the fish-speech repo live OUTSIDE this root so data cleanup can't touch model code or weights.

## Ollama version (auto-update ON, version drifts on its own)

The old hard rule (never upgrade, stay on ~0.24.x) is RETIRED as of 2026-07-26: the upstream
qwen2.5vl:32b projector bug is fixed, both extraction models were re-tested on the 0.32.x line,
and auto-update is back on.

- Never record an exact patch version and treat it as authoritative; get it fresh with `ollama --version`.
- Extraction is the stage most exposed to an unannounced upstream change. If OCR output suddenly
  degrades or a model stops loading, check whether Ollama moved BEFORE debugging pipeline_text.
- The project never installs, upgrades or configures Ollama from its own scripts. Scoping decision
  (optional, Path B only, shared with other projects), not a safety rule.

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

## Current validated state

Remote is github.com/Lipton1010/Audiobook-Studio. Keep the repo deliberately MINIMAL: one branch
(master) and one tag (v1-parallel, the pre-batched-engine rollback point). Delete feature branches
once merged; branch clutter is what caused stray commits. Check real git state with `git log` and
`git status` rather than trusting any snapshot written down here.

- Checkpoints 0, 1, 2 validated (extraction on DMG test pages, Path A on Project Hail Mary,
  Chatterbox voice cloning proven).
- Checkpoint 3 complete: page-number leak fix verified on a real harvest rerun (all 7 pages clean).
- chunk_and_narrate.py (Path A) and narrate_tagged.py (Path B) remain as validated standalone
  scripts. Tuned pauses: Path B 50ms intra-block, 100ms inter-block, 200ms/150ms heading
  before/after; Path A 150ms chunk gap, 400ms paragraph gap; 30ms fades.

## Audiobook Studio app (built 2026-07-21)

D:\Audiobook_Pipeline\app\ is a local web app wrapping the whole pipeline, PDF to audiobook. Start it with D:\Audiobook_Pipeline\Start_Audiobook_Studio.bat, UI at http://localhost:8765.

- server.py runs in BASE miniconda (stdlib + fitz + requests only, nothing installed). One worker thread runs the STAGES strictly sequentially, so Ollama extraction and Chatterbox narration never share the GPU. engine="batched" (the default) launches exactly ONE narration process; engine="parallel" launches N, sized to total VRAM by narration_worker_count() (read the constants from server.py, they have gone stale in this file twice).
- Hardening (from a multi-agent adversarial review 2026-07-22): cancel flag is cleared on resume and popped by path-B extraction (was: a cancel during OCR made the job re-cancel forever until server restart); worker PIDs written to worker_pids.txt and reaped on startup (Windows does not kill children when the parent dies); segment temp files are PID-unique (seg_NNNNNN.tmpK_PID.wav) and swept every run so orphaned/fresh workers never collide or miscount; progress counts only finalized seg_??????.wav; resume ETA is measured over this-run work only; plan_hash includes the voice file's size+mtime so re-uploading a same-named voice invalidates old segments; assembly process is registered before its cancel check so a cancel in that window still kills it.
- Parallel narration design: work is split by chunk index modulo N (disjoint, no coordination, still skips existing segments so resume-safe). Server flow: ensure_segments_fresh (wipes segments if blocks/voice/PLAN_VERSION changed, via plan_hash.txt) -> launch N `narrate_worker.py --shard K --num-shards N` -> wait all -> one `--assemble` pass (no model load). Progress is computed server-side by strict-counting segments (seg_??????.wav, excludes temp files) vs plan_total.txt, aggregated across workers, with ETA measured over THIS run only (baseline = segments present at run start).
- MEASURED reality on the 4090 (2 workers, Power of the Dog), the finding that motivated the batched engine: only ~1.1x, NOT the ~1.8x first guessed. GPU shows 98% util at 14 GB VRAM, but per-worker sampling rate halves (55 it/s solo -> ~25 it/s each), i.e. the two CUDA processes TIME-SLICE rather than co-execute. Windows has no CUDA MPS (Linux-only), so multi-process gives almost no real parallelism. Real speedup needs batched inference (multiple sequences in one forward pass), which the current design does NOT do. Keep expectations low for parallel workers on Windows; the adaptive count is still correct-by-VRAM but the payoff is small here.
- pipeline_text.py: shared tagging/extraction. Carries the verified page-number filter plus: headings may end in ? or !, markdown emphasis stripped, whitespace collapsed, cross-page mid-sentence stitching, Path A prose mode (path_a.py x-indent rule, font-size-based drop-cap merge) and verse mode (sentence-run grouping), auto-detected by capitalized-line-start fraction (>0.45 = verse). HEADING_LINE_RE detects chapter divisions numbered as digits, roman numerals, OR spelled-out words ("Chapter One", "Chapter Twenty-One") plus standalone Prologue/Epilogue/Introduction/Preface/Foreword/Afterword; all-caps short lines are still headings via is_heading (this can catch rare in-story all-caps like "DANGEROUS", which get a heading pause but are NOT chapters since the worker's CHAPTER_RE only marks division words).
- narrate_worker.py runs in the chatterbox env as a subprocess. Per-chunk WAV segments make narration resumable. Output is ONE single file, DEFAULT m4b, chosen by config["format"] (m4b | mp3 | wav). m4b/mp3 are encoded by streaming raw PCM straight into ffmpeg (no giant intermediate WAV) at 64k AAC/MP3, mono 24kHz. m4b/mp3 carry navigable CHAPTERS: one per top-level heading (CHAPTER_RE = BOOK/CHAPTER/PART/CANTO/PROLOGUE/EPILOGUE/INTRODUCTION/PREFACE), written via an ffmetadata file; sub-section headings are not chapters. wav is the lossless master and is the only format that can split (only if it would top the ~4 GB WAV cap, ~22+ hr book; fallback_part_minutes default 240). ffmpeg is required for m4b/mp3 (chocolatey install present; find_ffmpeg falls back to that path).
- Jobs are per-job folders under app\jobs\. Path B caches per-page OCR .md so extraction also resumes. Finished parts are also copied to D:\Audiobook_Pipeline\audiobooks\<title>\.
- GLM-OCR degenerates on full-page ARTWORK pages (endless code fences, empty HTML tables, or looped short tokens). Guards in pipeline_text.tag_blocks: markup-only and code-fence lines dropped, consecutive duplicate body blocks collapsed, and any page whose blocks are >=20 with <30% unique text returns empty (art page). ocr_page caps num_predict at 4096. narrate_worker fingerprints the chunk plan and wipes stale segments if blocks change.
- Voice cloning: users can upload a voice sample in the UI (wav/mp3/flac/ogg, converted via convert_voice.py in the chatterbox env, soundfile only, trimmed to 20s) and pick a voice per job. Default voice is samples\Voice_Sample\male_ref.wav ("Default narrator (male sample)"). The rights rule above applies to uploads.
- Design decisions applied (were open threads 3/4): CHECKLIST FOR X sections get normal heading treatment; epigraphs stay plain body.
- Verified end to end 2026-07-21: 1-page Path B job produced 53.7s of real narrated audio through the UI. Full Odyssey extraction dry-run: verse mode, 4465 blocks, all 24 Book headings detected.

## Batched narration engine (default since 2026-07-24)

app/batched_narrate.py puts N text chunks that share one voice through a SINGLE T3 forward pass. It reproduces v1's per-sequence math (right-padded text so real tokens keep learned positions 0..T_j-1, CFG as a 2N-row block-ordered batch, explicit position_ids from cumsum(mask)-1, per-row EOS with finished rows frozen to a safe one-hot). Quality is verified: byte-identical tokens to the old parallel engine. S3Gen batches a bucket when there is more than one valid row and trims every result to its real token length; one-row buckets use v1's exact path.

- Selected by config["engine"] ("batched" default, "parallel" fallback). server.py DEFAULT_ENGINE reads env AUDIOBOOK_ENGINE. The batched engine runs ONE process on purpose.
- VRAM safety is a TOKEN BUDGET, not a fixed batch size: buckets cap rows*Tmax at BATCH_TOKEN_BUDGET (default 1300, cap BATCH_SIZE 12). A fixed count OOM-thrashed and looked like a hang ~62% into a book once chunks got long. On the 4090 the longest chunks land at N=4, medium ~N=8, short at the 12 cap.
- HONEST SPEEDUP, do not overstate it: ~2x on a full book, and it is chunk-length dependent. Short/medium chunks hit ~3-4x; long chunks near CHAR_CEILING 400 are compute-bound AND forced to small batches, giving only ~1.1-1.2x. Earlier versions of this file said the budget was over-conservative and that S3Gen was "~15% of gen time and overlappable"; BOTH were measured and disproved on 2026-07-26, see the next section.
- batched_generate frees the kv-cache and calls torch.cuda.empty_cache() before vocoding. This is load-bearing: without it the reserved pool climbs across buckets and pushes S3Gen onto cudaFree-and-retry (one 728-token chunk took 95s instead of 0.87s).
- A bucket runs until EVERY row hits EOS, so one row that never emits EOS still makes the bucket run to max_new_tokens. CORRECTED 2026-08-04, this used to say "output stays correct, only throughput suffers" and that is FALSE: a runaway row once vocoded its padding as 21.4 seconds of audible DEAD AIR. The worker now blocks capped rows before vocoding, retries only that row in isolation up to three times, and fails resumably rather than writing bad audio if every retry caps. The dependency-free safety logic is regression-tested; a fresh CUDA production run remains a release validation gate.
- app/ab_*.py are the A/B harness and self-tests used to prove equivalence. Keep them.

## Measured findings, dead ends, and traps (compressed core)

Full evidence lives in the extraction-narration-investigations skill. This is the part that must
never be re-derived from intuition.

MEASURED DEAD. Do not propose either again without new evidence.
- OVERLAPPING S3Gen WITH T3: ceiling 1.52x, real implementation delivered 1.09x. T3's decode loop is
  launch-bound Python and a vocoder thread contends for the GIL; Windows has no CUDA MPS.
- RAISING BATCH_TOKEN_BUDGET: 1800 measures 0.96x against 1300 on real chunks. 1300 is the sweet
  spot. Peak VRAM is NOT the binding constraint (peaks ~8 GB of 24); per-row compute is.

BENCHMARKING RULE. Always build chunk lists with `narrate_worker.build_plan`. Three separate
benchmarks gave wrong answers by tokenizing raw blocks.json text (792 tokens) instead of real chunks
(~271). Never hand `batched_generate` an unbudgeted batch. Sample BUCKETS, not chunks, and sample
across a whole book: chunks run sorted short-to-long, so the head is S3Gen-bound and the tail
T3-bound. A 40-bucket sample predicted a full 994-bucket book to within 2%.

S3Gen IS STOCHASTIC. Two serial calls on identical tokens produce different audio (correlation ~0.2).
Waveform diffing cannot validate any vocoder change, and "the output changed" is not a bug report.
The byte-identical guarantee covers T3 TOKENS only. Judge vocoder changes by listening, or by
comparing batched-vs-serial spectral distance against serial-vs-serial.

ALLOCATOR STALL, undiagnosed. ~0.2% of buckets take 10-20x longer than neighbours doing more work,
at low reserved VRAM. Matches the cudaFree-and-retry signature that `empty_cache()` in
batched_generate exists to avoid. A few percent of runtime, no correctness impact.

PARAGRAPH DETECTION IS ADAPTIVE AND IMPLEMENTED (2026-08-03, app/pipeline_text.py).
`detect_paragraph_style` probes 24 pages and returns "indent" or "gap"; the vertical-gap fallback
fires only when indented lines are rare. Verse cannot see the change by construction. Verified:
PHM and The Odyssey byte-for-byte identical; Power of the Dog 726 -> 9,490 blocks with non-whitespace
characters IDENTICAL (905,525 both) and all 16 CHAPTER_RE marks unchanged. Any future change to this
rule must be checked the same two ways: character preservation AND chapter marks. Block counts alone
can look right while text is being dropped.

THROUGHPUT: the paragraph fix is FASTER, 0.86x. 2.82x more chunks became only 1.61x more forward
passes, because short chunks fill the 12-row cap. Confirmed by a full book: Power of the Dog
re-narrated in 1.646 h of generation against a 1.613 h prediction. THE OLD "3.1 hours for PotD"
FIGURE IS RETIRED: it came from a partial job running at N=2 rows with a fixed batch_size, a
different batching regime. Do not use it as a reference again.

CHAR_CEILING 400 IS ALREADY SOFT, not an invariant (`pack_text` appends its trailing buffer without
rechecking; real max chunk is 531). Only 19 of Power of the Dog's 5,024 dialogue turns exceed 400.
Do not raise it as a side effect of some other change.

DELIVERY PARAMETERS: production applies NO expressive profile, and that is correct. Blind listening
established that keeping a speaker turn whole beats splitting it on semantic beats (Stage 0), that
exaggeration=0.7 / cfg_weight=0.35 beats the neutral defaults on a 480-char turn (Stage 1), and that
the same profile LOSES to neutral on 7-55 char turns (Stage 2). The benefit is length dependent and
99.6% of turns are short, so applying it to all dialogue would make things worse. If ever revisited,
gate it on turn length and prove the gate on a length sweep first.

Recovered paragraph boundaries WON on listening (Stage 2): one-speaker-per-call went 0.7% -> 56.2%
and split turns 22.9% -> 2.4%.

THE NOMINAL PAUSE IS NOT THE AUDIBLE PAUSE. Chatterbox adds a MEASURED 380 ms of its own padding
across every join (180 ms leading + 200 ms trailing, measured on 402 real segments and confirmed
independently in the assembled file). So `block_gap_ms` 400 sounds like 780 ms. Any future pause
tuning must subtract 380 first; reasoning about the nominal number alone will be wrong by roughly
half. Pauses are inserted at ASSEMBLY, so changing them needs no re-narration, only a reassembly.

`block_gap_ms` IS NOW 650 (2026-08-04), settled by two blind rounds on Power of the Dog. Round 1
offered 400/510/650 and everything sounded "incredibly similar" because the span was only 32% and
duration discrimination in continuous speech needs roughly 20-25%; that was a bracket-design error,
not a listening limit. Round 2 offered 650/900/1200 with each step above threshold, and 650 won
clearly, with 900 called "too long" and 1200 "way too long". 650 therefore beat 400 and 510 from
below and 900 and 1200 from above, so it is bracketed, not a boundary artifact. `gap_ms` stays 150.

WHY THOSE VALUES, measured against the commercial Audible recording of the SAME book (timing
statistics only, no content): their sentence-band median is 480 ms and our chunk gap is audibly
530 ms, so `gap_ms` needs no change. Their paragraph-band median is 890 ms and their p90 is 1030 ms;
the owner's chosen 650 is audibly 1030 ms, i.e. their p90 rather than their median.

THE REAL REMAINING GAP IS STRUCTURAL, NOT MAGNITUDE. The commercial narrator spends 6.1% of gaps in
the 1200-4700 ms range for scene and section breaks; we spend 0.1% and effectively stop at 1.1 s. We
have exactly two body pause values and no concept of a scene break. Scene breaks should be
detectable from the same page geometry `_modal_leading` already measures, at roughly 2.5x leading
rather than the 1.5x that marks a paragraph, and an audition can inject them at assembly without
re-narrating anything. Untested. Do NOT substitute a bigger uniform gap for this; that is exactly
what round 2 rejected.

OPERATIONAL TRAP, has cost a wasted run: `worker_loop` SKIPS extraction whenever blocks.json exists,
so changing pipeline_text and resuming an existing job has NO effect. DELETE blocks.json to re-extract
(the per-page OCR cache survives), or create a fresh job. Spoken text/type changes invalidate segments;
source-page, chapter, and assembly-only metadata do not. Always audit blocks.json on disk after a resume.

## Portable configuration

Two things about app/config.py that are easy to get wrong:
- setup.py WRITES chatterbox_python into app/config.json at the end of a successful install (2026-07-26). Detection is a fallback now, not the primary path, and its last-resort return value is still the original author's hardcoded path, which is wrong on every other machine. If someone reports the app cannot find the chatterbox env, check whether config.json got written before debugging the detection order.
- CFG.ffmpeg_path() RUNS ffmpeg rather than testing that the file exists, and caches the result. Pass refresh=True after installing one. Existence checks are what let a broken ffmpeg look healthy.

## Rulebooks and other designed layouts (learned on the 2024 DMG)

Two-column reference books are a different document class from novels and verse, and they broke four things. All four fixes are in; this section exists so the same ground is not re-explored.

- USE PATH B, even when the PDF has a perfect text layer. Path A's paragraphing relies on the x-indent rule, and a two-column rulebook has no first-line indents, so every LINE becomes its own block, drop caps orphan ("UNGEONS & DRAGONS"), and columns interleave out of order. suggest_path already routes multi-column pages to B on its own; trust it. GLM-OCR is faithful here, measured at 0.95-0.98x of the text layer's character count.
- OPERATIONAL TRAP, cost a wasted narration run: worker_loop SKIPS extraction whenever blocks.json exists. So changing pipeline_text and resuming an existing job has NO effect, and plan_hash cannot save you because the blocks it hashes are never regenerated. To apply an extraction change to an existing job, DELETE blocks.json and resume; the per-page OCR cache in pages\ survives, so it costs re-tagging only, no re-OCR. Always audit blocks.json on disk after a resume rather than assuming the fix landed.
- Path B tagging guards added for this class of book: running headers ("CHAPTER 6 | COSMOLOGY", filtered by the pipe form only, so real chapter openers survive because they emit "CHAPTER 6" and "COSMOLOGY" as separate pipe-free lines); dice tables (a "1d20 Claim to Fame" header plus 3+ numbered rows, where SHORT fragment rows collapse to one marker but LONG rows that are real prose merely tabulated are kept with roll numbers stripped); diagram pages (many short distinct labels AND under 900 total chars, the volume ceiling being what stops it eating a random-tables page); and raw HTML tables, which OCR emits on a few pages and which the markup-only guard cannot catch because the cells contain real words.
- rasterize_page has a 12 megapixel budget. Fold-out pages exist: DMG page 154 is a 4934x7000pt map that rendered a 107 MB JPEG at 200 dpi and made Ollama return 413, killing extraction 148 pages in.
- CHAPTER MARKS CAN GO MISSING from detected headings when OCR does not transcribe decorative chapter numbers. New extractions now retain 1-based source-page provenance, the server persists the PDF outline, and assembly uses selected outline divisions when they provide more chapter marks than detected headings. Destinations map to the first real narrated chunk on or after the outline page. This is regression-tested on synthetic mappings but still needs an installed-build M4B navigation check on a real book before release.
- Expect frequent omission markers in table-dense chapters. That is the extraction rule working, but it is audible, so listen to a table-heavy stretch before committing to a long book.

## Repo hygiene (history scrub completed 2026-08-04)

ab_samples/ was tracked in the PUBLIC repo and contained real book prose, including an explicit
excerpt. `git rm --cached` on 2026-08-03 removed both files from HEAD. On 2026-08-04 all local refs
were rewritten to remove `ab_samples/ab_chunks.json` and `ab_samples/README.txt`, rewrite backup
and Codex checkpoint refs were removed, reflogs expired, and unreachable objects pruned. Verification
found zero path hits across all remaining refs and both former blob IDs absent from the object
database. A full pre-scrub bundle is preserved under ignored `Output/` and was verified before the
rewrite. The force-push used an explicit lease against the inspected pre-rewrite remote SHA and
updated public `master` successfully. POST-PUSH GATE: GitHub still advertises four read-only PR refs
(`#1` through `#4`) that retain the old history, and direct API lookup of the former blob still
succeeds. The repository reports zero forks. GitHub Support must dereference those PRs, run server
garbage collection, and remove cached views before a public Release. A sweep of all tracked files
found no other book prose.

## Release stabilization (approved 2026-08-04)

- `tests/` is the dependency-free regression suite for runaway-token recovery, source-page
  provenance, outline chapter mapping, segment-hash migration, and completed-job cache cleanup.
- Segment hashes are now prefixed `v2:` and exclude assembly-only metadata. A matching legacy hash
  migrates in place without deleting validated segments; spoken text, voice, or planner changes
  still invalidate them.
- Completed jobs expose safe segment-cache cleanup. It removes only resumable PCM segments and
  preserves the job record, blocks, logs, job-local finished audio, and copied audiobook.
- `AGENTS.md` is the tool-neutral entry point and `RELEASE_CHECKLIST.md` is the mandatory release gate.

WINDOWS-ONLY GIT WRITES. Working-tree files are CRLF while HEAD blobs are LF, reconciled by
core.autocrlf. A git run from a Linux shell or container reports ALL tracked files as modified, and
`git add -A` / `git commit -a` / `git stash` / `git checkout` from such a shell would commit CRLF
into every one of them. Use `git diff --ignore-cr-at-eol` to see the real change set, and do git
writes on Windows only.

## Where the rest of the detail lives

This file used to carry every measurement and audit inline, which cost ~37k tokens of context in
every session. The full verbatim history now lives in skills that load on demand. Nothing was
deleted; load the relevant one before working in that area.

- `installer-release` - setup.py, the one-click Inno installer, both independent audits, the pinned
  Miniconda, the Windows Sandbox display crash, physical-PC install failures, the Release procedure.
- `extraction-narration-investigations` - the full measurement writeups behind the compressed core
  above: performance measurements, dialogue-boundary analysis, the Path A paragraph root cause, the
  adaptive-detection implementation and its gates, the throughput benchmark, the PotD re-narration.
- `narration-auditions` - CosyVoice 3 and Fish Audio S2 evaluations (both rejected and deleted), the
  performance-director design, and the Stage 0/1/2 blind listening methodology with full verdicts.
- `book-notes` - per-book page ranges and completion records, plus the Shining edition analysis.
- `beta-field-reports` - HP Omen evidence, the Shining/Sphere job reports, and the local UX changes.
