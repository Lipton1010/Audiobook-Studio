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

## Optional scene direction prepared, GPU gated, 2026-10-21

The owner approved local scene-aware direction and a controlled Q3/Q4 comparison.
The optional source-bound pipeline is implemented in the existing app, disabled
for all current jobs/defaults. Read SCENE_DIRECTION.md for the exact scope,
compiler fallbacks, local model lifecycle, fresh-job opt-in and remaining limits.
Original extraction remains separate from editable annotations and rendered cues.
Runtime/receipt identity prevents edited directions from reusing old audio.

The private 2,091-word Clint's Demise chapter is prepared under
Output/Scene_Direction_2026_10_21/chapter. Local analysis has NOT run, and no new
speech or listening verdict exists. Parent must coordinate an exclusive GPU slot
with the Nosferatu restoration task before model inference. Reuse the installed
Qwen3-4B-Instruct-2507 Q4_K_M; no analysis-model install is needed.

The exact previously auditioned Q4 expert/Q8 backbone GGUF has been restored and
SHA-256 verified, while Q3 remains selected. Headers prove 120 true Q4_K versus
120 Q3_K expert banks; all 1,266 non-expert tensors, tokenizer assets and model
config are identical. Match CPU expert placement and sampling in the comparison.
Production's pinned Q3 adapter was not loosened to accept arbitrary model files.

CPU tests, source copies and production-configuration checks are recorded in the
private handoff. No existing audio/book edits, app restart, production opt-in,
installer, release, commit or upload occurred. Current CPU full-suite result is
recorded in Output/Scene_Direction_2026_10_21/full_tests_final.log.

## Annihilation completed — 2026-10-19 (current authority)

The owner requested autonomous completion, then explicitly authorized deleting
the previous Annihilation generations and starting fresh with Drama 3 using the
same narrator. New job `b79b1fb6-d6ff-4b80-9c3f-2ce7ed3e6f11` uses Ray Porter PHM,
Q3, the current sentence-preserving defaults and the saved scope of pages 6–98.
The ordinary regeneration API copied the source and narration choices; the old
job's generated-output deletion freed 469,989,597 bytes. Source PDF, original
voice, extraction and scope hashes remain unchanged. The new plan contains
55,513 spoken words, 154 parents, 733 clips and all five chapter headings.
Its lexical tokens exactly cover the selected PDF text layer in source order.

An early audit found a bad opening heading; both Parakeet and unprompted Whisper
heard the same wrong words. All 31 sampled prose clips pass Parakeet. A long
internal pause in one prose clip retained every expected word in both recognizers;
that delivery concern was addressed in the final replacement audit below.
Drama 3's early return in `_units_for_parent` bypassed the existing numbered-
heading checker, routing a clear heading failure straight to manual review.
The strict heading marker now applies before backend dispatch. Older pending
records receive that checker metadata without changing their audio or render
identity. A regression failed before the fix; the initial 104 affected tests passed.

The normal scheduler retried the heading at attempt two, seed 1730. Its raw WAV
matches the independently verified probe byte for byte. The failed take remains
archived and all 65 pre-pause WAVs are accounted for. The 32 early primary reports
were installed with exact audio/generation hashes; no listening approval was
created. The owner later paused work to use the PC and explicitly resumed it.

The full run exposed a second early-review path: Drama's critical short wording
flags also stopped before the existing retry budget. `_resolve` now lets Drama
use its bounded retries before that listening hold; uncertain transcript-review
results still stop. The new regression failed before the fix. All 26 Drama,
29 phase and 50 repair integration tests pass, and Graft was rebuilt and checked.

The finished M4B is `audiobooks/Annihilation (2)/Annihilation.m4b`, also retained
in the job output directory. Storybird reports `done`, all 55,513 words verified
and zero review passages. The book is 5:24:26, 162,330,216 bytes, with all five
chapter markers verified. Full decoding passes; the library and job copies share
SHA-256 `46e077f804b734da3b0a79420e6b105f63376d0daa5c2f6ef2a23a726a2de17e`.
The final audit and raw evidence are under
`Output/Annihilation_Drama3_2026_10_19/completion_audit/`.

All 733 original clip identities and hashes were checked; 223 original recordings
received an independent transcript check. Thirty-seven targeted replacements
were installed after bounded retries. Thirty-six pass both comparison checks;
one exact primary transcript has a documented independent formatting difference:
Whisper writes the source's three quantities as `12 or 50 or 100`. The scoped
audit confirms the same values without modifying raw reports or general policy.
Focused tail checks corroborate that five repeated Whisper `Thank you` segments
were recognition artifacts at its 30-second window boundary. The retained
6.07-second pause in clip 1490002 aligns exactly with a printed scene break;
its original take is complete, while its unsuccessful replacements are retained.

Native recovery rebuilt 28 parents without creating any listening approvals.
All selected frames survive 579 internal joins. Of 733 original clips, 696 remain
unchanged and 37 have exact backups; all 799 backup files verify. Source PDF,
canonical text, narration plan and configuration remain unchanged. This is an
automated completion audit, not a claim of a full human listen or proof that all
future books can finish unattended. No Git write, upload, installer, release or
recurring automation was created.

## The Voice completed — 2026-10-19 (current authority)

The owner directed completion of the book and autonomous progress. The finished
M4B is `audiobooks/The Voice (3)/The Voice.m4b`, also retained in the current
job's output directory. Job `56dd0db8-a583-4623-99a3-2be7976de1e8` reports `done`
in the live Storybird API, with no stale-narration warning or review queue.
The file is 3:39:24, 111,445,990 bytes, with title/credits, introduction and all
12 chapters navigable. Full decoding passes; all three export copies have SHA-256
`aebf41a0775394db28db9e1ce55e10debee8059d9767a17cb3fd70fc754541da`.

The completion audit verified all 477 original clips and independently checked
216 original recordings. Thirteen targeted replacements pass both Parakeet and
Whisper. Punctuation-only repairs restored omitted dialogue labels and stage
directions; bounded retries handled a frame cap and two content disagreements.
The former 7.62-second trailing silence is 0.18 seconds in the replacement.
All 465 selected clips retain every frame across 365 checked internal joins.

PDF inspection confirmed a blank-page OCR response at page 25, library inventory
stamps at page 133, back-cover material at page 135, and a line-broken word on
page 100. Exact spoken-projection edits remove the OCR response and non-story
material and restore the broken word. The identical publisher logo on pages 3
and 135 is omitted at both occurrences. Canonical source, PDF and frozen plan
are unchanged. Chapter marks use the 12 visually verified source openings and
word timings where a chapter begins inside a clip.

Completion records owner-delegated automated acceptance, not personal listening
or a claim of error-free delivery. Seventeen primary recognition flags remain
explicitly documented in the private audit. No general accept-if-either-ASR rule
or fuzzy name normalization was introduced. All original clips are accounted for:
475 remain unchanged and two have exact backups; all 553 backup files verify.
Evidence, reproducible scripts and acceptance basis are under
`Output/The_Voice_Drama3_2026_10_19/completion_audit/finished_book/`.

The source parser now holds the exact observed whole-page illegibility response
for visual review instead of treating it as prose. It preserves raw text and
does not match an ordinary quotation. The regression failed before the fix;
all 77 affected extraction/review tests pass. The earlier 103 narration recovery
tests remain green. Graft was rebuilt and checked. The running server was not
restarted; the extraction guard loads on its next launch. No Git write, release,
installer, upload or recurring monitor was created. Fully unattended completion
of arbitrary future books is not established by this supervised completion audit.

## The Voice Drama 3 rerun and empty-take recovery — 2026-10-19 (earlier checkpoint)

The owner requested deletion of the old Voice output and a fresh Drama 3 run
using the same narrator. The old job's generated caches and both library M4Bs
were removed; source PDF, extraction and voice reference remain unchanged.
New job `56dd0db8-a583-4623-99a3-2be7976de1e8` uses Chukwudi Iwuji, pages 3–135,
the current sentence-preserving Q3 defaults and M4B output.

Two native runs stopped because their original input/seed selected EOS before
the first audio frame. Both reproduce in isolation; changing only to the next
retry seed produces audio. The adapter incorrectly raised a job-wide failure
after recording a local retry. It now recognizes this exact native failure,
retains completed clips, continues unstarted requests without consuming their
attempts, and lets the existing bounded scheduler retry the empty take.
Other runtime errors and incomplete artifacts still stop the job.

All 103 affected regression tests pass. A real four-request replay continues
past the failure, retries only the empty take, preserves its peers and passes
all four GPU content checks. The unstarted production request's attempt was
restored with its old receipt retained. All 818 saved WAVs and four source/plan/
configuration files were hash-identical after resume at 12:49 Eastern. Live
readback at 12:51 confirms both affected requests saved and progress beyond
the failure point (30,553/34,729 words). Completion was pending at that checkpoint;
the final audit above supersedes its status. See `DRAMA3_MIGRATION.md` and private evidence under
`Output/The_Voice_Drama3_2026_10_19/debug_empty_audio/` before further repair.

## Genesee final audiobook — 2026-10-17 (current authority)

The owner said, "Im sure its fine. Assemble the book," authorizing the current
recordings without further listening. This supersedes the earlier final-export
hold; it does not claim the owner listened to every flagged clip. Exact take
fingerprints and the instruction are recorded under
`Output/Sentence_Boundaries_2026_10_17/final_book/`.

The finished M4B is in `audiobooks/The Devil at Genesee Junction/` and the current
Drama job's `output` directory. It is 12:35:37, 380,791,238 bytes, with 24 section
markers. Full decoding passes. The library copy matches the job export; its
SHA-256 is `65518c4a8122205e308716cd8137696bd3d26881347838da1aae1d5a357405b8`.
Its encoded audio matches the verified navigable draft. All 2,945 current takes
are accepted, all audible parent WAVs match that draft, and the two reference-only
units remain omitted. Storybird records this job as `done` with no review queue.
All 3,530 backed-up originals verify; source, projection config and frozen plan
are unchanged. Raw speech-recognition evidence is retained.

Finalization exposed an approval-path bug: `_unit_report` replaced the accepted
transcript but retained a stale normalized `comparison_transcript`, which the
parent gate preferred. It now preserves that value in `raw_assessment` and removes
it from the accepted comparison. A synthetic regression failed before the fix
and passes afterward; the native full suite passes 451 tests, one dependency skip.
Graft was rebuilt and checked. No new TTS, installer, release or Git write occurred.

The owner then explicitly requested a Drive upload and email to Mike Bullions.
The connector rejected the single 381 MB file before upload because its limit is
100 MiB. All four complete playable parts are uploaded to the private folder
recorded in `final_book/drive_handoff.json`: 382,375,969 bytes total, full decode
checks clean, all 1,999,378,566 source frames covered without gaps. Readback verifies
the expected names, sizes, parent folder and owner-only access for every part.
The owner subsequently reported deleting the multipart Drive upload and said
they will upload the full single-file master when home. Treat the multipart
handoff as withdrawn; do not restore it or send its old links. The local full
M4B remains ready. Mike's contact has no email address and no email was sent.
Any later email handoff needs the owner's new full-file link and Mike's address.
The earlier whole-draft upload hold no longer blocks this explicitly requested
finished-book handoff. Existing review material remains private and separate.

## Whole-book listening draft — 2026-10-17 (earlier evidence)

The owner requested continued progress toward the repair goal. The current
whole-book draft is under `Output/Sentence_Boundaries_2026_10_17/whole_book_draft/`.
Its source audit verifies all 371 parents and 2,945 current recordings, including
335 review candidates. Two reference-only units are intentionally omitted. No
source is missing or stale. All 2,575 internal joins retain every frame with
five-millisecond fades. Two original joins have long quiet intervals (10.96 and
4.45 seconds); retain them for listening rather than applying blanket shortening.

The navigable M4B is 12:35:37 with 24 section markers. Its complete decode passes;
all 13 smaller parts also fully decode and cover the source without gaps.
The navigation remux preserves the encoded audio packet hash. The private
`Listening_review.html` provides five focused items and 293 other primary-check
flags; these are not counts of confirmed narration defects. Independent Whisper
heard all three sentence spans missed in the primary check's eight largest
differences, so no additional takes were regenerated. App state and original
recordings remain unchanged; this is an unapproved listening draft, not a final
master or a bypass of the app's review gate.

The short prose reel and guide are already uploaded owner-only. Automatic
approval review separately blocked the full-book parts upload as outside that
earlier payload authorization. Obtain explicit approval for the complete draft
before retrying that upload. The concrete pending request covers all 13 parts
(380,632,992 bytes total) and the short guide in the existing owner-only folder.
No whole-book part has uploaded. The owner has not yet listened to the new prose
reel. Consult `assembly_result.json`, `parts_manifest.json`, `browser_qa.json`
and the current upload verification/status artifacts before continuing.

## Prose delivery application — 2026-10-17 (earlier application)

The owner selected comma-punctuation B for long prose and original A for names,
then authorized execution. Parent indexes 164, 192 and 204 now use the scoped
sentence policy and 26 exact punctuation edits, retaining all 117 earlier edits.
The over-limit forensic sentence splits only at complete semicolon entries;
those two terminal boundaries use periods. Names lists are unchanged.

All 15 new recordings completed below the output cap; 13 pass both recognizers.
Two retain name/spelling and time-format differences for listening. The long
sentence is byte-identical to the preferred B take. Three passage previews
preserve every frame across 12 joins; maximum join quiet is one second.
All candidates are installed unapproved. The live app has 272 review passages
and 943 unresolved items, which are not counts of confirmed defects. Of 3,351
protected files, 3,347 remain unchanged and four have exact backups; no current
unit WAV was replaced. The frozen plan is unchanged and GPU work has exited.
Evidence is under `Output/Sentence_Boundaries_2026_10_17/prose_pass/`, including
`final_handoff_checks.json`, `candidate_audit.json` and `drive_verified.json`.
The owner explicitly authorized the Drive upload after an automatic review hold;
the 3:09 reel and guide were uploaded and verified owner-only. No final master
approval or whole-book listening approval was created. Prior 450-test native
regression remains the latest suite; this pass changed private job artifacts,
not production application code.

## Sentence-preserving narration — 2026-10-17 (earlier application)

The owner requested larger chunks that retain whole sentences after listening
revealed abrupt endings. New Drama 3 plans use `sentences_v4`, 75/100-word packing
targets, 1536 output frames, 4096 context rows and 12 CPU expert layers. A long
sentence stays intact within the native character bound; an oversized semicolon
list can split at semicolons. An indivisible oversized sentence is held for
correction. Saved jobs retain their policies unless explicitly migrated.

