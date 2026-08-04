---
name: extraction-narration-investigations
description: Full measurement writeups behind the pipeline's current behaviour: the 2026-07-26 narration performance measurements and dead ends, the dialogue-boundary analysis, the Path A paragraph root cause, the adaptive paragraph-detection implementation and its verification gates, the throughput benchmark method, and the Power of the Dog re-narration. Load before changing chunking, batching or paragraph detection.
---

Full verbatim writeups migrated out of CLAUDE.md on 2026-08-04. CLAUDE.md keeps a compressed core of the operative rules; this file is the evidence behind them.
<!-- CLAUDE.md lines 93-104 -->
## Narration performance: what was MEASURED (2026-07-26)

Measured on the full Odyssey run (472 buckets, verse, 4618 chunks, 66.7 min). Read this before proposing any narration speedup; three plausible ideas were tested and two are dead.

- WHOLE-BOOK SPLIT: T3 59%, S3Gen 41%. The split swings hard with chunk length, so never quote a figure measured on one end of a book. Chunks are processed SORTED SHORT TO LONG, so the head of a book runs at N=12 rows where S3Gen is ~67% of the time, and the tail runs at N=5 where T3 is ~75%. An early sample of the head gave "S3Gen is 67%" and was wrong for the book as a whole.
- OVERLAP S3Gen WITH T3: DEAD. Ceiling for the measured mix was 1.52x; a real implementation (vocoder on a separate torch.cuda.Stream in a worker thread) delivered 1.09x, i.e. 17% of the available gain. Same lesson as the multi-process engine: on Windows the GPU plus the GIL does not co-execute the way the arithmetic suggests. T3's decode loop is launch-bound Python, so a vocoder thread contends for the interpreter. Not worth a thread, extra VRAM, and a conflict with the load-bearing empty_cache(). Do not rebuild it without new evidence.
- RAISING BATCH_TOKEN_BUDGET: DEAD. On real production chunks (max 400 chars, ~271 tokens) budget 1300 gives N=4 at 42.9s and budget 1800 gives N=6 at 44.7s, i.e. 0.96x, slightly WORSE. 1300 is already at the sweet spot; the earlier claim that the budget was over-conservative came from reading peak VRAM (5.2 GB of 24) rather than timing anything. Peak VRAM is NOT the binding constraint; per-row compute is.
- BATCHING S3Gen ITSELF: the one idea that measured positive, and it is now SHIPPED and ON by default (BATCH_S3GEN in narrate_worker.py and server.py, config key batch_s3gen, env AUDIOBOOK_BATCH_S3GEN=0 to fall back to the row-by-row path). seqs_to_wavs vocodes one row at a time, but flow.CausalMaskedDiffWithXvec.inference is genuinely batch-aware (token (B,n), token_len (B,), single-voice prompt broadcast by _repeat_batch_dim) and HiFTGenerator.inference is conv/istft only, so a padded batch works. Measured on real length-sorted buckets: 2.05x at N=12 falling to ~1.0x by N=3, 1.42x overall on the vocoder stage, projecting to ~1.16x whole book (10 min off 71). Note S3Token2Mel.forward's docstring still says "batch_size=1 only", which is stale but means upstream may not have validated it.
- S3Gen IS STOCHASTIC. Two serial calls on IDENTICAL tokens produce different audio (correlation ~0.2, matched lengths and RMS). So waveform diffing cannot validate any vocoder change, and "the output changed" is not evidence of a bug. This project's byte-identical guarantee is about T3 TOKENS only. Judge vocoder changes by listening, or by checking that batched-vs-serial spectral distance is no larger than serial-vs-serial distance.
- ALLOCATOR STALL, unexplained: roughly 0.2% of buckets take 10-20x longer than neighbours doing more work (one Odyssey bucket: 133s vs a 9s norm, at only 4.3 GB reserved), and two benchmark runs hit multi-minute versions. Cost was 3.3% of the Odyssey's runtime with no correctness impact. Matches the cudaFree-and-retry signature the empty_cache() comment describes. Not diagnosed.
- WHEN BENCHMARKING, USE narrate_worker.build_plan. Three separate benchmarks gave wrong answers because they tokenized raw blocks.json text instead of the production chunk plan: raw blocks reach 792 tokens while real chunks cap near 271, which is a completely different batching regime. And never hand batched_generate an unbudgeted batch; 12 unbudgeted rows filled the 24 GB card and thrashed.


