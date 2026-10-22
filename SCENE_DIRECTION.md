## CPU source-context hardening, 2026-10-21 (current scene-director status)

The existing optional director now carries bounded exact source paragraph frames,
not its own unreviewed facts or prior delivery notes, into subsequent windows.
Frames are deduplicated, limited to 6,000 context characters, and explicitly flag
incomplete/omitted context. The prompt separates source IDs from verbatim context
extracts; the former instruction conflict about copying facts is removed.

Source-based review signals cover written-medium introductions preceding a quote,
lowercase quoted fragments, reported cries and oversized paragraph context. They
remain review heuristics, not definitive role assignments. Later email text cannot
reclassify earlier spoken dialogue. The compiler checks these signals itself,
even if a model supplied an empty ambiguity field. An explicit reviewed override
is still distinct from model confidence. No emotions/deliveries were invented.

Context facts must be exact extracts of selected source evidence, with intact word
and sentence-ending boundaries. This verifies provenance, not truth, entailment,
attribution or completeness of surrounding caveats. Model proposals are never
propagated as memory even if they pass the extract checks. Direction policy is now
scene_direction_v2_source_context; stale compiled directions and old plans require
explicit revalidation. This does not affect existing jobs without direction opt-in.

CPU-only migration: scene_direction_cli.py revalidate OLD_FOLDER NEW_FOLDER.
It preserves the original and writes a new blocked review copy, a verbatim
quarantine report and source warnings. It never runs a model, approves semantics,
starts TTS or changes existing audio. Revalidate is not a production migration.

The real 2,091-word trial confirms all five missed written continuations and
three embedded fragments are guarded, while two earlier spoken turns avoid the
old later-email false positive. Twelve of fourteen context proposals are
quarantined (eleven non-extracts, one fragment); two remain unapproved extracts.
All 24 model speaker/emotion/delivery notes and all 23 original trial files remain
unchanged. Twenty-eight compiler units preserve canonical/runtime text exactly;
zero cues were added. No inference or GPU lease occurred in this hardening pass.

Full suite: 512 tests, 511 passed, one existing skip; 13 new context regressions.
Production configuration and four existing Drama jobs match the prior audit.
The Graft wiring graph was refreshed; no semantic/deep indexing was requested.
Evidence: Output/Scene_Direction_2026_10_21/context_hardening_v1/.

Unresolved: lexical checks cannot settle subtle medium changes across paragraphs,
scene-label drift, inferred motives/emotions or conflicting story accounts.
No model rerun establishes improved interpretation yet. The completed synthetic
Q3 whisper audition remains listening-pending and is not production approval.
Q3 remains the baseline; no defaults, model files, voice references or audio changed.

## Q3/Q4 controlled samples complete, private delivery verified, 2026-10-21

Parent granted the exclusive 25-minute TTS slot after restoration released its
canonical lease. Both models used the same two reviewed canonical excerpts,
voice reference, temperature/top-p/top-k, three seeds, no added cues and 16 CPU
expert layers. Six requests per model completed, plus one successful smoke each.
No local director ran. Existing production remains Q3 with its existing settings.

The first untrimmed Q3 smoke stopped safely during loading: process working set
peaked at 22,127,669,248 bytes and free host RAM fell to 420,872,192 bytes. No audio
was produced. The pinned port maps GGUF files but BinaryBlob::discard_range is
a no-op on Windows (binary.cpp:90-117). One guarded retry retained the 3 GiB stop
floor and used the SAME process-local policy for both arms: EmptyWorkingSet on
the owned child below 6 GiB free, at most four times in its first 90 seconds.
Sampling increased to 0.25 seconds. No unrelated process was killed, model changed,
system setting changed or backend recompiled. Failed logs remain preserved.

Full-arm measurements (native-process timing includes model load, excludes prior
SHA hashing): Q3 74.925 sec for 127.478 sec audio; Q4 77.859 sec for 127.245 sec.
Generation-only totals were 56.750 and 58.786 sec (Q4 about 3.6% slower). Peak
whole-board VRAM was 18,920 and 21,212 MiB. Peak process working set was 15.213 and
15.354 GiB; minimum free host RAM 5.962 and 5.730 GiB. Q3 needed one working-set
trim, Q4 two. These RAM/speed results include that matched memory policy and do
not predict unchanged production behavior. Both first-seed smoke/full WAVs were
byte-identical. All native frame/rate/text-identity checks passed.