For the current Genesee job, the new boundaries are applied only to parent indexes
8, 28, 102, 144, 208 and 368. The frozen plan, source corrections and all other
passage identities are preserved. The explicit resource migration binds the
old runtime hash and old/new capacity limits; voice, model and sampling remain
unchanged. Keep `state.json` generation settings consistent with the migrated
config because the server uses them on resume. Consult `DRAMA3_MIGRATION.md`
and `Output/Sentence_Boundaries_2026_10_17/six_passages/installed.json` for the
application status and preservation evidence before further work on this job.

The native full suite passes: 450 tests, one existing dependency skip. The
graph was rebuilt and checked. The 4:51 probe reel and guide were uploaded to
the owner's private Google Drive with owner-only permissions verified. ASR
checks and generated alternatives retain the listening gate; the final master
is not approved. The six passages now have 29 unapproved alternatives, five reused
from the probe. Two incomplete takes with long quiet tails were preserved and
replaced in one bounded retry; both replacements pass both content checks.
Fourteen final alternatives pass both checkers; the other 15 retain differences
for listening. All 23 preview joins preserve frames, with a maximum measured
quiet interval of 1.1 seconds. Earlier October 16 status/counts below are historical.

The owner subsequently reported slower, uneven delivery around 2:20–2:30 of
the probe reel and in its later names list. This was listening-only feedback,
not a source-text comparison or content approval. Isolated pacing comparisons
are under `Output/Sentence_Boundaries_2026_10_17/pacing_comparison/`. They test
list punctuation, fresh takes, complete-entry groups and a quiet-gap-only edit;
none changes the production book or its acceptance decisions.
The owner prefers B (comma punctuation) for the long-sentence excerpt and A
(original pauses) for the names excerpt. Preserve that distinction: the names
pause-shortening experiment is not selected. Exact excerpt hashes and scope are
recorded in `pacing_comparison/owner_delivery_preferences.json`; these choices
are delivery preferences, not source verification or whole-book approval.

## Genesee second repair pass; listening gate retained — 2026-10-16

The owner authorized the five-step checker, source, listening-pack, verifier and
selective-repair goal. Drama 3 remains the narrator. Work and private evidence are
under `Output/Repair_2026_10_16_v2/`; consult its final status and
`DRAMA3_MIGRATION.md` before continuing this job.

The narration comparator now separates safe notation from short meaningful
differences. Negation, numbers, pronouns/directions and short phrase/boundary
differences require listening; they do not trigger repeated automatic generation.
The phased and legacy workers hold aggregate-only failures, retain passing saved
takes, and archive replaced recordings. Cached receipts are checked against the
current policy. Per-passage `drama3_passage_unit_limits`, keyed by parent identity,
allow an explicit selective migration; stale review boundaries are rejected.
The opt-in `captions_v3` boundary policy recognizes parenthesized caption contexts
without changing saved default boundaries. The full isolated-runtime suite is
green: 442 tests run, one dependency skip.

The verifier experiment used 187 recordings, including 30 owner-labelled controls,
40 unlabelled holdouts and 12 synthetic waveform edits. Keep production Parakeet
TDT and optional independent Whisper. CTC and CrisperWhisper did not improve false
flags over the updated primary on these controls; forced alignment does not prove
that expected words were spoken. New verifier assets and runtime are isolated.

All 2,971 original current recordings were waveform-scanned. The corrected
listening page has eight short speech questions and three examples for each of
ten names, plus whole-corpus pause excerpts. Source evidence verifies 72 additional
footnote markers. Preserve canonical source, prior takes and existing review
entries. Final listening decisions and final export are pending; ASR passes are
not delivery approval. No release, installer, upload or recurring work was requested.

The production review handoff is installed: 147 unapproved alternatives, including
two reused saved takes; 119 pass both content checkers and 28 retain differences.
All 207 earlier review passages remain. The live API confirms 271 review passages
and 941 unresolved units. No current unit WAV was replaced and no approval was
created. Exact hashes account for all 29,663 original files: 29,550 unchanged and
113 preserved in `before_install`. Sixty-two unapproved passage previews preserve
all frames across 499 checked joins; no join has a quiet interval over five seconds
at the recorded scan threshold. One alternative has a 6.15-second internal pause
and is included in the listening pack. See `FINAL_STATUS.txt` for the remaining
human listening gate; do not infer final-book approval from these checks.

## Earlier October 16 repair pass (superseded status)

The owner authorized source cleanup, checker/accounting fixes, verified reuse,
then bounded repairs for job `7554bee0-d4ec-4e79-8228-70ed8a00851b`. Ten exact OCR
instruction echoes were removed from the spoken projection after checking the
blank PDF pages. Additional footnote, word-join and fraction corrections were
checked against the PDF. Raw source, approved visual decisions, the frozen plan,
voice and runtime settings are preserved. Future exact standalone prompt echoes
are sent to visual review instead of narration.

The checker now handles calendar dates, contextual years, decades and safe modal
contractions while retaining differences in quantities, dates, negation and
repetition. Saved-take accounting validates earlier audio before declaring it
missing; a failed retry cannot conceal an intact earlier take. Fourteen verified
recordings were reused without changing their audio. Twenty targeted passages,
including the genuinely missing unit 860002, were repaired and now pass both
Parakeet and independent Whisper content comparison. The bounded marker-only
probe completed that unit below the frame cap; this supports removing its source
footnote marker, not a general explanation for all model stalls.

No audio is missing. There are 164 valid assembled passages and 207 passages held
for review, containing 966 unresolved clip items. These are review entries, not
966 confirmed defects. No listening approvals were created and no final M4B was
exported. The app is returned to `audio_review_required`; do not automatically
resume the full scheduler or treat ASR passes as approval of delivery. All 10,638
protected files are unchanged (10,587) or preserved in byte-identical backups
(51), with no missing originals. The full suite passed in both base and audio
runtimes: 433 tests, with 118 and one dependency skips respectively; 55 affected
tests passed after the final progress-accounting adjustment. Detailed evidence
and remaining limits are in `DRAMA3_MIGRATION.md` and the private directory
`Output/Repair_2026_10_16/`.

The native Windows Q3 adapter is integrated with the existing queue, unit review,
44.1 kHz export and Windows process ownership. Raw WAVs and ten-codebook artifacts
are retained with provenance. Real cancel, app-exit, native-failure/resume,
frame-cap rejection, reference preparation and whole-unit replacement probes pass.
Prior-take conditioning works but has no demonstrated delivery advantage; true
inpainting is not implemented or exposed.

Drama 3 is now the default for new jobs and regeneration copies; VibeVoice is a
legacy choice. Saved jobs keep their recorded backend. The owner accepted the
chapter excerpts, with a minor reservation about one rushed compound phrase.
The 1,662-word chapter generated 10m57s of first-pass
audio in a 10m16s preparation/render/check/retry run, with 20 review items across
five passages. Year/name normalization contributes; do not call it an approved
chapter master or infer artifact-free delivery from ASR. New Drama plans use the
existing date/clock spoken projection; the October 16 checker update also handles
contextual year comparison.

Content flags remain subject to the unchanged review workflow; activation does
not approve the sample as a final chapter master. The idle local app was restarted
with the new defaults. The Desktop Storybird shortcut points to this checkout.
The owner has now authorized a fresh full Genesee generation with Drama 3, using
approved source/visual decisions in a new job and preserving the old job/audio.
The owner confirmed pages 5–355. Fresh Drama job
`1f1c79c1-d332-4327-a010-07721161e73f` started on 2026-10-15 with 2,212 approved
spoken blocks (about 121,250 words), the existing Grover reference and M4B output.
Copied source/visual/cover hashes match the legacy job. This attempt stopped at
a 240-second native-batch timeout after about 1,094 usable generated words; all
output remains intact. A replay showed shared-GPU-memory spill, not overheating.
Moving four expert layers to CPU reduced the same request from 179s to 33s.
New plans now bind that setting, 40/55-word ordinary units, and a 35-word maximum
for passages containing at least three semicolons. Existing plans retain their
original settings and identities. The affected 249-word real validation generated
all nine first-pass units below the frame cap; two capped retries were rejected,
and name/content flags remain for review. No acceptance gate was relaxed.

The owner confirmed the Foundry work was finished and authorized closing it and
resuming on 2026-10-15. Native inspection found Foundry already closed, no competing
AI workload, and 868 MiB whole-board VRAM at idle. The guarded one-shot
`Output/Drama3_Migration_2026_10_15/restart_genesee_headroom.py` created and started
fresh Drama job `7554bee0-d4ec-4e79-8228-70ed8a00851b` at 13:17 Eastern. It uses the
approved pages 5–355 and all 2,212 approved blocks; copied hashes and the unchanged
legacy state/source/cancellation flag were verified. Both prior jobs/audio remain
preserved. Startup verification confirmed the saved four-CPU-expert-layer profile,
40/55 ordinary limits and 35-word list cap. Three batches (12 requests, 428 words)
completed without frame caps; sampled whole-board VRAM was 19,196 MiB at 44 C.
This is startup evidence only. Full-book completion and content review are pending.
Its manifest is `Output/Drama3_Migration_2026_10_15/genesee_drama_headroom_job.json`.
At the owner's authorized 15:55 Eastern checkpoint, the one-time controller paused
this exact job through the normal API. The app records the pause as `canceled`
with its cancellation flag; completed audio is retained. The controller and both
checker processes have exited. There are 39,713 generated/provisional words of
121,204 (32.8%), 984 completed clips and 4h13m of audio. The 248 completed native
batches have no failed exit records or frame-capped saved takes. About 5h20m of
first-pass rendering remains at the observed pace, excluding checks/repairs/review.

The isolated audit checked all 984 clips plus 30 frozen owner-labelled controls
with Parakeet, then used Whisper on all 102 primary flags, 30 seeded random passes,
and the controls. Sixty primary flags clear the narrow year/date diagnostic;
80/102 clear that diagnostic or the independent diagnostic comparison. All 30
random passes also pass Whisper. Twenty-two clips still flag with both recognizers
after number normalization: twelve have substantial missing continuation and
near-silent tails already present in raw model WAVs, not introduced by loudness
normalization. The other ten include names, formatting and content discrepancies,
including an apparent added ending. These findings do not establish a cause in
the shorter unit policy or certify natural delivery. Aggregate passage gates still
produce many flags; no acceptance rule or approval was changed.

All 3,997 protected checkpoint/audio/control files were hash-identical after the
audit. Evidence, the detailed report and three unchanged example clips are under
`Output/Drama3_Migration_2026_10_15/pulse_1555/`. The owner authorized resuming after
the D&D session on 2026-10-15. The existing job resumed through the normal API at
22:32 Eastern after all 3,997 protected files matched their checkpoint hashes.
The local service had exited and was restarted as PID 27400 on port 8765. Foundry
remained open; sampled rendering used about 20 GiB of 24 GiB whole-board VRAM.
Saved work was reused and the first resumed batch advanced the count from 39,713
to 39,887 provisional words. The audit findings remain unresolved review evidence;
resuming does not approve those clips. Evidence is in `post_dnd_resume.json` and
`post_dnd_preservation.json` in the same private migration directory. The owner explicitly
deferred additional models and pipeline changes; existing Parakeet/Whisper only
were used. No regeneration, model/environment installation, upload or recurring
automation occurred.
Storybird was reloaded with this fix before the first run (then PID 18428);
the Desktop shortcut continues to launch the current checkout. Validation passed
424 base-suite tests (112 dependency skips), 172 shared audio-runtime tests,
15 Drama tests and 13 listening-review tests.

For Drama implementation, validation, review limits and runtime paths, read
`DRAMA3_MIGRATION.md`. Private evidence is under
`Output/Drama3_Migration_2026_10_15/`. The owner requested the three listening clips
on Drive; that folder and all three files were verified owner-only. All 12,756
baseline job/audio/audit files remain hash-identical at the preservation check.
The legacy VibeVoice Genesee job is still canceled with its cancellation flag.
This authorization is for a new Drama job, not a
legacy resume, model cleanup, installer build or release.

## 7B retired; Drama 3 comparison — 2026-10-15 (current authority)

The owner removed VibeVoice 7B because its cost and artifacts were unsatisfactory.
Its weights and the Drama 3 Q4 file are deleted. Genesee's `repair_model` and
`repair_unit_ids` settings are removed; 418 saved 7B render requests were archived
byte-for-byte. All generated audio and candidate provenance are retained. The
primary model remains VibeVoice 1.5B, and Genesee remains paused. Configuration
cleanup does not authorize resume, new repairs, or replacing the narrator.

The owner found both Drama 3 Q3/Q4 listening samples satisfactory, strongly
preferring Q3 for Help. The subsequent authorized Q2/Q3 comparison completed six
Q2 takes: 3.19x real-time generation versus the original Q3's 3.11x. This small
difference is not a demonstrated repeatable speed gain. In the blind comparison,
the owner strongly preferred Q3 for Help (Q2 sounded robotic), preferred Q3 for
the initial-name passage, and slightly preferred Q2 for attribution. The owner
selected Q3 and requested Q2 removal; its 17.05 GB weight file is now deleted.
The comparison recordings and results are preserved.
For evidence, model hashes, cleanup verification and blind keys, use
`Output/Drama3_4090_2026_10_15/q2_comparison/REPORT.txt` and its linked records.
Q3 remains an isolated experiment; VibeVoice 1.5B remains installed.

## Genesee paused for checker audit — 2026-10-15

The owner explicitly paused generation and requested a rejection audit. Keep
Genesee paused until further instruction. The app stores this as `canceled` with
`cancel_flag.txt`; no narration workers remain. Before checker changes or resume,
read `Output/Repair_2026_10_14/checker_audit/DIAGNOSIS.txt` and its linked evidence.
All 331 first-round 7B candidates were replayed: 234 unit rejections, 21 additional
parent-triggered retries, 76 valid units. A diagnostic year/date comparison clears
131 unit rejections and four parent rejections. Five of sixteen owner-approved
controls were falsely rejected by the unchanged gate. These are gate outcomes,
not proof of artifact-free speech. Independent GPU ASR and same-WAV Parakeet tail
probes demonstrate two false missing-sentence reports; batching alone is ruled
out in those cases. Real repetition, garbled initial/name wording and a changed
year also remain. Production checking and queue decisions are unchanged; only
diagnostic artifacts were added. No speech was regenerated during the audit.

## Authorized Genesee resume with selective 7B repair — 2026-10-14 (historical)