<!-- CLAUDE.md lines 474-498 -->
### Dialogue measured on a real book, and the long-turn worry was WRONG (2026-08-03)

Measured on the completed Power of the Dog job's own `blocks.json` (job `fb547e0f`, 707 body blocks, 1,104,684 narratable chars, Path A prose). Read-only analysis, no GPU, no book text reproduced. Dialogue in this book uses curly quotes, 5052 opens and 5030 closes.

(V) TURN LENGTHS. 5024 closed quoted turns plus 28 paragraph-spanning opens. Dialogue is 178,383 chars, only 16.1% of narratable text. Length distribution: min 2, median 22, mean 36, p90 67, p95 108, p99 267, p99.5 353, max 1008. Turns over 400 chars: 19, which is 0.38% of turns and 6.1% of dialogue characters. Turns over 800: 3. Over 1000: 1.

CONSEQUENCE. The `CHAR_CEILING` blocker recorded in the Stage 0 section was overstated and is hereby corrected. Accommodating the single longest turn in an 818-page novel means touching about 19 chunks, so the 2026-07-26 finding that long chunks batch poorly barely applies. Note also that the ceiling is ALREADY SOFT: `pack_text` appends its trailing buffer without rechecking, and the simulated maximum chunk on this book is 531 chars, well over the nominal 400. Do not treat 400 as a hard invariant that must be defended.

SECOND CONSEQUENCE, and it cuts against the audition. The Stage 0 and Stage 1 passage has a 480-char character turn, which sits in the top 0.4% of turns in this book. Both auditions therefore demonstrated turn preservation on a RARE case. The principle stands, but nothing has been tested on the common case.

(V) THE ACTUAL DEFECT IS THAT `pack_text` IS QUOTE BLIND. Simulating the real production packer at ceiling 400 over the same body blocks yields 3537 chunks (the stored job recorded 3556; the difference is headings, which this simulation excludes), mean 312 chars, median 341. Classified by quote balance:

- 1806 chunks (51.1%) are narration only.
- 1329 chunks (37.6%) MIX one or more complete turns with narration, attribution, or another speaker's turn inside a single synthesis call under one parameter setting.
- 397 chunks (11.2%) SPLIT a turn across the chunk boundary, leaving unbalanced quotes.
- 5 chunks (0.1%) are exactly one complete turn and nothing else.

So of the 1731 chunks that touch dialogue at all, 99.7% have wrong delivery boundaries. That is a far better explanation of the owner's "dialogue sounds phony" report than the long-turn theory, and it is a structural defect present on essentially every page, not a rare edge case.

(V) BUT THE NAIVE FIX IS NOT THE ANSWER EITHER. Splitting strictly at turn boundaries gives 5024 dialogue calls plus 3735 narration runs, and repacking those runs at 400 gives about 5151, for roughly 10,175 calls against today's 3537, a 2.9x increase in call count. Worse, the short-turn distribution is brutal: 45.8% of turns are 20 chars or fewer, 18.4% are 10 or fewer, and 7.4% are 5 or fewer. Handing Chatterbox a two-character call is asking for artifacts, and Stage 0 already established that fragmenting a speaker turn hurts.

THE REAL TENSION, stated plainly so it is not rediscovered. Stage 0 showed fragmentation hurts and Stage 1 showed the expressive profile helps, but BOTH were measured on one long turn. Strict turn splitting is itself fragmentation for the two thirds of turns under 30 chars, and no experiment has touched that case. The evidence supports "do not blend a turn with narration in one call" and "do not split a long turn", and it is silent on what to do with a 12-character turn, which is the majority. Do not ship a turn-preserving packer on the strength of the Stage 0 and Stage 1 results alone.