After both TTS processes exited, local offline Parakeet checked all 12 samples
without expected-text hints. All pass the existing checker. The shared difference
is Peglow transcribed as Peglo in each passage-1 take; no substantive omissions
or additions were detected. No full-scale clipped PCM samples or frame-limit hits
were found. Audible artifacts, naturalness and flatness remain listening questions.
No quality winner or production-default switch is justified yet.

Two blinded first-seed reels and their labelled counterparts contain both excerpts
with a one-second gap. They use static gain to the same -23 dBFS RMS, with no
compression/denoising/speed change. All 12 original unmodified native WAVs are in
the raw-samples ZIP. The reveal key is separate in the labelled folder.
Nine Drive uploads were read back: every file is shared=false with exactly one
permission, Paul Miscavage as owner. Remote sizes match local files; ZIP CRC and
12-WAV count pass; blind RMS differs by less than 0.001 dB and peaks stay below
-1 dBFS. Delivery used the Google Drive skill; no sharing permissions changed.

Listen first: https://drive.google.com/drive/folders/1TFzO6pS5LUpELCRTjLtsGCMvwiIxEPY7
All results: https://drive.google.com/drive/folders/1siqtkqfzH5weoJGhZoh4mByvodZ8s_d5

The canonical lease was independently reacquired/released at
2026-10-21T20:26:42.578204Z. GPU was 1,590 MiB, 1% utilization, Ollama empty,
22,657,581,056 bytes free host RAM. Slot start was 20:14:39.644239Z, so completed
inference and independent release verification were within 25 minutes.
CPU source audit confirms production config and four legacy Drama jobs unchanged,
with exact original chapter/source copies. Latest application CPU suite remains
499 tests (498 passed, one existing skip); no application code changed in this slot.