The owner explicitly instructed: "Continue 1.5B; use 7B for problem passages."
This supersedes the production-stop and unapplied-migration status below.
The primary plan remains pinned to the original 1.5B model. The job now has an
explicit local 7B Q8 repair-model fingerprint, run in its own GPU process at
batch one after primary workers exit. Parakeet runs after TTS exits; Qwen stays
disabled. Failed primary candidates switch to 7B, with at most three repair
attempts before review. Model identity and intact-context policy are recorded in
the repaired unit receipts and reports; old listening approvals do not transfer.
This is an authorized production attempt, not a claim that musical/ringing
artifacts have been perceptually eliminated. ASR cannot certify those artifacts.

Private applied manifest and backups: `Output/Repair_2026_10_14/resume/`.
Fourteen owner-rejected examples map to fifteen repair units across fourteen
parents, including the adjacent unit affected by the John I. Miller boundary.
Ten source-bound spoken corrections apply only to those rejected clips.
The other 1,066 unit descriptions retain their prior text and delivery policy.
All sixteen owner-approved WAV hashes are preserved and their exact existing
takes have listening approvals. Five of those takes were previously rejected by
ASR and are restored from retained candidates without modifying their originals.
Canonical book text and primary plan identities remain intact. Existing-job
resume now preserves projection, scoped boundaries, delivery and repair settings.
The local server was started and normal resume accepted this job. Verification
confirmed active generation, an unchanged primary plan and all sixteen approved
WAVs intact. The old saved retry queue also routes to 7B: after a brief controlled
restart, 331 repair units are queued/in progress, with 166 existing 1.5B candidates
awaiting the separate Parakeet phase. At this snapshot 70 parents are assembled;
the book is still in progress. `resume/verified_status.json` records the check.
Validation: the 171-case VibeVoice suite, the final 21-case phase suite and 13
narration-review tests pass; the latter's
localhost checks require native execution outside the socket-restricted sandbox.
No commit, installer, release, upload or recurring monitor was requested or made.

## Diagnosis of rejected audio — 2026-10-14 follow-up (superseded stop status)

Before further narration repair or an engine change, read the private report
`Output/Repair_2026_10_14/diagnose/DIAGNOSIS_AND_FIX.txt` and its `results.json`.
Five rejected WAVs reproduced byte-identically; ten raw fragments showed only
scalar gain during normalization. The intact failures originate in synthesis.
Both model weight sets match their pinned hashes. Shortening the reference did
not resolve the Help failure. Matched 7B and original Chatterbox probes recovered
the short dialogue words; full 7B verification removed the observed nonsense
syllables but retained minor transcript differences. A source-bound phonetic
initial override is prepared for eleven occurrences, with canonical text intact.
All proposals remain private and unapplied. The owner clarified that artifacts
include BOTH garbled speech and musical/ringing sounds. Perceptual repair is
unverified; keep production blocked and present no further listening batch until
there is a concrete validated fix. An engine change requires a new model identity
and fresh approvals; the source-only migration manifest does not authorize it.

## Owner rejected the five repair auditions — current acceptance status

All five recordings in `Output/Repair_2026_10_14/listening/` were rejected by
the owner: artifacts in both Help takes, unintelligible/artifacted tiny dialogue
under both policies, and the middle initial still spoken as "the first".
All five passed the raw Parakeet gate; transcript passes did not certify audio.
This supersedes the earlier migration recommendation below. Source/recovery/cache
regressions remain supported; audible delivery and initial pronunciation remain
unfixed. Keep production migration blocked and Genesee stopped. The intact-context
alternative is not approved. The five-recording budget for this round is exhausted.
Before further repair work, read `Output/Repair_2026_10_14/owner_feedback_five.json`
for exact feedback and verified hashes, then the updated migration report. Diagnose
existing rejected audio first; preserve the prior 30 labels and all original WAVs.

## Repair implementation and isolated comparison, 2026-10-14

The authorized handoff in `Output/Transcript_Review_2026_10_14/IMPLEMENTATION_HANDOFF.txt`
has been implemented and evaluated in the working tree. Production migration is
NOT applied. Genesee remains stopped, Qwen remains disabled, and no installer,
commit, upload, app restart or production resume occurred. The owner's existing
CLAUDE changes below are preserved verbatim.

Start with `Output/Repair_2026_10_14/REPAIR_AND_MIGRATION_PLAN.txt`. Its private
JSON manifests contain every old/new unit identity, canonical/spoken text, policy
and audio hash, source evidence, affected frozen label and reassembly requirement.
The base proposal changes 255 index rows across 170 parents: 253 existing indexes,
two additions and one retirement among those existing indexes. Of these, 132
indexes have existing audio and ten parents have assembled WAVs. 828 unchanged
unit identities remain untouched; the proposed unit count is 1,082. The optional
four-unit intact-context alternative is separate (258 rows / 172 parents).
Neither proposal authorizes automatic replacement or production resume.

Waveform normalization is shared; >100 ms and <400 ms valid signals retain timing
and gain with a 0.95 peak limit, without padding/tiling. Ordinary normalization
matches the prior algorithm within 1e-7 in regression tests. Recoverable render
exhaustion is local to its unit; saved candidates/failure history survive later
failure or interruption, while no-WAV failures remain explicit and block assembly.
Systemic errors still surface, cancellation terminates owned phases, and an
explicit listening retry starts a fresh bounded budget without losing evidence.

Existing jobs default to legacy sentence boundaries; new plans select initials_v2.
No global split revision was bumped. The explicit migration adds name/initial
integrity and one source-bound projection used for rendering, checking and review.
The private correction inventory contains 15 proven page-boundary word repairs,
19 visually confirmed superscript removals, one PDF-absent OCR instruction removal,
and 300 conservative calendar/clock edits. Suspended hyphens and genuine compounds
remain protected; there is no blanket dehyphenation or global name respelling.
Frozen render policies plus spoken/render hashes protect unit receipts, parent
reuse and approval fingerprints. Old review boundaries are rejected after an
explicit migration; approval never transfers to new audio.

28 fresh matched GPU renders compared current splitting and intact context across
seven cases and seeds 1729/2718, with identical source corrections. All completed
without generation failure or automatic retry. Including the separate name
example, TTS took 887.1 seconds. Five synthetic timing controls followed; GPU
Parakeet ran only after TTS exited (34 checks, 29.0 seconds including load).
Raw transcript-gate passes were 7/14 split and 9/14 intact; this is not delivery
certification. One empty C07 transcript persisted on a separate unprompted check.
C12 has a long nonsource ASR span in one split seed, while both intact takes avoid
that span; spelling/year/acronym differences still produce flags. Do not infer
a book-wide rate or claim pronunciation from ASR spelling.

Duration and semantic candidates remain SHADOW ONLY. A duration fit on 14 approved
fragments flagged two of 12 held-out approved fragments and missed seven of eleven
owner delivery errors. Numeric/negation diagnostics flagged eight of sixteen
wholly acceptable owner clips and benign held-out controls. No new universal
insertion, short-span, ratio, duration or semantic retry gate was adopted. Strict
heading checks remain intact. Whisper is not an accept-if-either authority.

Exactly five listening recordings are prepared at
`Output/Repair_2026_10_14/listening/index.html`: two blind pairs and the repaired
initial-name example, 113.8 seconds total. Selection was fixed before new ASR
results. Pleasantness, rushing and actual initial pronunciation remain listening
questions; no additional audition batch or narrower split arm was run.

Verification: 192 relevant tests passed (168 VibeVoice, 13 narration review,
11 transcript review). A private real-job copy invalidated only its affected
parent while preserving all copied audio/receipts. SHA-256 checks found zero
changes among 11,980 protected production/evidence files. Source fixes, synthetic
fixtures and isolated inference evidence are separate. Graft was fully rebuilt
with native Windows Git access and checked; Python-only coverage limitations in
GRAFT_INDEX.md still apply. No purchased source or generated audio was staged.

## Owner listening labels and boundary traces, 2026-10-14 evening

The owner completed C01-C30 and exported the blind labels. Preserve the original
at `Output/Transcript_Review_2026_10_14/owner_labels_30.json`; all 30 label/audio
hashes verified. Start with `OWNER_FINDINGS.txt` for the follow-up. Sixteen clips
passed all three axes; fourteen have at least one owner-reported issue, including
minor delivery concerns. There are 6 content errors, 9 pronunciation errors and
11 delivery errors, with overlap. A definite error remains a failure when another
axis is uncertain; the private scoring script now handles that correctly.

This partial sample contains 8 random previously accepted clips (all acceptable),
9 random flagged clips (3 acceptable / 6 with issues), and 13 targeted clips
(5 acceptable / 8 with issues). Do not call 14/30 a whole-book defect rate.
On the rated subset, the current gate clears 3 reported problems and flags 5 good
clips; current-plus-Qwen clears 1 problem and flags 8 good clips; the strict narrow
prototype clears 1 and flags 12; Whisper/current gate clears 7 and flags 3.
C04 is missed by every candidate; Qwen is not invoked for its transcript because
ASR reproduces the initial, hiding the owner's reported pronunciation error.

Specific traces: C12 retains a split word across PDF pages 345/346 in both extracted
blocks and narration input; `stitch_pages` joins with a space without dehyphenation.
C04 ends a chunk at a middle initial, separating the surname despite complete
parent text. C03's stray digit is a visually confirmed superscript endnote marker
on PDF page 204 that survived into spoken text. These are source/chunking problems.
C07's two 200 ms joins at 39.07/39.80 s align with the reported parenthetical
delivery defect. C27's attribution split at 26.47 s aligns with its abrupt ending.
C24's first synthesis fragment ends after the quoted exclamation; its first PCM
join starts at 18.53 s, so the reported artifact around 12 s is within generated
audio before the join. Do not claim a crossfade alone fixes it or that exclamation
punctuation alone is proven causal. C12 also has short, punctuation-led fragments.

Next recommendation: fix source projection and name boundaries, then compare intact
context against automatic quote/aside splitting on a small matched set. No production
fixes, new renders, approvals or resume were performed in this labeling follow-up.
Genesee remains stopped and Qwen remains disabled. The owner has ADHD and found the
60-clip task too burdensome: this round is finished at 30. Future listening requests
should normally be 3-5 clips with a specific decision, not another large review queue.

## Evidence review after the broad audit, 2026-10-14

The owner explicitly authorized interrupting Genesee to produce the audit's
findings and recommendations. This supersedes the earlier pause-approval block.
Evaluation only: no automatic Qwen approval, regeneration, job-configuration
migration, or production restart was performed. Genesee remains stopped, with
reviewer integration disabled. Its existing render failure preceded the authorized
pause: pyloudnorm rejected an audio fragment shorter than its 400 ms block;
the renderer's earlier minimum-length check permits fragments over 100 ms.
Fix and verify that boundary before resuming; do not infer that dialogue splitting
caused the short generation merely from this exception.

Private evidence and runnable evaluation scripts are under
`Output/Transcript_Review_2026_10_14/`; start with `REPORT.txt`.
The frozen sample is 20 randomly accepted, 20 randomly flagged, and 20 targeted
clips, seed 20261014, from 1,081 first-check records (580 not scheduled, 501
scheduled). Targeted clips must never enter prevalence estimates. The blind
listening page has separate content, pronunciation, and delivery labels, exact
audio identities, browser saving and JSON export. Human labels were pending at this
stage; the later 30-clip follow-up above supplies limited audio-grounded results.
Whole-book error rates and end-to-end savings remain unestablished.

GPU-only, sequential replay on the same 60 WAVs: Parakeet 18.80 s including load,
Whisper 140.01 s. Fresh Parakeet transcripts exactly matched 59/60 saved reports;
the remaining spelling variation had an independently hash-bound WAV. All 32
chronologically associated archived takes reproduced the saved transcript exactly,
which corroborates but does not replace missing historical audio hashes.

Qwen shadow replay requested 52 reviews: 43 structured decisions and 9 unfinished
responses; 8 clips did not trigger it. Total 37.83 s including load/unload; median
successful review 0.627 s. A targeted replay confirmed `done_reason=length`, 192
output tokens. The observation harness continued after failures; production would
stop and retain audio at the first such failure. It cleared 2/20 randomly flagged
clips but newly blocked 8/20 randomly accepted clips. These are decision changes,
not demonstrated repairs or false positives. The strict private deterministic
prototype also increased review burden and is not a replacement ready to deploy.

The first 42 synthetic cases rejected all 24 planted errors and cleared 11/18
harmless variations. A new 24-case control set then exposed an ACTUAL Qwen false
equivalence for a paraphrase with changed words. It cleared 7/8 harmless controls
and 1/16 deliberate fidelity errors; the old gate passed 13/16 errors. The first
set overlaps prompt examples and is not independent validation. Do not enable
Qwen as an approval authority on these results. Its raw replacement override
remains unsafe even though insert/delete protections exist. LLM explanations are
also fallible: one real-clip response described a curly apostrophe as an em dash.

Three PDF pages were visually spot-checked against extraction and plan, separately
from audio. The frozen job omits chapter number 15 on PDF page 221; page 87's opening
continuation is preserved in the previous merged block/passage. This is limited
source inspection, not whole-book extraction certification. Existing recordings
use 2,645 delivery calls for 1,081 units (605 multi-call units); intact-context
rendering remains a justified experiment, not a demonstrated speed/quality fix.

Recommended order: obtain blind listening labels; replace the known five-word /
numeric policy defects with narrowly tested rules; assess selective second-ASR
triage on those labels; only then run a bounded intact-context VibeVoice comparison
and matched Chatterbox baseline if needed. Keep Qwen observational. Count actual
review time, failed responses, retries and rechecks when measuring total work.

## GPU-only inference and local transcript reviewer, 2026-10-14

The owner explicitly rejects CPU-only model inference because it is too slow on
this RTX 4090 workstation. Use GPU inference and serialize competing model stages;
do not introduce silent CPU fallback. This supersedes older CPU-checker and
CPU-acoustic-model recommendations below. Ordinary application logic, file I/O,
and synthetic unit tests are not model inference.

The owner authorized a small local LLM to review narration transcript differences.
Year pronunciation is part of fidelity: a year such as 1999 should be read
"nineteen ninety-nine", not "one thousand nine hundred ninety-nine". A comma
helps distinguish a quantity (1,999), but context is also necessary. Do not excuse
wrong year pronunciation merely because its numerical value matches.