Throughput is also unmeasured under the new call profile. 2.9x more calls but a much shorter median call could be roughly neutral, because CLAUDE.md's own measurements put short chunks at the N=12 row cap where batching pays 3-4x. Could be. Measure it, do not assume it, and use `narrate_worker.build_plan` per the benchmarking rule above.


<!-- CLAUDE.md lines 499-525 -->
### ROOT CAUSE: Path A destroyed 92.5% of this book's paragraphs at EXTRACTION (2026-08-03)

This supersedes the framing of everything above it. The dialogue problem is an extraction defect, not a narration defect, and the project's own standing rule ("don't debug extraction and narration at the same time; isolate which stage failed") was pointing at the wrong stage until this measurement.

THE TELL. Path A produced 726 blocks (707 body, 19 heading) for pages 5 to 818, which is 0.89 blocks per page. Mean body block length is 1562 chars and the longest is 9094. One block contains 42 separate quoted turns. 69.6% of body blocks hold 3 or more turns, and 97.4% of all 5024 turns live inside those blocks. Those are not paragraphs; they are pages.

(V, full scan of the source PDF with pymupdf 1.28.0, pages 5 to 818, 809 pages with text, 19,950 lines) `samples/path_a.py::page_paragraphs` starts a new paragraph only when a line's `x0` exceeds the modal left margin by more than 6 points. In this PDF **there is no indentation at all**: 19,856 of the ~19,870 lines sit at exactly x0 77.0, only 18 pages (2.2%) contain any line indented past the threshold, and those are a handful of stray centred lines. With no indent signal the rule degenerates to exactly one paragraph per page, which is precisely the 0.89 blocks per page observed.

(V, same scan) THE PARAGRAPH STRUCTURE IS FULLY PRESENT, just carried vertically instead. The line-to-line gap histogram is cleanly bimodal: 17.2 pt (modal leading) occurs 10,024 times and 34.5 pt, exactly twice the leading, occurs 8,757 times. That is a blank line between paragraphs. Counting intra-page gaps above 1.5x leading plus one paragraph per page recovers about **9,624 paragraphs against the 726 Path A emitted, a 13.3x under-segmentation**, and would bring mean paragraph length from 1562 chars down to about 115.

WHY THIS EXPLAINS THE COMPLAINT. Path A's validated pause profile puts 400 ms between blocks and 150 ms between chunks. With one block per page, the 400 ms paragraph gap fires roughly once every 66 seconds of audio instead of at every speaker change, and every speaker change inside a page is separated only by wherever the greedy 400-char packer happened to land. That is the mechanism behind the 99.7% wrong-boundary figure in the previous section, and it is a much simpler explanation of "dialogue sounds phony" than any TTS parameter. With paragraphs restored, a 115-char mean paragraph means most paragraphs become a single chunk on their own, so one call per speaker turn falls out of `pack_text` for free, with no dialogue-aware chunker and no LLM performance director.

(V) THE FIX MUST BE ADAPTIVE, NOT A REPLACEMENT. Probed three Path A books over comparable page ranges:

- Power of the Dog: 0.48% of lines indented, 2139 paragraph gaps. Indent signal ABSENT, vertical signal STRONG.
- PHM (`samples/Novel sample`): 35.52% indented, 287 paragraph gaps. Indent signal STRONG, vertical signal weak.
- The Odyssey: 42.23% indented, 7 paragraph gaps. Indent signal STRONG, vertical absent (and it runs verse mode anyway).