Primary evidence: quantization_results.json, quantization_fidelity.json,
quantization_slot_guarded_trim.json, GPU_RELEASE_VERIFIED.json,
delivery_validation.json, drive_quantization_handoff.json, and
chapter/runs/quantization/guarded_trim_v1/*/{run,telemetry,artifact_checks}.json.
The exact runners and logs are copied into this private output directory.
Automatic direction is still incomplete; its separate 4B/27B comparison is
prepared but requires a newly coordinated analysis slot. Do not reuse this slot.

Windows API documentation checked for the process-local trim:
https://learn.microsoft.com/en-us/windows/win32/api/psapi/nf-psapi-emptyworkingset

## Independent quantization audition ready; analysis comparison prepared, 2026-10-21

Parent clarified that Q3/Q4 testing must not depend on successful automatic
direction. The quantization-only path is now independently prepared and tested.
chapter/quantization_manifest.json freezes two manually inspected, complete
canonical excerpts (63 and 59 words), no added cues, identical reference and
decoding, and seeds 1729/2718/31415. There are six requests per model, twelve total.
Both arms use 16 CPU expert layers; an optional Q3 12-layer production-placement
control is labelled separately. Text, source, reference, settings and placement
tampering fail validation. This path never reads the direction plan. No GPU ran
during this CPU follow-up, and the Nosferatu restoration task owns the GPU slot.

Use the private run_audition.py with --experiment quantization only AFTER a new
coordinated slot. First do one Q3 and one Q4 smoke (300-second ceiling each),
refresh headroom, then the matched six-request arms. The initial first-seed blind
listening pair assesses clarity, naturalness, artifacts and expressivity under
unchanged text/cues. Repeats distinguish sampling variance. ASR checks omissions,
insertions and substitutions; it does not establish acting quality. Decode-time
and peak RAM/VRAM are measured. No production switch follows automatically.
Emotion-tag effectiveness remains a separate later experiment at fixed quantization.
No tag contrast is required for this quantization-only experiment.

The installed local inventory also contains qwen3.8:27b (27.3B, Q4_K_M), digest
22130167c4c20e20c7b71454612966ca8e8171e9b3cc8ab6ce8aa6cbfec79643.
Its two local weight blobs total 17,741,860,480 bytes (language weights plus vision
projector); the tag inventory total is 17,741,872,154 bytes. No download is needed.
The qwen35 architecture is consistent with the official Qwen3.8 model card; it
does not imply that the local tag is secretly Qwen3.5. Customized coder/maps aliases
and the cloud alias were not chosen. This is a stronger candidate, not evidence
of better audiobook direction. Installed metadata and original raw failures are saved.

The 4B model has not demonstrated adequate reliability for unattended direction:
both prior attempts failed on the first window. This does not prove a general
4B capability limit; quote copying, schema consistency, attribution and unsupported
context claims were separate failures. The source-ID format fixes copying but
does not establish semantic truth. No context proposal is approved by schema alone.

director_trial_v2/trial_spec.json prepares exactly two cases per model, no retries:
one real-book attribution/uncertainty excerpt, one synthetic calm-concealed-fear,
explicit-whisper and quoted-sign example. Review criteria are kept out of prompts.
run_director_trial.py takes 4b or 27b and requires --gpu-slot-confirmed. Each model
has a 240-second active-trial budget, 90-second request timeouts, at most two calls
of 1,536 tokens, and up to 90 seconds of cleanup/release checks. Each model loads
and unloads separately; any non-GPU residency fails. No automatic chapter expansion.
Expected comparison duration is roughly 3-6 minutes, but the failure ceilings are
longer and must fit the coordinated slot. 4B previously used 5.6 GiB whole-board;
27B estimates are 18-22 GiB whole-board, unmeasured. Require at least 20 GiB free
host RAM for the 27B preflight; abort if it cannot fit fully on GPU. No CPU offload
for analysis is planned. The sampler now follows Ollama's process descendants.
27B thinking is explicitly disabled for this bounded structured-output comparison;
its reported thinking default is medium. The 4B Instruct runtime has no thinking
metadata and keeps its existing behavior. Generation options are explicitly matched.

CPU result: 499 tests run, 498 passed, one existing dependency skip. This includes
40 new direction/quantization tests. Both runner GPU gates were checked without
network or GPU calls; both quantization arms reached a mocked preflight without
reading direction plans or spawning processes. These are dry checks, not audio
or model-quality results. Production configuration/jobs/source copies stay unchanged.

Official documentation verified for this candidate and request controls:
https://huggingface.co/Qwen/Qwen3.8-27B
https://docs.ollama.com/capabilities/thinking
https://docs.ollama.com/api/chat

## Bounded analysis attempted; GPU released; chapter incomplete, 2026-10-21

Parent granted the chapter-analysis-only RTX 4090 slot. Preflight found no
competing inference and roughly 21 GiB free host RAM. No TTS or ASR started.
Two bounded local Qwen attempts were rejected: the first changed source quotes
and evidence punctuation; the one corrected attempt used exact source IDs but
returned inconsistent narrator/speaker roles and unsupported context wording.
Both failed closed and unloaded. Total wall time was 44.29 seconds (35.23 + 9.06).
Peak sampled whole-board VRAM was 5,701 MiB; baseline/final were 1,597 MiB.
Minimum available host RAM was 20.05 GiB (peak whole-host use 11.67 GiB).
The RAM figures are whole-system, not a measured model-process peak: the process
sampler did not identify the runner child, so its per-process totals are incomplete.
Ollama reported zero resident models after both attempts.

CPU follow-up now uses source-ID constrained selection, requires dialogue roles
for quoted-turn proposals, skips windows with no complete quoted turns, and
strengthens attribution/uncertainty instructions. This final prompt/schema has
CPU tests but has NOT had another GPU trial; there were no unbounded retries.
Context proposals now appear in the review page. HTML embedding preserves source
characters safely. Incomplete diagnostics cannot bind to a job or become auditions.

Output/Scene_Direction_2026_10_21/partial_review_NOT_FOR_RENDER/review.html is an
editable diagnostic: three flagged, conservatively corrected first-window notes,
all plain. Raw responses and exact changes are retained beside it. Eight model
context proposals were excluded from the corrected diagnostic; one introduced
unsupported credibility/publicity assertions. The reported Help cry was wrongly
attributed to Peglow, and has been marked unknown with explicit ambiguity.
The original chapter directions remain empty; the other windows are unanalyzed.
This is NOT a successful chapter analysis or a tagged audition. Quotation density
also includes written messages, aliases and legal text, requiring contextual review.

Final CPU suite: 495 tests run, 494 passed and one existing dependency skip;
36 direction tests included. Graft rebuild/check and review JavaScript syntax pass.
Production settings/jobs/source hashes remain unchanged. Q3 remains default.
Next inference requires a new parent-coordinated analysis slot. TTS/ASR remain
separately gated, and a valid supported cue contrast is still required first.

# Optional scene direction, CPU implementation checkpoint

Implemented in the existing `D:\Audiobook_Pipeline` checkout on 2026-10-21.
Disabled for all existing jobs and production defaults. No server restart,
book rerender, installer build, Git write or upload was performed.

## Data and integration

`scene_direction_cli.py prepare` copies original extraction bytes into a private
audition folder, records the source job/plan/config/reference hashes, and derives
a separate narration-text snapshot from the existing sentence-preserving planner.
`original_extraction.json` is the immutable original source layer.
`canonical.json` is the derived, exact narration-source layer used for offsets;
it does not claim the planner's whitespace normalization reproduces the raw PDF.
The source job's original book, extraction, approved spoken projection and audio
are never edited by preparation.

The local analysis returns source-anchored speaker, intention, internal emotion,
intensity, audible delivery, confidence, evidence and uncertainty. It carries
source-supported character/story facts and recent directions across bounded
windows, with adjacent text for continuity. Scene boundaries inferred by the model
are notes, not edits or authority to add plot. Confidence is not calibrated accuracy.
Only exact, unique quotes are resolved to Unicode code-point offsets. Missing,
repeated, overlapping, invented or stale anchors fail validation. Truncated model
responses remain in the cache as evidence and cannot become a compiled plan.

`review.html` presents annotations and reasons for withholding cues. It allows
source-bound user overrides without erasing the model's original notes. Saving
downloads `directions.json`; place it back in this private audition folder, then
rerun `review` and `audition`. Editing the JSON directly also supports richer
annotation changes, all revalidated before use. The page sends no network requests.
JavaScript syntax was checked; interactive browser verification is still pending.

The first cue vocabulary is deliberately small: whisper, angry, laughing, sighs,
and laughs. Documentation and native prompt passthrough support these forms;
local acoustic behavior has NOT yet been validated. Nonverbal proposals require
an explicit user choice. Unsupported cues remain visible notes and render plain.
Calm/neutral delivery emits nothing, even when internal emotion is intense.
Narrator spans remain plain. An ambiguous speaker/delivery remains in review.

The compiler keeps current sentence/turn chunks and inserts at most one cue per
chunk. It never fragments a turn into semantic beats. A cue with following narrator
prose/another turn is withheld because this pinned port has no locally validated
neutral reset. Cross-chunk turns, changed spoken projection and over-limit tagged
inputs also fall back to plain with a reason. This is a real first-pass limitation,
not evidence that all chapter dialogue will receive cues. Removing only recorded
insertions must reproduce the exact input; existing bracketed source is preserved.

The optional `scene_direction.json` sidecar binds `{source, plan}` to a NEW app
job. `drama3.write_plan` validates it against the actual planned passages and adds
its hash to runtime identity. The existing worker compiles units; native requests
and render receipts use directed text, while content checking uses plain spoken
words. Changed directions cannot reuse saved audio or silently migrate old jobs.
Remove an opt-in sidecar before a plan is created to disable it. After planning,
use another new job for a different direction version. No production job is bound.
This experimental entry point is a CLI plus a private review page; it does not yet
add an analysis button to Storybird's main window.

## Local model and GPU lifecycle

Reuse installed Ollama `qwen3:4b-instruct-2507-q4_K_M`:
`0edcdef34593eac1aa2be9c7d06c432dcf81945adca5eca2f27662c18f168ba0`.
The installed manifest is 2,497,293,803 bytes. No analysis-model installation or
runtime upgrade is needed. Model quality for performance direction is untested.

The adapter only contacts `127.0.0.1:11434`, bypasses proxies, rejects redirects
and remote model aliases, and checks the exact model digest. It requires a
coordinated GPU slot, refuses other resident Ollama models, requires full GPU
residency and verifies unload even on failure before TTS may begin. No CPU
inference or cloud fallback is introduced. Cache identities bind original text,
model digest, prompt/schema, sampling, cue policy and incoming story context.

## Prepared chapter and experiment

Private folder: `Output/Scene_Direction_2026_10_21/chapter`.
Source: completed Genesee job `7554bee0-d4ec-4e79-8228-70ed8a00851b`,
heading-delimited chapter “Clint's Demise,” 2,091 words, seven source parent
passages and four bounded analysis windows. Source hashes and copies verify.
No model-generated annotations exist yet; the manifest correctly reports
`analysis_or_review_required_no_tag_contrast` and refuses a full TTS audition.

After analysis and review, the manifest freezes two dialogue-rich production-sized
units, tagged/plain variants, the same original narrator reference/decoding settings,
and seeds 1729/2718/31415. Q3 and Q4 each receive the same twelve requests.
Both use 16 CPU expert layers and context 4096 to avoid confounding quantization
with placement. A separately labelled Q3 control can retain current 12-layer
production placement. Matching seeds controls the input RNG condition, not an
assumption that differing quantization will produce identical samples.

The private `run_audition.py` runner requires a separate GPU slot, checks exact
asset/reference/plan hashes and idle headroom, owns only its child process,
records command/timing/GPU samples/process peak working set/free RAM, bounds
duration and stops at a memory headroom floor. It retains native WAV/code artifacts,
checks exact input text, sample rate and frame caps, and never accepts audio into
production. It has not yet executed native inference; timing/VRAM/RAM comparisons,
independent Parakeet/Whisper checks and listening quality are still pending.
Present only one first-seed A/B pair initially; keep repeats for internal analysis.

## Quantization verified on disk

Both artifacts are from `Jmica/Drama-3-GGUF` revision
`bcb065b8b0b98535a5c002b39bcceeb8bf065513` and use the existing native Windows
audio.cpp revision `4e6018fd018499d75e5070ba4eb38db4e48b9b59`.

| Component | Baseline | Comparison |
| --- | --- | --- |
| Routed experts | 120 Q3_K banks | 120 true Q4_K banks |
| Other tensors | 392 Q8_0, 592 F16, 282 F32 | Same types and all 1,266 byte-identical |
| File bytes | 20,325,196,992 | 24,596,497,888 |
| Expert weight bytes on host at 16/40 layers | 5,536,481,280 | 7,247,757,312 |

The tokenizer, tokenizer config, special tokens, model config and chat template
are byte-identical; parsed model contracts are identical. Different ancillary
embedded README/index files explain metadata-size differences. Neither package
is an all-tensors-3-bit or all-tensors-4-bit model. Newer FP32-router derivatives
were not selected, since that would add a separate variable.

The exact prior Q4 file was absent and has now been restored with a bounded 1 MiB
streaming download, checked against live publisher metadata and SHA-256
`05af716baf78e7c20863b9ccebb3ebdeca9607dd3ea7d0b72c35079e675b212b`.
Q3 remains installed and selected. Production's Q3 asset pin was not relaxed.
CPU expert execution is verified in installed `backbone.cpp:290-324`; arbitrary
layer offload, newer expert-cache options and newer runtimes are not assumed.

## Validation and remaining gate

Final full suite: 490 tests passed, one existing dependency skip, CUDA disabled,
including all 31 new direction tests. The earlier 488-test run also passed.
Graft rebuild/check and JavaScript syntax check pass.
Four existing Drama jobs remain unopted-in; production config and selected source
job plan/config/extraction hashes are unchanged. This is CPU implementation proof,
not proof of local model accuracy, natural acting or Q4 superiority.

GPU remains gated by parent coordination with the Nosferatu restoration task.
First slot: Qwen analysis, approximately 4–6 GiB VRAM, expected 3–8 minutes for
four windows (300-second per-window ceiling). Second slot after review: bounded
native smoke and matched TTS/ASR, approximately 15–25 minutes. Q4 host expert
weights alone are 6.75 GiB at 16 layers; total RAM/VRAM must be measured live.
Require fresh headroom checks. No whole-book rerender or production switch.

## Current primary documentation checked 2026-10-21

* https://huggingface.co/fishaudio/drama-3
* https://github.com/fishaudio/fish-speech
* https://fish.audio/ (Drama 3 point/delivery controls)
* https://huggingface.co/Jmica/Drama-3-GGUF/tree/bcb065b8b0b98535a5c002b39bcceeb8bf065513
* https://github.com/JarodMica/audio.cpp/blob/4e6018fd018499d75e5070ba4eb38db4e48b9b59/docs/models/fish_drama3.md
* https://huggingface.co/Qwen/Qwen3-4B-Instruct-2507
* https://docs.ollama.com/capabilities/structured-outputs

Fish's generic emotion-control page explicitly describes S2. Its entire vocabulary
was not assumed validated for this installed Drama 3 port. No new dependencies,
driver/runtime updates or security changes were made.