Qwen3-4B-Instruct-2507 Q4_K_M has been downloaded through the existing Ollama
installation (2,497,293,803 bytes, manifest digest
`0edcdef34593eac1aa2be9c7d06c432dcf81945adca5eca2f27662c18f168ba0`). Source integration
is being validated and remains disabled. It runs after the Parakeet GPU process
exits, before retry scheduling, checks full GPU residency, and unloads afterward.
Original ASR reports and transcripts are retained; stored decisions bind exact
source/transcript hashes, model digest and review policy. Uncertain cases retain
audio for listening, and no human listening approvals are invented.

The 159 affected synthetic regression tests passed across quality comparison,
review, phase scheduling, unit/parent reuse, legacy repair, runtime audio, server
configuration and progress. Python compilation, embedded JavaScript syntax,
Graft reparse/check, and whitespace checks also passed. These are implementation
checks, not evidence of the model's judgment accuracy. The one-shot 42-case GPU
benchmark is prepared under `Output/Transcript_Review_2026_10_14/benchmark.py`;
it refuses to run while an app job is actively extracting or narrating.
Forced worker cancellation also releases the reviewer through the owning server
after worker termination; a regression verifies that another phase does not
trigger this cleanup. The review dialog exposes the model's reason as escaped text.

An initial automatic approval rejection prevented pausing without explicit owner
permission. The owner subsequently granted that permission; the completed GPU
evaluation and narrower recommendation are recorded above. No job settings,
audio, approvals, or application restart were changed for this integration.

## Restart recovery and targeted Chatterbox repairs, 2026-10-14

The owner authorized Chatterbox band-aids while retaining VibeVoice as the main
narrator. The Voice now has six Chatterbox clips: 59/1, 59/3, 71/3, 77/3, 85/1,
and 85/3, using its existing narrator reference. Four were saved retries; two
neighboring failures were independently confirmed during checking. Each replacement
has explicit Chatterbox generation provenance in its unit receipt. All other
speech clips and listening approvals were preserved; 1,488 of the 1,508 baseline
checkpoint files are byte-identical. The 20 changed files are six unit WAV/receipt
pairs and four rebuilt parent WAV/receipt pairs. No listening approvals were added.

Unprompted Whisper checked every final replacement. Parakeet cross-checked the
initial four; its disagreement on 71/3 was retained, with Whisper as that clip's
primary checker. DNSMOS and NISQA scored the generated takes. The last 85/1 take
had a trailing addition after its final source word; trimming within the measured
320 ms gap removed 0.48 seconds, and a fresh Whisper check matched the text exactly.
All 113 parents passed assembly. The new 3:20:50 M4B is published in
`audiobooks/The Voice (2)` and fully decoded without errors. The previous export
remains in `audiobooks/The Voice`. Private scripts, backups, hashes and reports
are under `Output/Chatterbox_Patches_2026_10_14`. This was a targeted repair, not
an automatic fallback feature or a change of the book's main engine.

The comparison gate now recognizes eight unambiguous pronoun contractions such
as I am/I'm. Ambiguous forms, identifiers, repeated words and real omissions stay
different. All 45 affected quality, review and unit tests passed with GPU access
disabled. The running app imports this source change on its next normal restart;
the repaired book was validated and assembled in a fresh process using the fix.

Genesee Junction resumed through the app, preserving all 622 saved WAVs checked
at restart. Its two GPU render workers are active. Additional Voice repairs,
verification and assembly used CPU after Genesee resumed. Final API readback:
Genesee narrating, The Voice done, neither reporting an error. No runtime install,
commit, installer, release or upload was performed.

## Homophones, added-speech labels, and live worker check, 2026-10-13

The owner reports that source-empty differences usually correspond to bad audio,
and specifically confirms many audible artifacts in The Voice passage 59 clip 3.
Its existing fingerprint-bound retry decision was preserved. Private feedback
and a read-only cached-review comparison are under
`Output/Homophone_Review_2026_10_13`. The current five-item saved review had no
differences affected by the new homophone rule; decisions remained byte-identical.

The shared word checker now aligns a bounded list of common homophones (including
be/bee) as identical sounds. It preserves original words, protects identifiers,
and still counts extra occurrences and adjacent genuinely changed words. It does
not use fuzzy phonetic matching or generalize to names or ambiguous read/red.
The UI replaces `(nothing)` placeholders with explicit possible-added-speech and
possibly-skipped-words labels. This is a checker/UI correction, not an audio repair.
All 43 focused quality, review, and unit tests passed, with worker tests run in the
isolated narration environment with GPU access disabled. Browser checks verified
both labels and escaping. The running server's imported checker updates on its
next restart; new checker subprocesses use the updated source. No restart occurred.

The Devil at Genesee Junction is now job `f48b73b5-ba59-4604-9015-811f0d1d2608`,
narrating with two render workers and native batch size four. The Voice is queued.
A live RTX 4090 reading showed 13,965/24,564 MiB VRAM and 97% GPU utilization.
Two workers remain the measured configuration (about 28% faster than one in the
earlier controlled test); three/four workers have not been benchmarked. Worker
settings, queued decisions, generated audio, and the active run were not changed.

## Optional final-text preview, 2026-10-13

The owner explicitly rejected an additional full-text review after saving the
flagged passage choices. Saved treatments now suffice to start narration.
The full-text preview remains optional and read-only. Its receipt is no longer
required by the UI, start endpoint, direct narration, resume/worker gate, or new
regeneration jobs. Old preview-required fields on existing jobs are ignored.
The ready book card offers Start narration directly, with Edit narration choices
as a secondary action, so saved choices do not require reopening review.
Unresolved treatments, unsaved UI edits, and empty narration still prevent start;
spoken-projection signatures still protect audio cache identity and stale output.

All 46 visual-review tests and 8 finished-output tests passed. Browser checks
confirmed that saved choices enable Start without any preview request, edits
block it until saved, and unresolved choices remain blocked.

The running server still had the old code. The Voice failed with a render-phase
error and then resumed before restart; the idle check prevented any app closure.
The Devil at Genesee Junction was queued at position 1 behind it using its eleven
unchanged saved choices. As a one-time compatibility step the running server's
projection was loaded programmatically, without asking the owner to inspect it.
The new server behavior loads on the next ordinary app restart. No narration
worker was interrupted, no audio-review approvals were added, and no release was
built. Private evidence: `Output/Optional_Preview_2026_10_13`.

## Discoverable visual-review completion, 2026-10-13 (preview gate superseded above)

The Devil at Genesee Junction had all eleven currently flagged treatments saved
and zero unresolved items, but no final-preview receipt. The remaining preview
and Start controls were buried below long passage context. The visual-review
dialog now scrolls its content separately from a persistent footer containing
explicit preview/start actions and the next required step. Existing server-side
preview and decision gates remain in place. Late preview responses from a closed
session or superseded review are ignored; failed previews can be retried.

All 37 visual-review integration tests passed. Browser checks with long synthetic
context verified visible actions at desktop and a 501-pixel narrow viewport,
preview-to-start, edit/save invalidation, unresolved blocking, failed-preview retry,
and stale-response rejection. No real job was started or approved during testing.
The Voice remained narrating. The already-open native window keeps its loaded UI;
its existing bottom-of-dialog preview/start controls still work, and a fresh page
load gets the improved layout without restarting the server. No release was built.

## Selected twelve-clip regeneration, 2026-10-13

The owner authorized regeneration of 49/2, 59/3, 67/1, 67/3, 71/2, 71/3,
72/2, 77/3, 85/1, 85/3, 98/3, and 99/3. All twelve now have new audio hashes;
all 380 protected peer audio/approval files remained unchanged. Selected originals
and receipts are backed up under `Output/Regenerate12_2026_10_13/before`.
No other clip was scheduled and no listening approvals were added.

After up to three attempts, only 99/3 cleanly cleared the combined content and
acoustic checks. Eleven remain in review. Independent unprompted Whisper confirmed
substantive additions, omissions, or corrupted speech in most; 71/2 retains an
acoustic outlier and disputed extra words. In particular, 67/3's two added words
and 72/2's three omitted words can pass the five-word gate but are not evidence
of faithful narration. All twelve were also scored with DNSMOS, NISQA, and
NISQA-TTS across 141 windows. Better acoustics did not establish correct wording.

The final render for 77/3 failed recoverably, and exhausting its limit stopped
the coordinator before it resolved the later checked clips. The exact renderer
error was not logged. Two earlier new takes were saved in rejected audio. The
second was freshly rechecked using the normal Parakeet phase, then published as
a listening candidate with its actual attempt number. Remaining checked clips
were resolved without rendering again. A relative report path from this manual
check was corrected to its verified absolute in-job path before normal cache-only
resume restored `audio_review_required`. No application source fix was made for
the exhausted-render recovery gap. The book is not assembled. See the private
`REPORT.txt`, `results.json`, `recovery.json`, and preservation evidence in
`Output/Regenerate12_2026_10_13`. No installer, release, commit, or upload occurred.

## Local acoustic-quality models and review triage, 2026-10-13

The owner requested installation, validation, and use of DNSMOS and NISQA on
The Voice's current review clips. A dedicated CPU-only Python environment is at
`runtime/acoustic-quality`; official source and weights are under
`runtime/models/acoustic-quality`. The source receipt records upstream commit IDs,
URLs, byte sizes, and SHA-256 hashes. No existing narration/ASR environment changed.
DNSMOS weights total 1.38 MB, NISQA v2 1.05 MB, and NISQA-TTS 1.24 MB. The dedicated
runtime occupies approximately 1.88 GB. NISQA weights are CC BY-NC-SA 4.0; this is
an owner-authorized personal installation, not authorization to bundle a release.

Private evidence and reusable inference scripts are in
`Output/Acoustic_Quality_2026_10_13`. All 32 current review clips and 25 previously
owner-approved clips were scored in 553 overlapping windows. Forty validation
windows comprise eight unchanged samples and their noise, clipping, dropout, and
click variants. All 32 degraded variants scored lower than their originals on each
model's overall metric. NISQA's mean quality fell from 4.97 to 1.49/1.55/2.02/1.99;
DNSMOS was less sensitive to non-noise damage. NISQA batched/single-file predictions
agreed within 0.000001. CPU scoring took about 185 seconds for the real windows,
with a 1.35 GB peak working set. Dependency checks passed. Clip 99/4 is 3.067 seconds;
its whole recording was scored, with DNSMOS's upstream short-input repetition.

NISQA found windows below every approved baseline window in 59/3, 98/3, 77/3,
71/2, 85/3, and 67/1. These are acoustic leads, not a calibrated rejection gate.
Several known content failures still score well acoustically: fluent unrelated
speech is not necessarily noisy. Keep ASR content verification separate. No app
quality gate, listening approval, original WAV, or regeneration state changed.

The book is awaiting audio review, superseding the running-generation snapshot
below. A fresh independent Whisper audit of its current 32 clips found strong
content-error evidence in 49/2, 59/3, 67/3, 71/2, 71/3, 72/2, 77/3, 85/1, 98/3,
and 99/3. The owner says name and word-ending differences are generally acceptable
when heard; 18 clips were deprioritized on that basis without inventing approvals.
Four uncertain checks (43/3, 67/1, 85/2, 85/3) were shortened to a combined 67-second
private Drive listening file. Evidence: `Output/Short_Review_2026_10_13`. The new
acoustic evidence raises the priority of 67/1 and 85/3; it does not establish that
43/3 or 85/2 has no added speech. No new narration, installer, or release was run.

## Reviewed retry queue and partial decisions, 2026-10-12

After generation reached 88/113 verified passages, the owner requested a check of
the 25-passage listening queue. Four passages already had decisions; independent,
unprompted Whisper large-v3 checked the remaining 30 clips in 21 passages. Seventeen
passed the existing word gate and 13 failed. Several failures contained substantial
unrelated speech corroborated by Parakeet. This was a word-level audit, not listening
approval of delivery or pronunciation. Evidence: `Output/Review25_2026_10_12`.

The owner later authorized GPU use and resume. The 13 audited failures were marked
retry through the app API, alongside two existing owner-selected retries. No new
listening approvals were added. Seventeen clips remain undecided for later review.

A partial-decision scheduling bug held passage 99 clip 3 behind its undecided peers.
The Parakeet scheduler now excludes selected retries from the deferred-review set
and removes an obsolete review candidate when its replacement passes. A regression
reproduced the skipped retry before the fix and now verifies that only the selected
clip renders, its replacement supersedes the old candidate, and the undecided peer's
audio stays unchanged. All 141 narration-runtime tests passed.

The live job was restarted at a saved batch to load the fix. It has exactly the 15
requested clips pending, including four already-generated replacements reused from
before restart. Both render children are active. All 82 saved approved audio/receipt
files and 331 other audio files were unchanged after resume, as were the four ready
replacement WAVs. Retry generation/checking remains in progress. No installer,
release, commit, upload, recurring monitor, or additional runtime install occurred.

## Two independent GPU render workers, 2026-10-12

The owner authorized a two-worker comparison and implementation/resume only if
faster without reducing quality, preserving every already-generated/approved clip.
Private evidence is under `Output/Workers_2026_10_12`. An eight-clip synthetic
workload (dialogue, asides, and plain narration) ran in 1/2/2/1 worker order.
One-worker runs took 208.50/206.54 seconds; two-worker runs took 151.34/146.22
seconds, including model startup/shutdown. Mean generation time fell from 207.52
to 148.78 seconds (28.3% less time). Fixed per-clip seeds produced byte-identical
WAVs for all eight clips across all four runs. All 32 clip and parent checks
passed Parakeet. This is sample evidence, not a whole-book timing guarantee.

The Parakeet workflow now supports `render_workers` 1 or 2. Children own disjoint
units by fixed plan order, so completed work cannot shift another child's
assignment. The coordinator prepares the voice once, starts both render children,
and waits for both to exit before starting the single GPU checker. Failure or
cancellation terminates and joins every child. Each two-worker model has a 40%
CUDA allocator cap; the single-worker cap remains 85%. Voice, delivery profile,
model settings, existing receipt identities, retry limits, and quality gates are
unchanged. Portable defaults remain one worker. This owner's ignored app config
and The Voice sidecar now select two render workers.

Validation: full native suite 364 tests passed (79 dependency skips);
all 140 narration-runtime tests passed, including stable partitioning, two-child
cancellation, peer failure cleanup, and the UI worker count. All 1,175 saved book
checkpoint files were unchanged before enabling the setting. The real production
coordinator generated and verified four synthetic passages in 93.66 seconds;
cache-only replay left all 20 audio/receipt files unchanged. The two render
children used about 15 GiB total GPU memory with about 8.7 GiB free and 97%
utilization during the observed sample; Parakeet ran only after both exited.