The two signals are complementary and essentially mutually exclusive across these books. So the change is: keep the x-indent rule as primary, and fall back to a vertical-gap rule (new paragraph when the gap exceeds about 1.5x the page's modal leading) only when indented lines are rare. That cannot touch PHM or the Odyssey, which take the existing path. NOT IMPLEMENTED, NOT TESTED. No code was changed for this finding.

COSTS AND TRAPS BEFORE ANYONE IMPLEMENTS THIS:
- Re-extraction invalidates `blocks.json`, and the operational trap in the rulebook section applies: `worker_loop` SKIPS extraction whenever `blocks.json` exists, so the file must be DELETED, not merely resumed over. Changed blocks then change `plan_hash`, which wipes segments, which means a FULL re-narration. For Power of the Dog that is roughly 3 hours of 4090 time.
- Chunk count will rise steeply, plausibly to the same ~2.9x estimated for turn splitting. Throughput under the new profile is unmeasured. Use `narrate_worker.build_plan`.
- Mean paragraph 115 chars means many very short calls, and the short-call quality question raised in the previous section is still open and still untested.
- Whether The Shining and Sphere share this typesetting is UNVERIFIED; their PDFs are on the HP Omen and were not inspected. It is a reasonable hypothesis given both are novels and both drew the same complaint, not a finding. FALSIFIED for The Shining on 2026-08-03, see below; still open for Sphere.
- Stage 0 and Stage 1 remain valid as narration findings. They are simply no longer the highest-leverage lever.


<!-- CLAUDE.md lines 526-569 -->
### Adaptive paragraph detection: IMPLEMENTED and verified (2026-08-03)

The previous section's fix is in. `app/pipeline_text.py` is the only file that changed for it, and `extract_path_a`'s signature is unchanged so `server.py` needed no edit.

- `_page_lines_with_geom` is new and carries `y0`. `_page_lines_with_x` is now a thin wrapper over it keeping its original `[(x0, text)]` contract, so `detect_text_mode` and `_verse_page_paragraphs` cannot see the change AT ALL. That is deliberate: it makes "verse is untouched" a property of the code rather than a claim to be re-tested.
- `detect_paragraph_style(pdf, page_from, page_to)` probes 24 evenly spread pages once per book and returns `("indent", 0.0)` or `("gap", leading)`. It measures the indent fraction with the SAME definition the rule itself uses (per page: min x0, plus 6 pt), so it cannot conclude the indent signal is present when the rule would not actually fire.
- `_modal_leading` takes the smallest WELL POPULATED gap cluster (at least 20% of the peak bucket, at least 4 pt), not the raw mode. This guard is load-bearing and not decoration: a book whose paragraphs are mostly one line long has MORE blank-line gaps than single-line gaps, so the raw mode would be twice the real leading, the threshold would sit above every real gap, and the fallback would silently find nothing while looking like it worked.
- `_prose_page_paragraphs(lines_with_geom, leading=0.0)`. A `leading` of 0.0 disables the vertical rule and is exactly the old behaviour. The indent rule stays active in gap mode as well, so a stray centred line still breaks a paragraph. A gap more negative than the threshold also breaks, which is a column jump rather than a continuation; a gap near zero joins, because that is same-row text.
- Constants: `PARAGRAPH_INDENT_PT 6.0`, `PARAGRAPH_INDENT_MIN_FRACTION 0.05`, `PARAGRAPH_GAP_RATIO 1.5`, `PARAGRAPH_PROBE_PAGES 24`.

(V) Verified by loading the ORIGINAL module out of `git show HEAD:app/pipeline_text.py` alongside the working tree and running BOTH over the real PDFs. The probe decides correctly with a wide margin: Power of the Dog prose/gap at leading 17.25 pt, PHM prose/indent, The Odyssey verse (the probe is not consulted for verse).

Indent fractions measured with the rule's own definition over a 24 page sample: Power of the Dog 0.17%, PHM 38.93%, The Odyssey 46.74%. These differ slightly from the 0.48 / 35.52 / 42.23 recorded in the previous section because that probe scanned differently; the conclusion is identical and the separation against the 5% threshold is over 200x on the low side. Do not treat either set as canonical without re-measuring.

- (V) PHM: BYTE FOR BYTE IDENTICAL, 6,219 blocks and 816,850 chars unchanged.
- (V) The Odyssey: BYTE FOR BYTE IDENTICAL, 4,465 blocks and 752,771 chars unchanged.
- (V) Power of the Dog: 726 blocks to 9,490. Body 707 to 9,461. Mean body block 1,562 to 115 chars, median 1,334 to 54, max 9,094 to 1,587. That is the 13.3x under-segmentation predicted in the previous section, landing at 13.4x.

Two gates were added because the block counts alone are not proof:

- (V) TEXT PRESERVATION. Non-whitespace characters are IDENTICAL, 905,525 in both. The apparent 8,935 char drop is entirely join spaces, and the accounting is exact: 8,764 extra blocks means 8,764 fewer line joins. Nothing was lost or reordered. Any future change to this rule should be checked the same way, since block counts can look right while text is being dropped.
- (V) CHAPTER MARKS. 16 headings match `CHAPTER_RE` before and after, identical and in the same order (Prologue, Chapter One through Fourteen, Epilogue). The m4b table of contents is unaffected.

(V) The old plan reproduces the stored job's 3,556 chunks EXACTLY through the real `narrate_worker.build_plan`, which validates the harness rather than just the fix. `CHAR_CEILING` was not touched, and both old and new have max chunk 531 with exactly one chunk over 400, so the fix does not create long chunks.

KNOWN SIDE EFFECT, accepted and not fixed. Headings go 19 to 29 on Power of the Dog. All 10 additions are shouted all-caps dialogue lines. `is_heading` accepts any 2 to 60 char line whose letters are all uppercase and which does not end in `.:,;`, and a quoted shout passes it. These lines were ALWAYS eligible; they were previously buried inside page-sized blocks so `is_heading` never saw them standalone. None matches `CHAPTER_RE`, so the only consequence is a 200/150 ms heading pause instead of body pauses on 10 blocks out of 9,490. `is_heading` was deliberately NOT tightened: rejecting quote-initial lines would also change Path B rulebooks, and that is a separate decision rather than a side effect of this one.

SHORT-CALL EXPOSURE, now quantified, and this was the open risk. Chunks go 3,556 to 10,042 (2.82x, matching the ~2.9x estimate) while the median chunk falls from 341 to 59 chars. Under 30 chars: 56 (1.6%) to 2,620 (26.1%). Under 10: 5 (0.1%) to 399 (4.0%). Under 5: 0 to 16.

DIALOGUE BOUNDARY QUALITY, classified over every dialogue-touching chunk:

| | old | new |
|---|---|---|
| one turn, nothing else | 5 (0.3%) | 1,317 (33.2%) |
| one turn plus attribution | 7 (0.4%) | 914 (23.0%) |
| turn blended into narration | 433 (25.0%) | 568 (14.3%) |
| two or more turns in one call | 889 (51.4%) | 1,077 (27.1%) |
| turn split across chunks | 397 (22.9%) | 96 (2.4%) |
| ONE SPEAKER PER CALL | 0.7% | 56.2% |

The previous section's 99.7% figure used a cruder classifier; the refined anatomy above gives 99.3% wrong falling to 43.8%. Real and large, and short of a cure. Note that "one turn plus attribution" counts `"Get out," he said.` as correct, which is a judgement call: that is a legitimate single beat, not a defect.

THROUGHPUT IS STILL UNMEASURED. 2.82x more calls against a much shorter median could be neutral or better, because this file's own measurements put short chunks at the N=12 row cap where batching pays 3 to 4x. Could be. Measure it with `narrate_worker.build_plan` per the benchmarking rule, do not assume it.


<!-- CLAUDE.md lines 632-677 -->
### THROUGHPUT: the paragraph fix is FASTER, and the 3.1 hour PotD figure is RETIRED (2026-08-03)

The open question from the two sections above is answered. 2.82x more chunks costs LESS wall clock, not more.

Two new prototypes, both untracked at time of writing. `app/bench_plan_dump.py` runs in the BASE env (needs fitz) and dumps the old and new production chunk plans; `app/bench_throughput.py` runs in the chatterbox env and does the GPU timing. Split for the same reason Stage 2 was: the chatterbox env has no PyMuPDF.

METHOD, because the method is what makes the number believable:
- Chunk lists come from the real `narrate_worker.build_plan`, per this file's own benchmarking rule.
- The hot loop is production's, not a reimplementation: `tokenize_chunk` then `.cpu()` then sort by token length then `narrate_worker._make_buckets` with the live constants then `batched_generate` then `seqs_to_wavs_batched`.
- BUCKETS ARE SAMPLED, NOT CHUNKS. Buckets form from the FULL sorted chunk list, so a sampled bucket is exactly the work production would do. Sampling chunks would change bucket composition and measure a different machine.
- The two arms are INTERLEAVED bucket by bucket so drift hits both equally.
- (V) THE OLD ARM CANNOT COME FROM HEAD ANY MORE, and the script caught this itself by refusing to run. The fix is committed, so `HEAD:app/pipeline_text.py` is the new code and the first attempt would have benchmarked the fix against itself. The old arm is now derived by forcing `detect_paragraph_style` to return `("indent", 0.0)`, which is the pre-fix behaviour by construction, and the script PROVES that byte-for-byte against `016c29a` before it will emit a dump.

(V) RESULT on the 4090, 40 sampled buckets per arm, zero outliers in either arm, all three estimators agreeing to three decimals:

| | old | new |
|---|---|---|
| chunks | 3,556 | 10,042 (2.82x) |
| buckets | 616 | 994 (1.61x) |
| buckets at the N=12 row cap | 27 (4.4%) | 617 (62.1%) |
| median tokens | 221 | 42 |
| median bucket time | 11.43 s | 4.29 s |
| T3 / S3Gen split | 75.9 / 24.1 | 63.7 / 36.3 |
| estimated total | 1.88 h | 1.61 h |

**0.86x, so roughly 14% faster.** The mechanism is that 2.82x more calls became only 1.61x more forward passes, because short chunks fill the 12 row cap while the old plan's long chunks only reached about 5 rows, and each of those passes is cheaper. It also shifts work from T3 toward S3Gen, the stage that batches well. Do not quote 14% to two digits; see the error bar below.

(V) THE ESTIMATOR IS VALIDATED ON REAL PRODUCTION DATA, which matters because extrapolation is the only inferential step. Every completed batched job carries per-bucket telemetry, so the same 40 bucket sampling and stratified estimate was replayed against complete real time series: DMG chapters 1 to 6 estimated 1.090 h against a true 1.126 h (-3.2%), The Odyssey 1.135 h against 1.180 h (-3.8%), the PotD batched job 2.085 h against 2.014 h (+3.5%). So each arm is good to about 4% and the ratio to roughly 8%. Even at the pessimistic end that is 0.93x, so "faster, or at worst neutral" is safe.

THE 3.1 HOUR FIGURE FOR POWER OF THE DOG IS RETIRED. Do not use it as a reference again. The benchmark's built-in sanity check failed against it by 39.4%, and the reference was the problem:

- (V) Job `71ab0f07` "The Power of the Dog (batched)" is where it came from, and its log shows ALL 668 buckets ran at **N=2 rows**, with `batch_size=6` in its config and no token budget key. Today's default produces N=4 to 12 on the same plan. That is a fundamentally different batching regime, not the current engine.
- (V) That log covers 1,336 of 3,556 chunks, 37.6% of the book. It is a partial or resumed run, consistent with this file's account of a fixed batch count thrashing partway through a book.
- (V) Per chunk it cost 3.56 s against today's 1.90 s, i.e. today's configuration is about 1.9x faster per chunk, which matches the roughly 2x this file attributes to batching.
- Its T3 share is 88.2%, against 75.9% in the benchmark's old arm at N=5 and 59.0% for the Odyssey. That gradient is exactly what more rows per bucket should do, and it is a useful cross-check that all three measurements are internally consistent.

CONSEQUENCE: the re-narration cost estimate recorded in the two sections above, "roughly 3 hours of 4090 time", inherits the retired figure and is WRONG. On today's engine the new plan should be about **1.6 hours of generation** plus assembly.

(V) The Odyssey job log independently reproduces this file's own recorded Odyssey figures exactly, 472 buckets and a 59.0% T3 share against the recorded "T3 59%, S3Gen 41%". So the job logs are trustworthy and it is the prose figure that was stale.

TWO WORRIES THAT DIED, both of which had been raised as possible costs of the fix:
- (V) Tokenizing the whole book is free: 0.8 s for the old plan, 1.5 s for the new one.
- (V) The extra segment writes are free: 0.03 to 0.04 s per bucket, roughly 35 s across the whole new book despite 2.82x more files.

VRAM peaked at 7.9 GB of 24 across both arms, consistent with the standing finding that peak VRAM is not the binding constraint here.


<!-- CLAUDE.md lines 678-711 -->
### Power of the Dog re-narrated on the recovered paragraphs (2026-08-04)

Job `4c5b2405`, Path A, pages 5 to 818, batched engine, m4b, default voice. Created as a NEW job on purpose rather than deleting `blocks.json` on an old one: a fresh job has no stale blocks for `worker_loop` to skip past, so the extraction-skip trap does not apply, and both pre-existing PotD jobs keep their data. (V) `fb547e0f` and `71ab0f07` are both intact afterwards with 3,556 segments each.

(V) EVERY OFFLINE PREDICTION HELD, which is the main reason to record this run in detail.

| | predicted offline | real job |
|---|---|---|
| blocks / body / headings | 9,490 / 9,461 / 29 | 9,490 / 9,461 / 29 |
| CHAPTER_RE marks | 16 | 16 |
| mean body block | 115 chars | 115 chars |
| plan chunks | 10,042 | 10,042 |
| buckets | 994 | 994 |
| generation time | 1.613 h | **1.646 h (+2.0%)** |
| T3 share | 63.7% | 64.6% |
| median bucket | 4.29 s | 4.58 s |

THE BENCHMARK IS NOW VALIDATED BY A FULL BOOK, not just by replaying old logs. A 40 bucket sample predicted a 994 bucket run to within 2%. That is better than the 4% the log replays suggested, and it means the sampling method in `app/bench_throughput.py` can be trusted for future plan changes without running a book to find out.

Extraction took 34 s. Wall clock was 1.783 h against 1.646 h of generation, so about 8 minutes of overhead for model load, segment writes and the m4b encode. One allocator stall, costing 0.4% of runtime, consistent with the ~0.2% of buckets this file records as the undiagnosed norm.

(V) OUTPUT: 18.36 h, 558,470,896 bytes, AAC 24 kHz mono at 68 kb/s, cover art (mjpeg 510x680) and the full tag set. All 16 chapter marks present, correctly ordered and monotonic, Prologue at 0.00 h through Epilogue at 18.31 h. Audio sampled at 1 h, 9 h and 17 h measures mean -20.6, -20.8 and -21.4 dB, i.e. real speech throughout and in line with previously validated runs.

THE BOOK IS 1.32 HOURS LONGER, and this was not predicted anywhere. 18.36 h against the original's 17.04 h, a 7.7% increase. The accounting:
- About 53 min is the deliberate paragraph pause. The old extraction had 725 block gaps at 400 ms; the new one has 9,489. That IS the pacing change the Stage 2 audition preferred, so it is the feature working, not a defect.
- About 26 min is per-chunk model overhead. 2.82x more synthesis calls means 2.82x more per-call lead-in and trailing audio, and at 6,486 extra calls a quarter second each that is the right order of magnitude. This is incidental rather than intended.

Nobody has decided whether a 400 ms gap at EVERY recovered paragraph is right at book scale. Stage 2 preferred it on a 579 character passage with 16 paragraphs. Over 9,489 paragraphs it adds nearly an hour. If the full book sounds too spaced out on listening, `PAUSE_PROFILES["A"]["block_gap_ms"]` is the dial, and lowering it does NOT require re-narration since pauses are inserted at assembly.

SIDE EFFECT WORTH KNOWING: the uncommitted beta UX patch MOVED the source PDF out of `source_pdfs` into `processed_pdfs` on completion. That is the patch behaving as designed, but it means `app/bench_plan_dump.py`'s default `--pdf` path no longer resolves; pass the `processed_pdfs` path to re-run the benchmark on this book.

Disk: the new job holds 2.78 GiB of segments across 10,042 files, and all jobs together are now 15.23 GiB. The completed-job cache cleanup feature the owner asked for still does not exist.

NOT YET LISTENED TO. The Stage 2 audition validated 579 characters. Nothing about this 18 hour file has been heard, and the short-call question that Stage 2 answered on 12 turns has not been tested across 2,620 sub-30-character chunks.