Storybird was restarted and The Voice resumed successfully. Live verification
showed one coordinator and exactly two GPU render children, with no GPU checker
overlap. The 925 preserved files (existing audio, completed/approved receipts,
ready provisional clips, and the canonical plan) were byte-identical after
resume. The other 251 baseline entries are unrendered work receipts that will
advance as new audio finishes; none was discarded. Book narration is still in
progress. No installer, release, commit, or upload was performed.

## Generate-first Parakeet workflow and book rerun, 2026-10-12

The owner selected NVIDIA Parakeet after a local comparison, requested deletion
of Granite, and authorized rerunning The Voice with the new workflow while
preserving regenerated/approved clips. This supersedes the older CPU-checker
and awaiting-listening snapshots below. No installer or release was built.

`vibevoice_phases.py` implements `generate_first_parakeet_v1`: render all pending
units in one GPU process, exit that process, check all provisional clips in a
separate Parakeet GPU process, then render/check failed clips in bounded rounds.
The existing unit receipts, cumulative parent gate, exact listening approvals,
archiving, cancellation, and final assembly are reused. Interrupted checking
resumes verified provisional WAVs without rendering them again. Exhausted clips
go to listening review while other passages finish. The progress message names
Parakeet on GPU. This workflow currently reports phase progress without an ETA.

Parakeet is `nvidia/parakeet-tdt-0.6b-v3`, revision
`541d1f99c6b0c3cd0b11a95167540bb8edefd82b`, native Transformers 5.19.0 TDT,
float32, batch 4 with OOM bisection. The local dedicated runtime is
`runtime/parakeet/Scripts/python.exe`; weights are at
`runtime/models/parakeet-tdt-0.6b-v3`. This local venv reads the already-tested
compiled-runtime libraries without changing that environment. Chatterbox,
Fish, legacy VibeVoice, and dnd-transcribe environments were not modified.
`install/bootstrap_parakeet.py` supports dedicated fresh installation and
verification/registration of existing paths; its fresh-install path has not
been exercised on a clean machine. Registration checks the pinned weight hash
and stores the workflow as a literal, not a resolved path (regression tested).
New jobs use the configured workflow; existing sidecars retain their workflow
and checker paths unless explicitly migrated. Granite's downloaded model folder
was deleted at the owner's request; historical measurements remain private.

Private evidence: `Output/Workflow_2026_10_12`. The same 71 clips (~38 minutes)
took ~148 seconds with GPU Whisper large-v3, ~17 seconds with Parakeet, and
~8 seconds with Granite, including startup. All three caught six planted errors;
Parakeet flagged 2/25 owner-approved book clips, Whisper 6/25, Granite 17/25.
Batched Whisper was faster (~88 seconds) but dropped a five-word control phrase.
Two 990-word workflow comparisons averaged 285 seconds for CPU overlap and
182 seconds for generate-first/Parakeet (~36% lower). The implemented worker then
completed all 8 synthetic parents/12 clips on real GPU. A separate real repair
test rejected two planted bad clips, regenerated them together, and passed the
recheck while reusing ten peers. Book-source disagreements without listening
ground truth are not proof of ASR accuracy; expressive delivery still needs ears.

The Voice scan found 171 single-quoted dialogue-boundary clips: 12 already used
the new delivery profile and 159 used old rendering; 113 of those also contained
in-word apostrophes. These were candidates, not 159 confirmed audible defects.
The authorized broader rerun preserves 42/321 clips (all 27 exact listening
approvals plus other clips already using the delivery profile) and replaces 279
clips across 109 parents. `book_before_rerun` holds the original final M4B,
metadata/receipt backups, the exact selection, and protected file hashes.
All existing audio and the canonical plan were unchanged when queuing the rerun.
The live book now uses Parakeet and is actively generating; narration is NOT
complete. Protected clips and their approval receipts were verified unchanged.
The refreshed Storybird desktop shortcut opens the source app with `app/icon.ico`.

Validation: base suite 360 tests passed (76 runtime-dependent skips); 136
narration tests passed in the dependency-equipped runtime, including the seven
phase regressions. Native GPU generation and grouped-repair tests passed.

## Listening-review repair and spoken delivery, 2026-10-12

The owner reported non-playing review clips, delayed choices, a Windows progress
replace failure, spoken page citations, and rushed dialogue/parenthetical delivery.
The audio-review route held the per-job mutation lock while streaming audio. It now
validates and snapshots the selected clip under that lock, then sends bytes after
releasing it. Playback checks only the selected parent. Review players load on
demand, pause other players, release requests on close, expose reload feedback,
and show saving/failure status beside the selected clip. Requests time out after
15 seconds; stale dialog responses cannot update a reopened review. Choices do
not require playing through to the end. Clear choice explicitly restores listening.

VibeVoice progress now uses the existing bounded-retry, nonfatal progress writer.
A real Windows handle denying delete sharing reproduced the failure on a disposable
sidecar: narration survived, preserved prior valid JSON, and updated successfully
after unlock. Progress remains advisory; receipt/checkpoint writes still fail closed.

`vibevoice_delivery.py` omits parenthetical numeric p./pp. references, preserving
ordinary prose parentheses and any attached editorial prose. Projection spans
existing unit boundaries, including a split citation in passage 24, without
changing unit indices, canonical text, parent plans, or identities. The narration
checker compares intended spoken text; generic spelling/number assessment and its
five-word threshold are unchanged. New render receipts bind delivery profile and
spoken-text hash. Selected accepted parents are marked for reassembly/replacement;
old parent audio/receipts are archived before requested replacements publish.

The delivery profile inserts 200 ms PCM gaps at closing dialogue quotes and both
sides of parenthetical asides, with 5 ms join fades. In-word apostrophes and quoted
terms are not turn boundaries. Attribution stays with following speech to avoid
isolated tiny narrator fragments. Asides retain every word, render separately, and
use gain 0.84; no time stretching, pitch processing, pronunciation substitution,
or invented character voices. This provides explicit timing, not a guarantee of
natural acting or correct pronunciation in every language.

Private evidence: Output/Review_2026_10_12. Two local five-clip delivery runs used
the original voice. Final replacement candidates are staged for passage 14 clip 1,
28 clip 2, 33 clips 1/2, and 58 clip 2. Only 14/1 and 33/2 passed automatic word
verification; the other three were NOT approved. The earlier description of
these failures as only name/quoted-language disagreements was incorrect: passage
58 clip 2 also contained substantial unrelated recognized speech, and the owner
reported poor audio. These were not established as checker-only errors. All five
required owner listening for delivery. Passage 14's citation is
absent and its spoken transcript matches with only a safe spelling variant.
Other reference-bearing units are queued for targeted regeneration on resume.
Do not claim that the foreign-language pronunciation or overall delivery is fixed.

At the owner's explicit request, passage 10 clips 2/3, 24 clip 2, 91 clip 3 and
97 clip 2 were restored for listening rather than regenerating them for playback
failure. Their WAVs remain unchanged. Live browser playback loaded and advanced
all five, with durations 45.87/36.13/55.47/35.87/44.40 seconds and no media errors.
A separate synthetic browser fixture played briefly, paused, saved, cleared and
reopened choices successfully. A real HTTP concurrency regression held a stream
stalled while a choice saved. Original baseline: 501 WAVs. Every original WAV
remains either in place or archived; all accepted-parent and active-unit WAVs are
unchanged at handoff. Existing genuine regeneration choices and listening approvals
remain; no new listening approvals were invented.

The idle app was restarted through the refreshed Storybird desktop shortcut. The
book is now audio_review_required with TEN unresolved clips: the five restored
originals and the five revised delivery candidates. It was deliberately not resumed
because the owner requested listening first. Remaining scheduled replacements run
after those choices. The full suite passed 348 tests with one skip; final focused
checks passed 37 tests. Graft wiring and whitespace checks passed. No installer,
release, commit, upload, checker-model switch, or DND environment change occurred.
Whisper large-v3 remains CPU/int8 with its original unprompted transcription. Its
model card acknowledges hallucination; a second recognizer needs an audio-grounded
comparison before replacing it, especially for names and unsupported languages.

## Checker workflow and optional compiled inference, 2026-10-12

The owner requested the checker/workflow fix and compiled inference including
Transformers' September 21 batch-row fix. Safe spelling normalization now uses
an explicit UK/US whitelist and exact spacing/possessive equivalences. Adjacent
safe variants are recognized together. Names, homophones, missing words, numbers,
and substantive edits retain the existing gate; the five-word budget is unchanged.
Review shows individually failing clips rather than every passing sibling, while
still enforcing the cumulative parent gate. Previously retained candidates that
now pass can be recovered with validated receipts, without fabricated approvals.
The progress bar reports generated words separately from verified passages.

Private recovery on The Voice recovered nine of twenty pending parents, leaving
11 parents / 23 clips for listening before resuming. All 320 raw quality reports
and all 110 pre-existing accepted-parent WAV/receipt files were unchanged. Of
548 baseline checkpoint files, 546 were byte-identical; two unit receipts were
updated through validated recovery. No audio was regenerated for this recovery.

`app/vibevoice_hf.py` implements an isolated Transformers compiled backend, pinned
to Transformers 5.19.0 (includes upstream #48902, September 21), Torch 2.10.0+cu128,
and triton-windows 3.6.0.post26. The HF model is `vibevoice/VibeVoice-1.5B-hf` at
`d4cd82eb4371bf3e3d088e1ea7fa4eefb60449bf`. It uses BF16, SDPA for the text model,
static KV caches, torch.compile default mode, local-only assets, existing 85%
GPU allocator cap, CPU verification, and per-row EOS/cap validation. It reuses
the worker's normalization, repair, review, and checkpoint paths. The separate
runtime is D:/ml_repos/vibevoice-compiled-20261012; legacy and other environments
were not upgraded. New runtime/model paths are registered in ignored config.json.

Setup supports `install/bootstrap_vibevoice.py --backend compiled` with the
existing install/configure/check modes and separate requirements. To select it
for NEW jobs, set `vibevoice_inference_backend` to `compiled` in app/config.json;
`vibevoice_compiled_python` and `vibevoice_compiled_model_dir` select its assets.
Existing job sidecars pin their original backend. Legacy identities are unchanged;
compiled identities bind the model, Transformers version, and compile profile.
Registering compiled paths preserves the legacy tokenizer cache. Default stays
legacy because the short benchmark did not demonstrate a legacy-to-compiled gain.

Measured on RTX 4090, two unequal synthetic passages: HF eager 17.30 seconds,
compiled first call 70.24 seconds, warm 13.40 seconds (about 1.29x versus HF eager).
Through the actual worker: compiled 72.32 / 13.64 seconds, legacy 14.87 / 13.15.
Do not describe this as a 1.5x production improvement. Initial compilation and new
batch/cache shapes can cost time; this is an optional validated implementation,
not a reason to restart a partly narrated book. Synthetic evidence is under ignored
Output/Inference_2026_10_12. All 14 probe and worker clips passed the CPU speech checker,
including unequal-duration batches with the short row finishing first. Full suite: 335 tests passed with one skip; final focused checks after
setup-preservation regression: 21 passed. Browser fixture confirmed generated vs
verified wording. No installer, release, commit, or upload was performed.

Storybird's desktop shortcut was verified and the idle app restarted. The Voice
resumed on its pinned legacy runtime: live UI showed 69% generated, 65/113
passages verified, generating passage 77/113, and 11 deferred review passages.

## Checker language and priority experiments, 2026-10-12

The owner authorized pausing The Voice, testing explicit English selection first,
then lower CPU-checker priority, keeping only quality-preserving improvements,
and resuming the book. Neither candidate was retained; production checker and
worker source hashes remained unchanged throughout these experiments.

Explicit `language="en"` was compared with unchanged automatic detection using
saved audio, the same CPU/int8 model, beam five, and VAD. Five serial paired
checks matched exactly and took 137.3 seconds with detection versus 113.8 with
English selected. The remaining replay used two isolated CPU helpers. Testing
stopped after the strict equivalence gate failed: of 17 completed pairs, 16 had
identical transcripts and assessments; a 0.8-second clip was detected as Portuguese
and produced a different word when English was forced. Both versions passed,
and English had fewer differences from the source. This is not evidence of a
quality regression, but it does not satisfy the agreed unchanged-results gate.
Automatic language detection remains enabled. The planned 60-clip replay was
stopped early rather than continuing a candidate that had failed its gate.

The priority experiment used the current six-parent/820-word production-planned
synthetic workload, two four-thread checkers, native batches up to four, fixed
seeds, and normal/below-normal/below-normal/normal order. Elapsed times were
235.16/210.29/207.07/203.48 seconds. Windows process priority was verified directly.
All four runs completed every parent, produced identical WAV hashes, substantive
receipts and all ten quality reports, and passed cache-only replay. The mean
appeared 4.85% faster at lower priority, but the final normal-priority run beat
both lower-priority runs; warmup or timing drift makes the early gain unreliable.
Keep normal priority. Do not claim that checker contention was proved or fixed.

Private scripts and evidence are under ignored `Output/Checker_2026_10_12`.
All 258 saved book checkpoint files and its seven pending review passages were
unchanged before and after resume. Storybird had been closed during testing;
it was reopened through the existing desktop shortcut and The Voice resumed.
Live verification showed passage 39 of 113 being checked, GPU generation active,
31 accepted parents, seven passages retained for review, and both CPU helpers
at normal priority. OCR was unloaded. No runtime settings, environments, or
quality gates were changed, and no installer, release, or commit was made.

## Measured narration throughput, 2026-10-12

The owner authorized pausing The Voice, benchmarking four improvements in order,
and resuming it afterward. GPU rendering now has one executor owner and continues
while CPU speech checks run. Prefetch stays bounded to two native batches and
retains the existing duration/byte limits. Cancellation waits for active writers
before temporary-file cleanup. The optional second CPU checker keeps one request
per helper, with bounded reuse and cleanup on startup/check failures.

Portable defaults remain one four-thread checker and native batch size two.
This owner's measured profile in ignored `app/config.json` uses two four-thread
checkers and batch size four. Larger batches apply only on GPUs with at least
23 GiB; smaller/unknown GPUs and conservative mode use one. The existing 85%
allocator cap, CPU-only ASR, parent boundaries, retry limits, and quality gates
remain in place. OCR and TTS still never overlap on the GPU.

Evidence in ignored `Output/Performance_2026_10_12`:
- The initial pipeline-only comparison averaged 238.5 versus 234.4 seconds
  (1.7% less time); all WAV hashes and substantive receipt fields matched.
- A 12-clip CPU benchmark in 1/2/2/1 order averaged 278.9 seconds with one
  checker and 183.1 with two (34.3% less checking time). All transcripts and
  verdicts matched; helper startup was excluded (about 16 versus 32 seconds).
- Two synthetic parents/eight clips took 127.9/85.4/63.5 seconds of GPU
  generation at native batch sizes 2/3/4. Peak reserved memory was
  6.10/6.55/7.07 GiB. Every clip and cumulative parent quality gate passed.
- The final combined six-parent/820-word comparison took 238.9 versus 203.9
  seconds (14.7% less elapsed time). Both arms passed all parent gates and
  cache-only replay. About 6.66 GiB system RAM remained with both checkers and
  the narrator loaded. This is sample evidence, not a whole-book speed promise.

Formatting equivalence now narrowly handles MA/M.A. and PhD/Ph.D. (with case
and dotted-form guards), plus matching p/pp numbered citations such as p84/p.84.
Wrong names, missing text, wrong numbers, signed/decimal/range/identifier forms,
and ordinary lowercase "ma" remain strict. The threshold of five differences,
Whisper model/beam settings, and two automatic retries are unchanged.
Historical replay covered 607 mapped reports: six comparisons changed and three
attempts of one clip changed verdict; 601 reports were unchanged. All 16 older
unmapped reports lacked eligible transcript forms and therefore could not change.
Existing receipts and listening approvals were not rewritten.

The final source suite ran 328 tests successfully (64 runtime-dependent skips);
all 114 VibeVoice runtime checks and seven listening-review checks passed.
The full 83-file Graft reparse/check and Git whitespace check passed.
Before restarting, all 158 saved checkpoint hashes and the complete pending
review file were unchanged. The desktop shortcut was refreshed, Storybird reopened,
and The Voice resumed with two live CPU helpers and configured batch size four.
Live generation reached passage 27 of 113, with 21 accepted parents and five
passages retained for end review. All 158 baseline checkpoint hashes and the
review file were still unchanged after resume; OCR was unloaded. Evidence is in
`Output/Performance_2026_10_12/live_checkpoint_validation.json`. Full-book completion
remains pending. No installer, release, or commit was made.

## Listening review recovery, 2026-10-11

Follow-up: listening review now waits until all available narration is generated.
The worker persists multiple flagged passages, continues remaining clips within
each passage and later passages, and skips already-flagged clips on resume.
Only final audiobook assembly waits for all listening decisions. Accept/retry
decisions remain bound to exact clips. Existing single-passage review files migrate
without changing their decisions. Progress reports the count saved for later review.
Synthetic runtime regressions prove multi-passage continuation, interrupted recovery,
cache-only replay, selective retry and assembly blocking. The source suite passed
314 tests (53 runtime-dependent skips); all 53 focused runtime checks passed.
Browser fixtures verified the combined review list and decision controls.
The desktop shortcut was updated and The Voice resumed: passage 11 was generating
with passage 10 retained for end review. All 20 pre-existing WAV hashes were
unchanged; earlier listening approvals were preserved. Live evidence is in
`Output/OCR_2026_10_11/listening_recovery/deferred_live_validation.json`.
Full-book completion remains pending. No installer or release was built.

The Voice stopped at parent passage 9 after cumulative ASR differences exhausted
its retries. The checker now treats standalone favourite/favorite variants and
valid unsigned ordinal notation (including mid-20th/mid-twentieth) as equivalent.
Names and real omissions remain subject to the existing threshold. Replaying the
saved reports reduced nine counted substitutions to seven across two clips.

Exhausted speech checks now hold the job as `audio_review_required`. Review audio
shows source text, ASR differences and playable clips, with explicit accept or
selective-regenerate decisions. Approvals bind source identity, audio and report
hashes. Rejected replacement clips stay separate until approved; regeneration
archives the prior clip and preserves peers. Raw ASR evidence is retained in
assembled receipts alongside the listening decision. The patch manifest includes
the new dependency; no installer or release was built.

The source suite passed 313 tests with 52 runtime-dependent skips. All 60 focused
quality/recovery tests passed in the isolated narration runtime. Browser checks
verified playback metadata, escaping, acceptance controls and resume dispatch.
The real job is awaiting the owner's listening decisions; no subjective audio
verdict or complete-book success is claimed. Eight accepted passages validate and
all 40 existing checkpoint files retain their hashes. Evidence is in ignored
`Output/OCR_2026_10_11/listening_recovery`. The desktop shortcut launches the
updated main checkout. Do not automatically accept its remaining name differences.

## Local OCR recovery, 2026-10-11

Progress/queue follow-up: VibeVoice now reports verified source-word progress and
a rough ETA calibrated from this run's missing-unit work. Calibration waits for
three prose passages and 600 verified new words; cached units do not inflate
the measured rate. Timing includes GPU generation, CPU checking, and retries,
but excludes startup and final export. The UI displays a heuristic 0.75x to 1.5x
range, not a statistical confidence interval. Stale updates suppress the ETA.
Full-book estimate accuracy is not yet validated. Phase text distinguishes GPU
generation from CPU word checking. Persistent FIFO queue positions and automatic
start behavior are visible; books needing text/visual review still wait for it.
The source suite ran 305 tests successfully (49 runtime-dependent skips), and all
38 repair integration checks passed in the existing VibeVoice environment.
Browser fixtures verified progress, warmup, ETA, and queue labels; the real book
remains paused and the desktop shortcut opens the updated app. Graft's 81-file
reparse and wiring check passed. No installer or release was built.

The owner subsequently requested pausing The Voice and testing 16 CPU checker
threads. The job was stopped through its resumable cancel endpoint with eight
accepted parent passages preserved. Running jobs now show a Pause button and
the existing canceled state is displayed as Paused, with an explanation that
completed work is saved. The underlying queue/checkpoint contract is unchanged.
Browser checks verified both labels and Pause/Resume action dispatch. The
desktop shortcut was refreshed and the app reopened with the book still paused.

The saved-passage CPU check ran in 4/16/16/4 thread order: 165.91/178.65/
205.14/160.19 seconds, excluding model load. Four threads averaged 163.05
seconds versus 191.90 for sixteen (17.7% slower). All four transcript hashes
matched and all 42 existing segment/checkpoint file hashes remained unchanged.
Keep the current four-thread default; the book remains paused. Private evidence:
`Output/OCR_2026_10_11/thread_results.json`. This is a single-passage comparison,
not a whole-book throughput prediction.

Follow-up: the completed extraction then hit VibeVoice's exclusive-GPU guard
because the app had no OCR unload at the narration boundary. Path B narration
now unloads the configured OCR model through Ollama before starting either
narrator, including cached-extraction resumes. An unload failure prevents worker
startup; VibeVoice's independent GPU guard remains intact. A real synthetic OCR
call loaded the model on GPU, and the new release call left `ollama ps` empty.
Seven OCR tests, six desktop/download tests, seven narration-server tests, and
36 review/queue integration tests passed. Full narration was not rerun.

The native window now enables `text_select=True`; job polling preserves cards
with highlighted text. A hidden native EdgeChromium check confirmed selectable
log text with computed user-select `auto`. The desktop shortcut is refreshed to
the main checkout launcher after these changes.

Ollama 0.40.3 returned HTTP 500 with `prediction aborted, token repeat limit reached`
on the owner's new Path B job, reproducible on PDF page 4. Its original GLM-OCR
GGUF lacked `tokenizer.ggml.eot_token_id`; see upstream issue 18609 and PR 17195.
Prompt and textual stop-sequence changes did not resolve this local failure.

A separate local model, `storybird-glm-ocr-eot`, adds EOT token 59253 while
preserving all 527 tensor hashes, the GLM renderer/parser, prompt, and sampling
settings. Only the ignored local config selects it; the default model and original
Ollama model remain unchanged. Local tools and recovery evidence are under ignored
`Output/OCR_2026_10_11`; no narration environment was modified.

The failed page and adjacent pages 3 and 5 now extract successfully. The original
page 3 cache contained 7,856 characters of runaway output; it was backed up and
replaced with the verified 109-character result. The job remains resumable; no
narration or full-book validation was performed. Synthetic body text was accurate,
but its heading and the real Introduction heading were omitted by OCR. This is
not a claim of complete heading fidelity. Local configuration takes effect on
the next app launch. No installer or release was built.

Source error handling now includes bounded Ollama JSON error details and the
failed PDF page, without caching failed output. Five new OCR regressions and all
36 existing extraction/review integration tests passed outside the Windows sandbox.

## 1.0.7 beta candidate, 2026-09-15

The 1.0.7 full installer and patch were built from
`21f4b3bf1f00a3496f4ad46447820bcd4b6f9e4c`. Source verification passed 291
tests with 47 runtime-dependent skips, and the isolated runtime plus assembly
checks passed 100 tests. The source remains public; no public GitHub release,
tag, or asset has been published. Preserve the historical records below.

The source now auto-imports selected voice files, shows each new job at the top, and persists a
durable FIFO queue. Finished-book actions use a context menu. Artwork changes update
local-library artwork and embedded artwork in owned finished audio where the format
supports embedding. Completed-book deletion presents explicit choices. Regeneration
creates a new job with the selected model, leaving the completed source job intact.
Advanced settings can be reset to their defaults.

The recovered Annihilation run completed story-PDF pages 6 through 98. It was not an
uninterrupted run: 5:32:09 active time and 14:38:45 wall time produced 4:26:56.75 of
finished audio. This records a recovered completion, not a clean-run prediction.

Automatic performance enables bounded next-parent render-ahead while the persistent
CPU checker verifies the current passage. Conservative mode disables it. A fixed-seed
four-passage RTX 4090 comparison (off/on/on/off) took 92.48/73.13/71.67/92.89 seconds:
21.9% less elapsed time on that sample, identical WAV hashes in all four runs, and
unchanged 5.56 GiB peak Torch reservation. This is not a whole-book speed guarantee.
Quality gates, finite retries, and checkpoint identities remain enforced. Physical
12/16 GB cards are still untested; native batches remain two on the tested 24 GB
class and one on smaller/unknown devices. Private timing telemetry is opt-in.

The CPU-thread check retained four threads: four threads took 148.93 seconds, eight
took 171.36 seconds, and twelve took 149.83 seconds. Each setting performed six
checks and all 18 transcript hashes matched by input clip.

Final source verification: 291 tests passed with 47 runtime-dependent skips; all
100 focused VibeVoice/assembly tests passed in the isolated runtime with no skips.
Two fresh synthetic PDF jobs completed through the app with automatic queue handoff,
full audio decoding, library ownership checks, and cache-only reuse. Regeneration
with another model stopped for its required preview. UI voice import, placement,
context actions, artwork, export, and advanced reset were exercised. Sol's source
and privacy audits passed; Graft reparsed 80 Python files and its wiring check passed.
See RELEASE_1_0_7.md for the scope and remaining hardware/installer limits.

A fresh 16 GiB Windows Sandbox installation passed the direct installed-worker
smoke for the standard `CHAPTER ONE` fixture: GPU narration, CPU quality checks,
parent and unit receipts, native batches of two, cache-only reuse, M4B/MP3/WAV
decodes, and M4B chapter and cover metadata. The patch upgrade's dependency
failure, recovery, and repeat run passed; uninstall retained 76 user files.
The Sandbox lacked `nvidia-smi`, so this is direct worker evidence rather than
physical GPU telemetry. Legacy Chatterbox files were preserved, but Chatterbox
inference was not tested. An earlier 4 GiB Torch native load failure and two
rejected numbered-heading fixtures remain limitations. Do not claim
numbered-colon heading audio passed.

The authorized beta handoff is complete: the current full installer and patch
were verified in the existing authorized folder, the prior 1.0.6 pair was
archived, and both beta guides were read back. Sharing remains unchanged. Do
not create a monitor. No public GitHub release has been published.

The prior source handoff at `ebc7862` was reconciled before this beta work. The
current local installer-message and documentation commits have not been pushed:
the requested work was the installer handoff, not GitHub publication. Every
prior dirty source/doc file was preserved with hash verification in an ignored
local backup; unrelated branding and handoff files remain untracked and
unchanged. The desktop shortcut now launches the main checkout's launcher, and
the running app reports 1.0.7. Existing runtime paths and job data are retained.
The requested personal iCloud upload remains pending sign-in and destination-access
verification; the finished audiobook has not been uploaded there.
# Local PDF to Audiobook Pipeline — Standing Rules

Personal project. Local build on my own hardware, for legally purchased books, personal use only.

## 1.0.6 installer retest authorized, 2026-09-14

The owner requested updated patch and full installer builds after the batched repair
fixes. This authorizes packaging and exact-artifact beta testing now, while the
private audiobook continues separately; it supersedes the earlier book-first build
sequence. Main checkout/GitHub reconciliation still waits for the completed,
verified audiobook and 1.0.6 beta handoff. Preserve all main checkout changes.

The release candidate includes the post-beta extraction, heading, process cleanup,
progress, persistent CPU verification, native batching, selective repair and numeric
equivalence fixes described below. Source verification passed 203 tests with 15
runtime-dependent skips; all 31 focused tests passed in the isolated VibeVoice
runtime. Both installer version markers and the app version are 1.0.6. See
RELEASE_1_0_6.md. Artifact tests and hashes are recorded separately under ignored
Output/Release_1_0_6; source checks do not certify an installer or a public release.
The first installed 1.0.6 candidate exposed missing M4B chapter marks for numbered
colon headings. Both narration assemblers now reuse the shared chapter classifier;
this changes assembly metadata only and preserves all narration checkpoints. The
corrected source passed 204 tests (16 runtime-dependent skips) and all 35 focused
runtime/assembly tests. Final candidate artifacts require new installed checks.
The owner explicitly requested leaving Annihilation paused after installer testing
and upload, to keep the PC available; do not automatically resume that book.
## Current 1.0.5 integration state — 2026-09-14

The owner approved VibeVoice 1.5B as the preferred narrator after listening to the
full chapter. New Storybird jobs now default to this isolated backend. Existing
jobs without a backend remain Chatterbox; Chatterbox is also selectable for new jobs.
This supersedes historical statements below that Chatterbox is the app-wide default.

Terra implementation, independent Sol verification and orchestrator app-level
verification are recorded in [VIBEVOICE_1_0_5.md](VIBEVOICE_1_0_5.md). Two real
synthetic PDF-to-M4B jobs passed, including visual decisions, final-preview approval,
GPU narration and CPU quality checks. GPU-disabled checkpoint reuse and all three
export formats were verified separately. Original extraction remains separate from
spoken visual adaptations. OCR and TTS never overlap on the GPU.

Runtime settings are pinned to 1.5B BF16, CFG 2, 20 steps, SDPA and gain-only
-21 LUFS normalization. No environment was upgraded for this integration: local
configuration registers verified existing runtimes. The new provisioning helper
creates only ownership-marked isolated environments when explicitly invoked.

The owner explicitly authorized the 1.0.5 full installer and patch on 2026-09-14,
with extensive Astra final audit and testing before the established Google Drive
beta handoff. This supersedes the earlier build hold. Fresh-machine setup and
exact-artifact verification remain distinct from the completed local app checks;
do not upload until those checks have finished. Public release gates still apply.

## Post-beta Annihilation validation, 2026-09-14

The real-book run exposed source defects after the 1.0.5 beta handoff: ordinary
prose beginning with a visual-label word and a period could trigger review;
numbered uppercase colon chapter titles could merge into body text; healthy
VibeVoice generation/CPU-quality retries could exceed the watchdog interval
between accepted passages; terminating a worker left its CPU verifier running.
These are corrected in the source worktree with synthetic regressions. Worker
progress now identifies actual generation and quality-check phase transitions,
and each worker has its own lock-protected, handle-scoped Windows Job Object.
Canceling a queued job or cleaning up an older worker cannot close another job.
Quality thresholds and finite phase timeouts remain enforced.

Astra ran the 178-test full suite (three runtime-dependent skips), then all three
runtime tests in the existing VibeVoice interpreter. The final phase-display
change passed the seven-test server suite. Sol independently reviewed the fixes.
Real extraction preserves five chapter headings and all prose without false
visuals. The full audiobook has resumed using its unchanged accepted checkpoint;
completion and final audio verification are still pending. Scene-separator pause
handling remains the previously documented limitation. Private evidence is under
ignored Output/Annihilation_1_0_5. No new installer, patch, or release was built.
## VibeVoice efficiency investigation, 2026-09-14

The owner made total processing time a product priority: the previous Chatterbox
Annihilation job finished in 36.4 minutes, while the new VibeVoice pipeline spends
roughly as long on CPU speech checking as GPU generation and can repeat both for
rejected passages. The older job used a different voice, all 102 PDF pages, and no
new per-attempt CPU coverage gate; it is a product baseline, not an isolated model
benchmark. Do not describe performance as solved.

The source worker now retains one isolated CPU Whisper large-v3 helper per job and
generates at most one provisional next passage while checking the current one.
Int8 CPU inference, beam size five, VAD, quality thresholds, retry counts and receipt
identities are unchanged. Only verified audio becomes a checkpoint. Real phase
transitions, per-request timeouts, bounded diagnostics and exact-process cleanup
remain enforced; OCR never overlaps narration on the GPU.

Astra ran the final 189-test suite (12 runtime-dependent skips) and all 17 focused
runtime/quality tests in the existing isolated runtime. Sol independently audited
the lifecycle, speculative retries, checkpoint order and cancellation. A real
two-passage run completed with both receipts validated in 549.0 seconds, including
two retries of the first passage. It overlapped 78.8 seconds of work and preserved
the already-generated second passage. This is useful evidence, not a claim that
whole-book speed is competitive. Annihilation's seven accepted checkpoints were
preserved for resume.

A separate synthetic native batch-of-two pilot took 84.0 seconds of generation
versus 153.2 seconds serial, with both batched outputs passing the unchanged CPU
gate. It is not integrated into production and does not certify smaller GPUs.
A GPU Whisper experiment was much faster but disagreed with CPU verification on
a previously rejected passage; neither transcript is audio ground truth. GPU
checking is not enabled. Investigate that disagreement before changing the gate.
The short-heading absolute-threshold limitation also remains a final-audio review
item. Private evidence lives under ignored Output/Annihilation_1_0_5.
## Batched repair sections, 2026-09-14

The owner authorized implementing native VibeVoice batching and small independent
repair sections after the original run exhausted its third retry on parent passage
11. The existing parent plan remains unchanged. Missing parents now use deterministic
120-word target, 180-word maximum sections, with sentence boundaries where possible.
Headings remain whole. All 55,513 source words and five headings are preserved in
485 sections beneath the existing 154-parent plan. Eleven accepted parent WAVs and
receipts were verified unchanged before resume.

One model process uses native batches of two only on the measured 24 GB class
(at least 23 GiB physical VRAM); smaller or unknown devices stay at one. CUDA OOM
uses the existing ordered bisection helper. One persistent CPU verifier can overlap
one following batch within a parent. Unit receipts bind source/runtime identity,
WAV, and report hashes; resume recomputes coverage. Good peer units survive failures.
Only a failed unit retries, with bounded attempts. The concatenated transcripts must
also pass the unchanged parent coverage gate before parent audio is published.
Internal joins use 5 ms edge fades, retaining every frame and all interior speech;
accepted unit files remain unchanged. GPU ASR remains disabled.

Astra's real 693-word, two-parent benchmark completed generation and all six CPU
checks in 219.46 seconds, versus 549.04 seconds for the prior overlap trial. The
prior trial needed two retries and this trial needed none, so this is not a controlled
whole-book speed estimate. Measured overlap was 54.62 seconds; peak Torch allocation
was 6,038,912,000 bytes and reservation 6,543,114,240 bytes. Both parent gates passed.
Cache-only replay loaded neither model nor ASR and preserved all cache hashes. The
first raw concatenation showed one 0.067-full-scale boundary step; Astra corrected
it with the internal fades and verified every new join reaches zero, with exact
interior PCM and timing preservation. The corrected 200.417-second mono 24 kHz AAC
M4B export decoded completely without errors. This is objective audio validation,
not a subjective listening verdict.

Final verification: Astra full suite 200 tests OK (15 runtime-dependent skips),
all 28 focused tests passed in the existing VibeVoice runtime, and Sol independently
reviewed retry, cumulative quality, cancellation, cache and join behavior. The
installer process-check fixture now uses a unique temporary app root so it can run
while Storybird is open. Graft reparsed 71 Python files and its wiring check passed.
The future patch source manifest includes the new module; no installer was built.
Private measurements and resume evidence are in Output/Annihilation_1_0_5. Annihilation
resumed through Storybird on the updated worker; full completion, final audiobook
verification/upload, 1.0.6 packaging/handoff, and then main/GitHub reconciliation
remain pending in that order. Performance is improved, not established as competitive
with the historical 36.4-minute Chatterbox book run.

The subsequent live run proved section repair preserved its three good peers, but
its remaining section was rejected three times for a comparison bug: Whisper's
"100" and "700" were counted as missing "one hundred" and "seven hundred". Those
four formatting-only token differences plus one possessive difference crossed the
five-word threshold. The quality tokenizer now expands valid unsigned whole
integers (including grouped thousands, through one trillion) into canonical English
words. Signed, fractional, decimal, leading-zero and identifier forms stay distinct;
the threshold and runtime identity are unchanged. Astra replayed all three real
reports: each now has only one missing/inserted word and passes. Sol independently
reviewed numeric boundaries, including grouped decimals. Final counts after this
correction: full suite 203 tests OK (15 runtime-dependent skips), isolated focused
suite 31/31 passed. The book resumed through the app again with its good sections
preserved. See numeric_equivalence_audit.json and BATCH_REPAIR_AUDIT.json in the
private evidence folder for final source hashes and live progress. The formerly failing parent 11 subsequently passed after only its missing section was regenerated; all three accepted peer WAV hashes remained unchanged (live_repair_recovery.json).

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

Chatterbox is the chosen narrator, using voice cloning from a reference clip. Default reference clip as of 2026-07-21: D:\Audiobook_Pipeline\samples\Voice_Sample\male_ref.wav (converted from Voice Sample Male.mp3, 20s). The older ref_15s.wav was rejected by the user on listening quality; do not switch back to it. Chatterbox scripts must stub the watermarker (resemble-perth 1.0.1 is missing perth_implicit) and read the mp3 reference with soundfile, not torchaudio, on Windows.

## Extraction models (textbook path, Ollama at http://localhost:11434)

GLM-OCR is primary, run via a tuned Modelfile (glm-ocr-doc) on the /api/generate endpoint with a plain Markdown transcription prompt and num_ctx 16384. Do NOT force JSON on GLM-OCR; it collapses and drops the page. qwen2.5vl:7b is a weak fallback (hallucinated on the test page); 32b is reserve for hard pages only, use /api/chat with base64 images, temperature 0, JSON output.

## Extraction rule

Read body text and section headings, retaining iteration headings and quotations. Remove repeating boilerplate (title, author, running headers, footers, page numbers). Visual passages, including tables, data lists, charts, diagrams and computer logs, must retain their extracted source for review before narration. The owner retired blanket omission announcements on 2026-09-12. In Storybird, explicitly keep spoken text, write an editable spoken description, or skip a passage when surrounding author-written prose already conveys its contribution. Preserve important counts, changes, warnings and the original sequence of discovery. Never infer missing graphics or add unsupported conclusions. Uncertain passages require manual review; adaptations stay separate from original extraction. Section headings keep their audible pause/cue before the body.

## Working style

- Candid tone. Tell me directly when something is a bad idea or won't work. Don't just agree.
- No dashes in any output meant for me to copy and paste.
- Give exact commands. Flag torch/CUDA version pitfalls before they happen.
- Don't debug extraction and narration at the same time; isolate which stage failed.
- Verify claims against real output before asserting they're fixed. Don't assume a fix works from pattern matching alone if a quick test can confirm it.

## Current validated state

2026-09-12 installer handoff policy: `Output` contains only the two current installer
executables, `Setup_AudiobookStudio.exe` and `Setup_AudiobookStudio_Patch.exe`.
Never retain version-suffixed executable copies beside them; historical copies belong
under `Output/Old, do not use/`. `00_CURRENT_INSTALLERS.txt` identifies both builds
with version, source commit, byte size and SHA-256; per-artifact `-build.json` receipts
are generated by the canonical build script after its manifest check. These records
identify beta candidates and do not replace the exact-build release checklist.
The retained 1.0.3 pair was built from `19e8e30`; the subsequent Graft repair changed
only exclusions and documentation, with no application or installer logic changes.
The owner authorized automatic beta uploads to the Audiobook_App Google Drive folder
on 2026-09-12. Follow `install/BETA_HANDOFF.md`: upload a verified versioned replacement
before moving only superseded Audiobook Studio installers to `Old, do not use`.
This is beta distribution authorization, not permission to publish a GitHub release.
For the next version onward, the owner confirmed simple Drive filenames:
`Patch_AudiobookStudio_1.0.4.exe` and `Installer_AudiobookStudio_1.0.4.exe`
(substitute the actual version). No build timestamps or hash suffixes. Leave the
current 1.0.3 uploads unchanged. Update the receipt generator and naming test when
preparing the next version, as specified in `install/BETA_HANDOFF.md`.

2026-09-12 Graft indexing repair: native Windows process access is required when
the Codex sandbox blocks Node's Git subprocess. That failure made Graft ignore
Git exclusions during its filesystem fallback and serve a stale 41-file graph.
The exclusion policy now covers generated output, runtime environments, books,
and audio. A full reparse indexed all 47 current Python files; source addition,
edit, and removal each triggered automatic refresh. Files and permissions in
the protected output tree were preserved. See GRAFT_INDEX.md for evidence,
unsupported file types, and the remaining upstream sandbox/fallback limitation.

2026-09-12 narration safety update, candidate 1.0.3: a Jurassic Park run stalled after 336
segments with about 22.36 GiB dedicated and 3.86 GiB shared GPU memory in use. Canceled at the
user's request; all 336 completed segments remain resumable. The original stochastic trigger
was not reproduced. The input-token budget alone does not bound generated-token memory.
Workers now set a CUDA allocator ceiling before model loading, retaining physical VRAM
headroom. Existing ordered OOM bisection handles batches that exceed it. Batched progress hides
an ETA after two minutes without an update and stops the owned worker resumably after five;
model loading before the first progress record is not covered by that timeout. Early heading
samples no longer extrapolate an ETA far beyond observed text lengths. The patch now includes
all local Python import dependencies and the voice-conversion helper (15 files total).
All 66 unit tests pass. Real T3/S3Gen probes across five production-plan buckets recovered under
a 6 GiB allocator cap; a synthetic forced-1000-token test split 12 rows into groups of 3, peaked
at 6 GiB reserved, then generated 12 finite, non-silent audio segments in the same CUDA context.
These are developer-machine checks, not physical small-card or installed-build certification.
See NARRATION_AUDIT.md for evidence and remaining release gates. Restart the app to load new
server-side safeguards before resuming. Prior 1.0.2 patch assurances are superseded by this audit.

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
- GLM-OCR can degenerate on artwork pages (endless code fences, empty HTML tables, or looped short tokens). Visual review preserves detected empty tables and uncertain repeated OCR as raw review evidence instead of announcing an omission. A blank OCR result is an unresolved unreadable-page visual, including when recovered from cached pages. Nonempty copyright-filtered pages still follow the copyright rule. ocr_page caps num_predict at 4096. Narration fingerprints the spoken chunk plan and invalidates stale segments if that plan changes.
- Voice cloning: users can upload a voice sample in the UI (wav/mp3/flac/ogg, converted via convert_voice.py in the chatterbox env, soundfile only, trimmed to 20s) and pick a voice per job. Default voice is samples\Voice_Sample\male_ref.wav ("Default narrator (male sample)").
- Design decisions applied (were open threads 3/4): CHECKLIST FOR X sections get normal heading treatment; epigraphs stay plain body.
- Verified end to end 2026-07-21: 1-page Path B job produced 53.7s of real narrated audio through the UI. Full Odyssey extraction dry-run: verse mode, 4465 blocks, all 24 Book headings detected.

## Batched narration engine (default since 2026-07-24)

app/batched_narrate.py puts N text chunks that share one voice through a SINGLE T3 forward pass. It reproduces v1's per-sequence math (right-padded text so real tokens keep learned positions 0..T_j-1, CFG as a 2N-row block-ordered batch, explicit position_ids from cumsum(mask)-1, per-row EOS with finished rows frozen to a safe one-hot). Quality is verified: byte-identical tokens to the old parallel engine. S3Gen batches a bucket when there is more than one valid row and trims every result to its real token length; one-row buckets use v1's exact path.

- Selected by config["engine"] ("batched" default, "parallel" fallback). server.py DEFAULT_ENGINE reads env AUDIOBOOK_ENGINE. The batched engine runs ONE process on purpose.
- Buckets cap rows*Tmax at BATCH_TOKEN_BUDGET (default 1300, cap BATCH_SIZE 12). This controls input work, not worst-case generated-token memory; the 1.0.3 allocator ceiling and OOM bisection supply an additional memory safeguard. A fixed count OOM-thrashed and looked like a hang ~62% into a book once chunks got long. On the 4090 the longest chunks land at N=4, medium ~N=8, short at the 12 cap.
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
  spot in those measured runs: peaks were ~8 GB of 24 and per-row compute was the constraint.
  This is not a universal memory-safety claim; the 2026-09-12 run exhausted dedicated VRAM.

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

BATCHED ETA is based on bucket workload, not chunk count. Chunks run shortest-to-longest and later
buckets also hold fewer rows, so a whole-run chunks/second average becomes increasingly optimistic.
The worker fits elapsed bucket time against each bucket's input-token maximum after 20 samples and
forecasts the known remaining bucket plan through `narration_progress.json`. The server uses the old
chunk-rate estimate only for the unsorted parallel engine. Replayed against all 179 buckets of the
2026-09-12 Annihilation run, the new estimate was 4-9% high from bucket 100 onward; the old estimate
was 52-65% low at the same checkpoints and displayed "under a minute" with five buckets still left.

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

Cached extraction needs deliberate migration. Do not delete an existing job's blocks to apply the
visual-review policy. The review flow preserves original extraction separately and checks cached
jobs before narration. Spoken text/type changes invalidate segments through the existing plan hash;
source-page, chapter, and assembly-only metadata do not. Always audit the saved narration projection
after a resume. Unrelated extraction changes still require an explicitly prepared fresh extraction.

## Portable configuration

Two things about app/config.py that are easy to get wrong:
- setup.py WRITES chatterbox_python into app/config.json at the end of a successful install (2026-07-26). Detection is a fallback now, not the primary path, and its last-resort return value is still the original author's hardcoded path, which is wrong on every other machine. If someone reports the app cannot find the chatterbox env, check whether config.json got written before debugging the detection order.
- CFG.ffmpeg_path() RUNS ffmpeg rather than testing that the file exists, and caches the result. Pass refresh=True after installing one. Existence checks are what let a broken ffmpeg look healthy.

## Rulebooks and other designed layouts (learned on the 2024 DMG)

Two-column reference books are a different document class from novels and verse, and they broke four things. All four fixes are in; this section exists so the same ground is not re-explored.

- USE PATH B, even when the PDF has a perfect text layer. Path A's paragraphing relies on the x-indent rule, and a two-column rulebook has no first-line indents, so every LINE becomes its own block, drop caps orphan ("UNGEONS & DRAGONS"), and columns interleave out of order. suggest_path already routes multi-column pages to B on its own; trust it. GLM-OCR is faithful here, measured at 0.95-0.98x of the text layer's character count.
- Existing jobs preserve their cached extraction and prior audio. Use visual review to adapt cached visual passages; do not delete blocks.json as a migration shortcut. The historical extraction-skip trap remains relevant for unrelated extraction changes, which need a deliberately prepared fresh extraction.
- Path B filters pipe-form running headers while preserving real chapter openers. Dice tables, including long prose-like rows, now remain raw visual passages for review rather than losing roll numbers or receiving omission markers. Diagram-label detection is bounded to contiguous short labels and preserves surrounding headings, quotations and prose. Raw HTML tables, malformed pipe tables and structured log fragments also retain their source for an explicit treatment.
- rasterize_page has a 12 megapixel budget. Fold-out pages exist: DMG page 154 is a 4934x7000pt map that rendered a 107 MB JPEG at 200 dpi and made Ollama return 413, killing extraction 148 pages in.
- CHAPTER MARKS CAN GO MISSING from detected headings when OCR does not transcribe decorative chapter numbers. New extractions now retain 1-based source-page provenance, the server persists the PDF outline, and assembly uses selected outline divisions when they provide more chapter marks than detected headings. Destinations map to the first real narrated chunk on or after the outline page. This is regression-tested on synthetic mappings but still needs an installed-build M4B navigation check on a real book before release.
- Table-dense chapters require editorial review. Prior omission markers are historical behavior, superseded by the owner-authorized visual review policy. Narrate a visual only to the extent its source supports and its contribution warrants.

## Repo hygiene (history scrub completed 2026-08-04)

ab_samples/ was tracked in the PUBLIC repo and contained real book prose, including an explicit
excerpt. `git rm --cached` on 2026-08-03 removed both files from HEAD. On 2026-08-04 all local refs
were rewritten to remove `ab_samples/ab_chunks.json` and `ab_samples/README.txt`, rewrite backup
and Codex checkpoint refs were removed, reflogs expired, and unreachable objects pruned. Verification
found zero path hits across all remaining refs and both former blob IDs absent from the object
database. A full pre-scrub bundle is preserved under ignored `Output/` and was verified before the
rewrite. The force-push used an explicit lease against the inspected pre-rewrite remote SHA and
updated public `master` successfully. PURGE COMPLETE 2026-08-06: GitHub Support removed the internal
references from PRs 1 through 4, ran its purge, and confirmed completion. Independent verification
found zero `refs/pull/*` entries and the former commit API lookup now returns HTTP 422 rather than
commit data. Local and remote `master` both remained at `0e8e3d789630b4a97de57b4dedf8da6339a283bc`.
The repository reports zero forks. A sweep of all tracked files found no other book prose.

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

## GPU capability handling (added 2026-08-23, first friend-machine crash)

Brandon (first outside tester) hit `torch.cuda.OutOfMemoryError` inside T3's batched forward pass
on his own card; BATCH_TOKEN_BUDGET=1300 was only ever calibrated on the author's 4090. This closed
the asymmetry the project used to have (voice and ffmpeg were preflighted with a clean 400 at job
creation; a GPU problem was not, and surfaced as a raw torch traceback). Three layers, in server.py
and narrate_worker.py:

- `missing_gpu_error()` preflights job creation (alongside the existing voice/ffmpeg checks): no
  NVIDIA GPU at all (nvidia-smi absent or failing) refuses the job with a clean message. It cannot
  and does not try to predict OOM from a positive-but-small VRAM number; that is the next layer's job.
- `scaled_batch_token_budget()` scales the batched engine's per-job token budget down linearly by
  detected VRAM (ceiling stays 1300, never scaled up) unless AUDIOBOOK_BATCH_TOKEN_BUDGET is set.
  This is a straight-line ESTIMATE off the single 4090 calibration point, not a measurement on any
  other card, and ignores the model's own fixed load footprint, so treat it as lowering the odds of
  a first-try OOM, not a guarantee.
- narrate_worker's T3-generate and S3Gen-vocode calls now catch `torch.cuda.OutOfMemoryError`,
  empty the cache, and retry the bucket as two halves, recursively down to one chunk. A single chunk
  that still OOMs is a hard VRAM limit, not something a smaller batch fixes, so it propagates and
  `main()` writes `job_dir/error.json` with a clean cause; `server.py` reads that back so the UI
  shows the real reason instead of "a narration worker failed (exit codes [1]), see log".

PROVEN, not just code-reviewed: a real CUDA OOM forced via `torch.cuda.set_per_process_memory_fraction`
on the dev 4090 was actually caught by `main()` and wrote the exact expected error.json (2026-08-23).
The bisection recursion itself (splits correctly, preserves chunk order, a truly-unrecoverable single
chunk still raises rather than looping) was proven by monkeypatching `batched_narrate.batched_generate`
/ `seqs_to_wavs_batched` to fail above N=1, not by finding a real memory ceiling that reproduces it
exactly. `tests/test_gpu_oom_handling.py` covers the server.py-side pieces (scaling formula, preflight,
error.json readback) since those import cleanly in the base env; the narrate_worker.py pieces cannot
be unit-tested there (it needs torch/chatterbox, base env has neither) and are proven only by the two
live checks above plus a real book completing end to end.
STILL UNVERIFIED: whether the scaling formula actually keeps a real small card (e.g. 6-8 GB) under
budget on the first try for a real book start to finish; only Brandon rerunning (or another sub-4090
card) proves that.

Optional crash reporter: `config.error_webhook_url` (env `AUDIOBOOK_ERROR_WEBHOOK_URL`, config.json
field, gitignored like the rest of config.json) posts one structured Discord embed on any job failure
(extraction or narration) -- error message, stage, engine, job title, GPU name/VRAM, OS -- and nothing
else: no chunk text, no blocks.json, no log tail. Disabled by default on every install; must be opted
into per machine, and the URL must never be committed. `_report_crash` swallows every exception itself
so a Discord outage can never mask the real failure it is reporting on top of.

## Emergency beta stabilization after Brandon's 2026-08-31 failure

Field evidence supersedes the earlier assumption that the August 23 OOM catch covered Brandon's
machine. His patched 1.0.1 install reported a batched narration failure for `Jurassic Park 8-31` on
an RTX 4090 Laptop GPU with 16,376 MiB. Transformers' DynamicCache failed in `torch.cat` with a plain
`RuntimeError("CUDA error: out of memory")`, not `torch.cuda.OutOfMemoryError`. The VRAM formula's
starting budget was about 827 tokens and still OOMed. That budget remains an UNMEASURED ESTIMATE on
his laptop; it was not lowered during this stabilization because runtime recovery is the safety
mechanism. Only a controlled run on that laptop can justify a measured budget change.

Local source fixes and proof, 2026-09-01:

- `app/gpu_oom.py` is the single dependency-light classifier and ordered bisection implementation.
  It accepts PyTorch's CUDA OOM class or a `RuntimeError` whose message contains both the standalone
  word `CUDA` and `out of memory`. CPU OOMs, unqualified OOM strings and unrelated CUDA runtime
  errors are not swallowed. Generation, recursive halves, S3Gen vocoding, capped-row isolated
  retries, serial fallbacks and the top-level clean `error.json` path all use the classifier.
  Recovery clears ended traceback frames, runs GC and calls `cuda.empty_cache()` best-effort; it does
  not synchronize an asynchronously failing device or replace the original exception. A resumed run
  removes stale `error.json` before generation. Tests reproduce Brandon's exact exception string,
  prove left-to-right chunk order and prove a single-item hard OOM is re-raised.
- Raw PID cleanup is retired. Every narration/assembly child is assigned by its live process handle
  to a Windows Job Object configured with `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`. Assignment failure
  stops the new process and refuses narration. Normal cancel still kills the exact live `Popen`
  handles, launcher exit closes the Job Object, and a server crash closes it in the kernel. Legacy
  `worker_pids.txt` files are only deleted and are never authority for `taskkill`. Cleanup runs in
  `finally`, including spawn and cancel races. A real Windows child died when the job handle closed;
  a test file containing the current unrelated test runner's live PID was removed without any kill
  command. This removes the credible PID-reuse hazard but does NOT prove it caused Brandon's touchpad
  failures. His memory of whether the touchpad stopped at job failure, app close or next launch would
  be useful; do not ask him to reproduce it.
- `launcher.py` sets pywebview 5.4's `ALLOW_DOWNLOADS=True` before creating the native window.
  Download links also issue a parallel HEAD availability check and show inline/alert feedback for a
  missing server file. The exact pinned pywebview 5.4 package was installed into an ignored isolated
  test target and run with EdgeChromium against synthetic job data. Both `Download beta report` and
  the WAV link opened native Save dialogs. The saved ZIP contained only the synthetic summary and
  log; the downloaded 48,044-byte WAV was byte-for-byte identical to the synthetic source. This is
  native-window proof of the source path, not proof of a not-yet-built 1.0.2 installer.
- The installer designs no longer inject a crash-report credential and the one-shot merge helper is
  removed. Crash reporting remains local opt-in through gitignored `app/config.json` or
  `AUDIOBOOK_ERROR_WEBHOOK_URL`. A current working-tree scan found zero live Discord webhook URLs.
  The credential introduced at `3351d47` still exists in public history and MUST be revoked. As of
  this record, revocation has not been confirmed. No history rewrite, force-push or Support purge was
  started; those remain a separate destructive decision requiring explicit approval.
- The conclusive base-environment run used `C:\Users\paulm\miniconda3\python.exe` with a writable
  project temp root: all 48 dependency-free tests passed. Changed Python files compiled and the
  embedded JavaScript parsed. The earlier 12 temp-file failures were managed-sandbox errors before
  assertions, not product failures.

Release status remains BLOCKED. The reviewed stabilization source was committed as `19f74df`, and
the 1.0.2 release preparation was committed separately. A local patch candidate has compiled from
clean HEAD through `install\build_installer.bat patch`; its eight-row manifest passed the prohibited-
content check and the artifact contains no detectable Discord webhook endpoint. The exact retained
candidate's commit, byte size and SHA-256 are recorded at handoff rather than in its own source
commit. No installer has been sent and no release has been published. The
next Brandon run must use a short synthetic or properly licensed sample, verify beta ZIP and audio
downloads in the installed window, deliberately exercise recoverable OOM splitting on the 16 GB GPU,
and observe clean shutdown before any complete-book job. The exact-build clean-machine checklist is
still mandatory for a public release.

## Local library follow-up (2026-09-12)

Visual review is implemented in the source app. See `VISUAL_REVIEW.md` for its editorial
workflow, cached-job migration, source/decision files, prior-audio preservation and verification.
`review_required` pauses the worker queue before TTS; saved keep/describe/skip decisions and a
current full-text preview are required before narration of flagged passages. The interface uses
Storybird branding. This source change does not constitute a new installer or release.

- Finished jobs now render as collapsed, cover-led tiles after active work. Their existing playback,
  download, output-folder, delete, beta-report, log, and cache controls remain available after
  expansion. A completed job can store a local PNG/JPEG/WebP cover override in its job folder;
  this never rewrites audio, segments, blocks, config, or job state. Existing extracted covers are
  reused, with the moved processed PDF as a fallback.
- The create-audiobook dialog now renders a selected PDF page in memory for page-range selection.
  It uses an opaque library token, CPU-only PyMuPDF rendering, page bounds, and no job/queue/OCR/TTS
  mutation. Copyright filtering is conservative and applies only to future Path A and Path B
  extraction before stitching. It removes anchored, year-bearing publication notices and adjacent
  rights lines while preserving ordinary discussion, mixed pages, and source-page provenance. It
  does not alter existing blocks, cached segments, or finished audio.

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
