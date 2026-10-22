# Drama 3 Q3 integration — 2026-10-15

## October 19 Annihilation completion and bounded recovery

Fresh job `b79b1fb6-d6ff-4b80-9c3f-2ce7ed3e6f11` uses the owner's saved Ray Porter
PHM reference and pages 6–98. The owner explicitly requested deleting previous
Annihilation generations, which the normal contained deletion API completed.
Source and reference hashes are preserved; the new plan has 733 clips and five
chapter headings. The completed M4B is in
`audiobooks/Annihilation (2)/Annihilation.m4b`; the live app reports `done`, all
55,513 words verified and no remaining review passages.
The 5:24:26 export fully decodes, has all five chapter markers at verified offsets,
and matches its library copy byte for byte: SHA-256
`46e077f804b734da3b0a79420e6b105f63376d0daa5c2f6ef2a23a726a2de17e`.

An early 32-clip audit found a failed numeric chapter heading. Both recognizers
corroborated its wrong content; the 31 prose clips pass the primary checker.
Two next-seed probes with unchanged source text, and two formatting probes,
pass the existing strict heading comparison. Changing formatting is unnecessary.
The production defect was that Drama's unit-builder return skipped the existing
`numbered_heading` marker. A failure therefore reached the generic short-span
listening gate instead of the bounded heading retry path. The marker now applies
before backend dispatch; old pending records inherit only this checker metadata.

The synthetic regression reproduces the early review hold, then verifies bounded
retry, failed-take preservation, correct number/title checking and review after
budget exhaustion. A later regression also covers critical wording flags using
Drama's existing bounded retry budget before the manual-review hold. Uncertain
transcript-review results remain held, and no acceptance threshold changed.
All 26 Drama, 29 phase and 50 repair integration tests pass.
The resumed production scheduler selected attempt two, seed 1730, whose raw WAV
exactly matches the probe verified by both recognizers. All 65 earlier WAVs are
accounted for. No source, renderer policy, narrator or acceptance waiver changed.
See `Output/Annihilation_Drama3_2026_10_19/heading_recovery_verified.json` and the
adjacent probe/check records. The task-scoped monitor is observational and ends
when the job stops; it is not a recurring agent or automatic error-waiver loop.

The final audit validates all 733 original receipts, independently checks 223
original recordings, and installs 37 bounded replacement takes. Thirty-six pass
both recognizer comparisons. One exact primary transcript has a scoped numeric
formatting adjudication because Whisper writes `12 or 50 or 100` for the same
source quantities; the raw result and rationale remain in `repair_assessment.json`.
Tail-only independent checks corroborate five false `Thank you` additions at the
30-second ASR window boundary. A 6.07-second source scene-break pause is retained
after word-timing verification rather than replaced by a truncated candidate.

Native recovery rebuilds 28 parents with zero listening-approval records. Every
selected frame survives 579 internal joins; 696 original clips are unchanged and
37 have exact backups. All 799 backup files verify, and source, plan, configuration
and narrator hashes remain unchanged. See the private `completion_audit` directory
for original reports, candidate history, installation manifest and final checks.
This supervised automated audit does not establish unattended quality for every
future book. No installer, release, Git write or upload was performed.

## October 19 Voice completion

The owner directed autonomous completion of The Voice. The final 3:39:24 M4B
is registered as done in Storybird, with 14 verified navigation markers and a
clean full decode. Its local library path is `audiobooks/The Voice (3)/The Voice.m4b`.
The job export and private audited master match it byte for byte.

All 477 original clip identities and hashes were checked. An independent audit
covered 216 original recordings; 13 replacement clips pass both recognizers.
Scoped punctuation changes restored the missing dialogue labels and stage
directions. One frame-capped take and three content retry events used bounded
new seeds; passing peers were retained. PDF-verified spoken projection edits
remove a blank-page OCR response, library stamps and exterior back-cover material,
and restore one line-broken word. The identical publisher logo is omitted on
both title and back-cover pages. The frozen plan and canonical source are intact.

The exact-fingerprint completion basis is the owner's instruction to finish
autonomously, not a claim of owner listening. Seventeen primary recognition
flags remain in the audit. No broad recognition acceptance policy was changed.
Every selected frame is retained across 365 joins; chapter offsets are bound to
the current audio and verified source openings. Do not reuse those offsets after
changing recordings. Of the original clips, 475 remain unchanged and two have
verified backups. All 553 backup files and all three final copies verify.

The new whole-page OCR-response regression first failed, then passed with a
narrow visual-review guard in `pipeline_text.tag_blocks`; all 77 affected tests
pass. The existing 103 narration recovery regressions are unchanged. This is a
completed personal book and an improved bounded recovery path, not proof that
arbitrary future books can be completed without editorial judgment. Scripts,
source evidence, raw recognizer output and final checks are under
`Output/The_Voice_Drama3_2026_10_19/completion_audit/`.

## October 19 empty native take recovery

The Voice's new Drama job `56dd0db8-a583-4623-99a3-2be7976de1e8` stopped twice
on the pinned CLI message `Drama 3 ended before producing an audio frame`.
The native generator selected EOS at step zero. Captured batches reproduce
exactly; the failing requests also reproduce alone on an idle GPU. Changing
only each seed by one produces uncapped audio. These controls rule out batch
history and resource contention for these two captured failures; they do not
establish the model's general empty-output rate.

`drama3.render_phase` now handles only exit code 1 with that exact terminal
diagnostic, a contiguous unfinished suffix, and no WAV/code artifacts for that
suffix. The first unfinished request enters the existing bounded retry path;
unstarted followers keep their attempt and seed and render before the phase
finishes. Completed requests retain their bytes and provenance. Unknown errors,
partial artifacts, timeouts and cancellation retain their existing stop behavior.
Retry exhaustion still blocks final assembly when any audio is missing.

The fast regression failed before the fix and passes afterward. The 24 Drama,
29 phased-worker and 50 repair integration tests pass, including empty failures
before/after completed requests, finite exhaustion, systemic errors, incomplete
artifacts and cancellation. The real second failing four-request batch now
saves three first-attempt peers, retries only unit 900000 with seed 901730, and
produces four valid 44.1 kHz takes below the frame cap. All four pass Parakeet;
the peers' hashes are unchanged. This is recovery/content evidence, not whole-
book delivery approval.

The one-time production recovery restores the unstarted unit 900001 to attempt
one with its original seed; the previous receipt is backed up. Earlier saved
audio and provenance remain untouched. Resume was accepted at 12:49 Eastern,
with all 822 protected files hash-identical. The new child processes load the
fix directly; no server restart or model/runtime replacement was needed.
Evidence and replay commands are in
`Output/The_Voice_Drama3_2026_10_19/debug_empty_audio/REPORT.txt`.

## October 17 owner-authorized final assembly

The instruction "Im sure its fine. Assemble the book" accepts the current takes
for final assembly without asserting completed human listening. The one-time
finalization preserved 3,530 originals, bound approval to all 2,945 exact current
recording fingerprints, promoted the selected review candidates, and rebuilt
audible parents through the existing recovery/assembly helpers. Every resulting
parent WAV matches the verified listening-draft PCM hash. Reference-only parents
are excluded just as in the normal final assembler. Source, frozen plan, visual
decisions and narration configuration remain unchanged.

The production fix removes a stale `comparison_transcript` from the accepted
`_unit_report` view after preserving it in `raw_assessment`. Previously the parent
gate preferred the normalized ASR text over the explicitly accepted transcript,
and passage 8 failed despite valid approvals. A synthetic normalized-year report
reproduced the failure; the regression now verifies successful parent recovery,
preserved raw comparison/evidence, and unchanged rejection before acceptance.
The full native suite passes 451 tests with one dependency skip. The graph was
rebuilt and checked; no GPU model was loaded for finalization.

The final M4B in the job output and `audiobooks/The Devil at Genesee Junction/`
has 24 markers, duration 45,337.381995 seconds, and size 380,791,238 bytes. Both
copies hash to `65518c4a8122205e308716cd8137696bd3d26881347838da1aae1d5a357405b8`.
Full decode is clean and encoded audio packets match the verified draft. The
app API reports `done`; its review queue is empty and its narration signature
matches. All backup hashes were checked. Evidence and scripts are private under
`Output/Sentence_Boundaries_2026_10_17/final_book/`.

The owner subsequently authorized Drive upload and email delivery to Mike
Bullions. The single-file connector call failed before upload at its 100 MiB
limit. All four complete playable parts are now uploaded: 382,375,969 bytes,
covering all 1,999,378,566 source frames with complete-passage boundaries and no
gaps. Each part fully decodes and retains relative chapter markers and cover art.
Drive metadata verifies names, sizes, parents and owner-only sharing. The private
folder and four file links are recorded in `drive_handoff.json`; readback is in
`drive_verification.json`. Mike's
saved contact has no email and a sender/recipient Gmail search found no match;
his address has been requested. No email has been sent. The owner subsequently
reported deleting the multipart upload and will upload the full single-file
master when home. Do not restore the parts or email their old links. The local
master is intact; any email handoff now needs the owner's new full-file link
and Mike's exact address.

## October 17 whole-book listening draft

The current source-bound draft is in
`Output/Sentence_Boundaries_2026_10_17/whole_book_draft/`. Its audit verifies all
371 parents, 2,945 current clips, 335 review candidates and two intentionally
omitted reference-only units. Every selected WAV, receipt, report, spoken
projection and native generation record matches. All canonical source is covered.
The draft retains unresolved candidates without changing production decisions.

The 12:35:37 AAC M4B fully decodes without error. All 2,575 unit joins preserve
frames with the existing five-millisecond fades. Two retained original joins
have 10.96- and 4.45-second quiet intervals; they remain listening items. The
default export identified only foreword/epilogue, so a private metadata remux
adds 24 detected heading markers, combining adjacent fragments from the same
page. Encoded audio packet hashes before/after remux are identical. No global
chapter filter was changed. All 13 smaller copies split only at complete
passages, fully decode without error, and cover all 1,999,378,566 source frames.
Their combined size is 380,632,992 bytes; none has uploaded while approval is
pending for the complete draft payload.

Eight large primary transcript differences received an independent Whisper
check. It heard all three sentence spans omitted by the primary transcript;
the remaining large differences concern numeric forms, dates and word spacing.
No new repair or approval follows from those differences alone. The local review
page has five focused listening items, 293 other primary flags, working audio
seeks, and observation-only note export. It is not uploaded because its text
comparisons contain book text. Only generated audio and the short guide are
eligible for the owner's private Drive handoff. Full-draft upload awaits explicit
payload approval after an automatic approval-review rejection; the earlier short
reel/guide upload is complete and verified private.

## October 17 preferred prose delivery applied

The owner selected B for long prose, A for original names pacing, and authorized
execution. The selective prose pass adds parent indexes 164, 192 and 204 to the
sentence policy. All 117 prior source corrections remain; 26 semicolon edits
alter punctuation only. Two complete-entry boundaries in the over-limit forensic
sentence end in periods; the remaining edited separators become commas. All
canonical words and all other 368 parents' unit definitions are unchanged.

Fifteen native recordings completed below the cap without retry. Thirteen pass
both TDT and Whisper; two retain name/spelling and time-format differences.
The regenerated 132-word sentence is byte-identical to the owner-preferred B.
Three previews preserve frames across 12 joins, maximum join quiet one second.
The candidates are installed without approval; current live counts are 272 review
passages and 943 unresolved units. All 3,351 protected files are accounted for:
3,347 unchanged and four exact backups. Current unit WAVs and the frozen plan
are unchanged. GPU processes have exited. See
`Output/Sentence_Boundaries_2026_10_17/prose_pass/final_handoff_checks.json`.
The 3:09 current-prose reel and guide were uploaded to the owner's private Drive
after explicit upload authorization and owner-only permission readback. Names
pause compression was not selected or applied. The final master remains pending.

## October 17 sentence boundaries and generation capacity

New Drama 3 plans use `sentences_v4`: 75/100-word packing targets retain whole
sentences, including a sentence longer than the word target. An oversized
semicolon enumeration can split at its existing semicolons. A single sentence
above the native 1000-character limit is held with an actionable error, never
silently cut into arbitrary word groups. Parent packing also retains sentences.
The older boundary policies remain available for saved jobs.

The new default is 1536 output frames, 4096 context rows and 12 CPU expert layers.
The larger output budget permits about 71 seconds rather than 36; it does not
force longer delivery. The context increase also accommodates the narrator
reference. Four CPU layers caused a long probe to spill into shared GPU memory
and time out; 12 layers completed it. All timed-out evidence remains preserved.

Eight real probes completed below the frame cap; three exceeded the old cap.
All eight primary transcripts retained the expected endings, and seven secondary
transcripts did. Whole-content checks passed both recognizers on four probes;
name/word differences and one uncorroborated Whisper tail remain listening items.
The final 132-word probe completed with the exact new defaults in 40 seconds.
Other probes used earlier capacity/offload profiles, recorded in their provenance.
The 4:51 listening reel and brief guide are in the owner's private Drive folder.

For an existing job, `drama3_resource_migration` explicitly binds the frozen
runtime hash, old limits and requested limits for only output frames, context
length and CPU offload. Model, voice, sampling and text identity remain checked.
Selective `sentences_v4` overrides retain other passages' boundaries and audio.
Canonical source and the frozen plan remain byte-identical. Private evidence:
`Output/Sentence_Boundaries_2026_10_17/`; the six-passage application is recorded
under `six_passages/`. Generated alternatives still require listening approval.

The selective application produced 29 review candidates across six passages,
including five reused probe takes. All final takes are below the frame cap.
Two initial takes omitted substantial text and had long quiet tails; one bounded
retry replaced each, with both replacements passing both recognizers. Preserve
the initial takes and reports under `six_passages/initial_takes/`.
Fourteen final candidates pass both content comparisons; 15 retain differences.
Six unapproved previews preserve every frame across 23 joins, with PCM error at
most one LSB and maximum measured quiet at a join of 1.1 seconds. Existing unit
WAVs are unchanged. The app retains 271 review passages and 937 unresolved items;
these counts describe review work, not confirmed defects. Full native regression:
450 tests, one existing dependency skip. The graph was rebuilt and checked.

Subsequent owner listening identified uneven list pacing in the long sentence
at reel 2:20–2:30 and the names sample beginning 3:31. This is delivery feedback,
not content approval. The isolated comparison keeps source words and originals.
Fresh takes and comma substitution shortened the long sentence, but made the
names list longer; complete-entry groups also failed to shorten the names list.
The final names alternative instead removes 5.81 seconds from near-silent gaps
in the original take. Removed samples are below -50 dBFS; all retained samples
and every sample at or above that threshold are bit-identical. Approximate ASR
word spans overlapped quiet gaps and were unsuitable as edit boundaries, so
waveform evidence controls this experiment. No production pacing policy has
changed. Consult `pacing_comparison/comparison_report.json` and `pause_edit.json`;
timing measurements do not establish natural delivery without listening.

## October 16 second repair pass — earlier evidence

The owner requested the complete five-step repair goal: correct checker/retry
behavior, verify narration source, produce one focused listening pack, benchmark
CTC/CrisperWhisper, then selectively repair and verify assembly. Drama 3 remains
the narrator. The original queue must retain its listening gate.

- `narration_v2_critical_review` compares narrow notation equivalents while
  retaining short semantic differences. Meaning-sensitive short differences route
  to listening after the first check. Aggregate-only failures do not select a
  passing unit for regeneration. These rules cover both worker paths and cached
  audio. Every replacement of an existing unit archives its predecessor.
- The verifier benchmark contains 187 recordings. On 16 owner-accepted controls,
  updated TDT flagged two, CTC four and Crisper eight; all three flagged all six
  owner-labelled content failures. These small, selected, mostly older-engine
  controls support retaining TDT, not a universal accuracy claim. Forty unlabelled
  holdouts and 12 controlled waveform edits are reported separately. CTC alignment
  is conditioned on expected words and supplies diagnostics, not proof of speech.
- The new isolated verification environment uses CUDA inference, with no OCR/TTS
  overlap or changes to the existing narrator/transcription environments. The
  Windows Crisper experiment uses its Transformers verbatim backend, without
  expected-text hints. Both model revisions and downloaded file hashes are saved.
- All 2,971 original current recordings were scanned with exact hash checks.
  Nineteen have quiet intervals of at least five seconds at 10 ms RMS windows;
  none has clipped samples at the scan threshold. Quiet intervals require
  listening. The disputed pause measurement is explicitly labelled, and excerpt
  PCM is verified against the actual processed recording.
- The listening pack starts with eight short speech questions and 30 name
  excerpts: three for each of ten recurring names. It includes pauses outside
  the original queue. Exported choices bind to audio hashes and concern excerpts;
  they do not approve entire units or automatically change the book.
- Seventy-two additional footnote markers were visually checked against PDF
  evidence. Exact projection corrections preserve canonical source and earlier
  approved corrections. Bracket punctuation was separately tested on omitted
  narrative words; no lexical content was removed.
- Two matching saved takes were reused with generation validation and byte-exact
  reconstruction. Further alternatives are checked by TDT and independent Whisper.
  Repeated omissions in five passages motivated a scoped smaller-unit migration.
  `drama3_passage_unit_limits` applies only to named parent identities and is
  validated by both generation and review; changed boundaries require migration.
- An opt-in `captions_v3` policy separates sentences around parenthesized credits.
  It is scoped to one affected caption passage. Exact credit words remain in the
  spoken projection, with prose punctuation where the narrator omitted asides.
- The full suite is green: 442 tests run with one existing dependency skip. The
  production review handoff is installed with 147 unapproved alternatives, two
  reused from saved takes. Both content checks pass for 119; 28 retain differences.
  All 207 prior review passages remain, with no new approvals or current unit WAV
  replacements. The restarted app reports 271 review passages and 941 unresolved
  units. All 29,663 original files are accounted for by exact hash: 29,550 unchanged,
  113 backed up. The 62 unapproved passage previews preserve all frames across 499
  joins, with PCM differences within one LSB and no quiet interval over five seconds
  at a join. Alternative 1780015 has a 6.15-second internal pause, included in the
  listening pack. `installed.json`, `candidate_audit.json`, `join_verification.json`
  and `preservation_proof.json` contain the evidence. Final listening remains open.

Private evidence: `Output/Repair_2026_10_16_v2/`. Final audio remains gated on
listening decisions; no new acceptance receipts or final M4B are implied here.

The native backend is implemented, locally exercised, and active as the default
for new jobs and regeneration copies. The owner accepted the chapter listening
samples, noting one rushed compound phrase. Existing jobs keep their recorded
backend; a missing historical backend continues to mean Chatterbox. VibeVoice
remains available as a legacy choice.

## Implemented contract

- `app/drama3.py` orchestrates the tested Windows audio.cpp CLI. Executable,
  Q3 GGUF, embedded codec, CUDA libraries, narrator reference/transcript, source
  text, sampling, spoken projection, and optional history are bound to the plan.
  Registration hashes assets; resume verifies registered paths, size and mtime,
  reference hashes, and output provenance. Restoring a changed runtime is required
  before resuming its saved job.
- One GPU renderer, four requests per process (one in conservative mode),
  1000-character native chunk ceiling, 4096 context rows and 1536 output frames.
  A process has a 240-second bound. New plans use 12 CPU expert layers and
  sentence-preserving 75/100-word packing targets. Rendering and review share
  the same boundaries. Earlier plans retain their recorded settings unless an
  explicit scoped boundary or resource migration is applied.
- Native mono 44.1 kHz is retained through validation, gain normalization,
  five-millisecond joins and export. Raw WAVs and ten-codebook artifact envelopes
  remain under each job's `drama3_runs`. Published receipts bind them to the take.
  Frame-capped, partial, wrong-rate and invalid artifacts cannot become accepted
  cached audio.
- OCR, reference transcription, TTS and GPU ASR execute in separate phases.
  Windows Job Objects own worker descendants. Completed batch results are saved
  before process exit; interruption resumes unfinished units without duplicating
  completed narration.
- The existing queue, review and export flow is reused. Historical
  `vibevoice_*` checkpoint filenames are shared storage, not backend identity.
  Whole-unit retries use a new seed and retain existing accepted audio until the
  replacement is reviewed. Other units remain unchanged.
- New plans use the existing `calendar_clock_v2` spoken projection for explicit
  calendar days and clocks. Canonical source text is retained. This projection
  does **not** fix year-normalization differences in the content checker.
- Optional `drama3_history` maps string unit indexes to saved generation
  receipts. The adapter validates model/codec/reference and audio/code hashes,
  unwraps `payload_hex`, and writes native `{text, vq_codes}` history. This remains
  an experimental configuration API, without a repair UI or a quality advantage
  claim. It is not prefix/suffix inpainting.

## Local setup

The owner's ignored `app/config.json` now registers the tested executable,
Q3 model, CUDA DLL directory and audition-reference registry. The adapter uses the
existing Parakeet interpreter for orchestration and checking; it does not install
another Python TTS stack. Known audition references are copied exactly. Other
selected references are converted to mono 44.1 kHz, bounded to 20 seconds, and
transcribed in an owned GPU process before TTS starts.

The runtime currently lives under `Output/Drama3_4090_2026_10_15`; preserve that
directory and the registered reference paths. Configurable keys and environment
names are defined in `app/config.py` and illustrated in `app/config.example.json`.
This is a local integration, not a distributable runtime installer. The patch
source manifest includes the two new Python modules solely to maintain dependency
closure. No installer was built.

## Measured acceptance

Private evidence: `Output/Drama3_Migration_2026_10_15/`.

| Check | Observed result |
| --- | --- |
| Original chapter sample | 1,662 words, 30 units, 657.264 seconds of first-pass audio. 615.521 seconds including preparation, process loads, ASR and 17 retry requests. Stops for review; no approved final chapter master. |
| Review burden | 20 unresolved items across five passages: seven unit flags and 13 additional items surfaced by aggregate passage checks. Year/date representations and names contribute; some source-marker omissions also remain. No gate was relaxed. |
| Cancel and app exit | Both killed the owned process tree; resume reused completed requests without duplicates, preserved accepted fixtures and finished export. |
| Native failure | A deliberately invalid option on the real executable produced an actionable error; normal resume completed. |
| Real frame cap | A 64-frame probe reached the cap and was retained as failure evidence, never published as usable audio. |
| Whole-unit replacement | Real native replacement changed seed, kept original and peer WAV hashes until review, then adopted the candidate after a simulated acceptance confined to the disposable test fixture. |
| Wrong-word repair | Ordinary and prior-take-conditioned generation both changed the synthetic wrong word to the requested word, with independent ASR confirmation. Each pipeline took about 38.2 seconds excluding plan registration. No advantage established for history. |
| Delivery-only comparison | Same target text, seed and narrator compared with/without the ordinary take as history. Outputs retained. Comparative listening remains unverified; ASR does not establish delivery or absence of ringing. |
| Reference preparation | Exact audition reuse and generic GPU transcription both exercised successfully. |
| Export | Pilot WAV, MP3 and M4B decoded to finite mono 44.1 kHz audio at 42.146 seconds. No clipping; compressed exports retained cover art and chapter boundaries. WAV retained the exact expected sample count. |
| Browser | Native settings load with valid values; all three 18-second excerpts played with advancing playback time and no media errors. Playback was muted and is not a perceptual assessment. |
| Preservation | All 12,756 baseline job/audio/audit files hash-identical; Genesee remains canceled with its cancellation flag. |

The bounded chapter's maximum plausible whole-board GPU reading was 24,135 MiB;
two impossible driver readings were excluded and retained in raw telemetry.
This includes other applications and is not model-only memory. A sampled native
process recorded a 20,427,915,264-byte peak working set and a sampled
22,613,397,504-byte private usage. Full-book memory/throughput stability is not established.

Regression evidence: full base-interpreter suite passed (424 tests, 112 runtime
dependency skips); the audio-runtime Drama suite passed all 15 tests, and the
existing VibeVoice runtime suite passed all 172 tests during integration. After
the headroom change, all 172 shared runtime tests and 13 listening-review tests
passed again. The earlier retry-seed check also passed all 21 scheduler tests.
Real-process lifecycle checks and the native evidence above cover the actual
runtime separately from synthetic tests. Logs remain in the private evidence
directory.

## Activation and remaining review

1. Owner listening acceptance received. The third excerpt's abrupt start was an
   arbitrary preview cut; a longer excerpt of the same take was accepted, with
   the minor pacing reservation above. Files remain in an owner-only Drive folder.
2. The chapter's content flags remain review items, not silently accepted audio.
   The unchanged checker still flags some year/name representations and source
   marker omissions. Default activation does not approve a final chapter master;
   the same content-review gates apply to production jobs.
3. Server and browser defaults, including new regeneration copies, now select
   Drama 3. Browser and API regression checks passed. The idle local server was
   restarted, and the Desktop Storybird shortcut was verified and refreshed to
   launch this checkout. Existing saved jobs retain their backend and approvals.
4. The owner authorized a fresh full Genesee generation with Drama 3. Use the
   approved source/visual decisions in a new job, preserving the canceled legacy
   job and its audio. Record the new job and its actual outcome in current authority.

## Full-book headroom correction

The first production attempt stopped on a dense acknowledgments list after six
completed batches. The first 1,094 usable generated words remain saved. Windows
reported approximately 23.4 GiB dedicated plus 684 MiB shared allocation for the
native process during an isolated replay. With four CPU expert layers the same
request completed in 33s instead of 179s. This was a speed/memory comparison;
the long request still reached its audio cap and was not accepted.

The subsequent 249-word test used the new 35-word list bound with ordinary prose.
All nine first-pass units completed, at most 571 of 768 frames. Two retry takes
hit the cap and were rejected; saved generation records all remained below the
cap. The pipeline ended for name/content review, not a render failure, in 219.8s.
This does not certify the names or all spoken content as correct.

The owner was also running Foundry VTT. Whole-board VRAM still peaked at
23,768 MiB during the revised test, so generation waited for that work to finish.
On 2026-10-15 the owner authorized closing Foundry and resuming. Native inspection
found Foundry already closed and 868 MiB whole-board VRAM at idle. The guarded
one-shot started fresh job `7554bee0-d4ec-4e79-8228-70ed8a00851b` at 13:17 Eastern,
with approved pages 5–355, the same narrator, and M4B output. Source/visual copies
and preservation of the legacy job were verified by hash. Both prior attempts
remain intact. The new job was paused at the owner's 15:55 Eastern checkpoint,
with 39,713/121,204 provisional words, 984 completed clips and 4h13m of audio.
All 248 completed batch exit records succeeded; saved takes have no frame caps.
Measured throughput implies roughly 5h20m of first-pass rendering still required
after resume, excluding checking, repairs and review.

The isolated Parakeet/Whisper audit completed and all 3,997 protected files remain
hash-identical. Of 102 Parakeet flags, 60 clear the year/date diagnostic and 80
clear that diagnostic or the independent comparison. Thirty seeded random passes
also pass Whisper. Twenty-two clips still flag with both recognizers after number
normalization. Twelve have missing continuation and near-silent tails verified in
raw model output; ten retain other name/format/content discrepancies. No causal
claim about chunk length follows from this audit. Three unchanged diagnostic
examples and the full report are in `pulse_1555` under the private evidence folder.
The owner authorized resuming after the D&D session. At 22:32 Eastern on
2026-10-15, the same job resumed through the normal API after all 3,997 protected
files matched their checkpoint hashes. The local service was restarted as PID
27400 on port 8765. The first resumed batch advanced generated words from 39,713
to 39,887, with about 20 GiB whole-board VRAM in use while Foundry remained open.
The audit did not regenerate clips, change production gates, or install models;
its findings remain unresolved review evidence during the resumed generation.

True audio infilling is not implemented or exposed. It still needs aligned
prefix/suffix conditioning, duration and boundary handling, PCM-preserving splice
logic, and the handoff's insertion/deletion/boundary/listening proofs. No production
legacy job was resumed, old model/audio removed, installer built, commit made or
release published by this integration task.

## Post-run audit — 2026-10-16

The headroom job stopped at 09:48 Eastern, with 119 assembled passages, 245
review entries and no M4B. Eighteen final attempts hit the frame cap; eight lack
`last_candidate`, but seven of those have fully validated earlier unit receipts
under a parent repair hold. `run_generate` counts only `last_candidate` when
reporting missing audio. The seven retained takes also pass independent Whisper.
Only unit 860002 lacks a usable take: each raw attempt speaks its opening clause
for about two seconds, followed by near-silence through the 35.7-second cap.
The clause ends at a superscript reference marker; causation needs a bounded
render-input comparison, not an assumption or a longer generation cap.

The frozen audit covered 2,972 latest saved units and 370 complete parents.
Parakeet flags 229 units; 163 clear the diagnostic year/date comparison. Whisper
checked those 229, 30 seeded primary passes, seven retained missing-error takes,
three capped takes and 30 owner-labelled controls (299 recordings). Thirty-three
latest clips still flag after both diagnostic comparisons; fifteen have more
than five seconds of quiet tail already in raw output. These are diagnostic
categories, not a count of clips requiring new generation. Eleven retained
earlier takes exist beneath the 33; eight pass independent Whisper, but one
contains the source contamination described below. Seven are reuse candidates.
One of the 30 sampled primary passes (1890007) retains a quantity/content concern.

Of 251 parent flags, 41 clear the date/year probe. Of the remaining 210,
185 arise only from accumulating smaller differences. Seventy have no flagged
individual units. Names, contractions, clocks and formatting contribute; neither
these counts nor an ASR pass certify delivery or authorize blanket acceptance.
The probe is not production-ready: six raw Whisper passes acquire shadow flags,
and year ranges, decades and some clock forms remain unsupported. The original
gate misses owner-labelled delivery defects, as does Whisper; accepting whenever
either recognizer passes would be unsafe for quality. Six strict negative probes
retain differing values, missing negation, repetition and missing/added sentences.

Ten approved source units contain the exact extraction instruction from
`Config.ocr_prompt`. Parents are 43, 77, 103, 112, 133, 161, 208, 221, 270 and 355
(zero-based). Nine current takes speak the instruction, independently confirmed
by nine additional Whisper checks. Parent 103's latest take stalls before the
instruction, while its earlier ASR-passing take includes the contaminated text.
Do not reuse that take as clean narration. These are source errors, not proof
that the narrator invented content. Some silent tails also produce spurious
Whisper text beyond file duration; those transcripts alone do not prove additions.

Recommended next work, not yet authorized or applied: clean the ten source
artifacts while preserving approved book content; correct same-value comparison
and retained-take accounting with regression coverage; reassess parent flags
without discarding short semantic errors; restore verified reusable takes under
the review workflow; then run bounded repairs only for confirmed remaining
defects, including the missing unit. Keep production stopped until the owner
chooses that next step. No acceptance gates, job/source state or audio were changed.
Private evidence, manifests, comparisons and preservation hashes are in
`Output/Drama3_Migration_2026_10_15/final_audit_2026_10_16/`; the reusable diagnostic
script is `Output/Drama3_Migration_2026_10_15/final_audit.py`.

## Authorized cleanup, verified reuse and targeted repairs — 2026-10-16

The owner subsequently authorized the recommended sequence: clean source
artifacts, correct the checker and saved-take accounting, reuse verified
recordings, then repair confirmed defects. This entry supersedes the preceding
audit's instruction to wait for authorization.

Source corrections use the existing spoken projection and migration mechanism.
The ten exact extraction-prompt echoes were checked against their blank PDF pages
and omitted. Two units contain only that artifact and now need no WAV. Additional
PDF checks corrected footnote markers, a word join and two printed one-and-one-
eighth fractions misread by OCR as one-and-one-half. Bounded number-word and
punctuation expansions retain the corrected values. The frozen plan, raw source
blocks, approved visual decisions and original voice/runtime settings remain
unchanged. Drama plan validation permits only evidenced source projections;
unrelated voice/runtime changes still fail. Future standalone default-prompt
echoes become visual-review items.

Production narration comparison now handles date/clock projections, contextual
calendar years and decades, plus unambiguous modal contractions. Regression
checks retain changed values, days, years, negation, repetition, wrong historical
year pronunciation and quantities read as years. Digit-only ASR output cannot
establish pronunciation. Generic word-difference budgets remain unchanged;
diagnostic semantic comparisons are not blanket acceptance rules. Parent
assessment uses the same narration comparison. There is no fuzzy name waiver or
rule accepting a clip merely because either recognizer passes.

Saved-take accounting now checks the actual prior audio, hash, source and runtime
provenance before reporting missing audio. Exhausted retries retain valid prior
audio under review, including when a worse latest candidate exists. Corrupt or
forced-regeneration receipts do not qualify. Fourteen earlier recordings were
reused unchanged: seven behind the false missing-audio error and seven beneath
worse latest takes. The contaminated earlier parent-103 take was not restored.

Twenty units received bounded repairs: 430006, 770002, 860002, 900001, 1030004,
1120000, 1330004, 1400007, 1610004, 1640003, 1760000, 1790003, 1890001, 1890007,
2040012, 2080006, 2700003, 3060009, 3190003 and 3600000. Every published repair
passes both Parakeet and independent Whisper content comparison. Unit 860002's
same-seed marker-only probe completed at 558 frames instead of its prior 768-frame
cap. This is bounded evidence about that input, not proof of a universal stall
cause. Difficult fraction/plate-number passages needed explicit number words and
further bounded renders. Models, environments and GPU serialization are unchanged.
Whisper's final unit-1890001 transcript includes an apparent ending timestamped
largely beyond the file's duration; Parakeet does not report it. Preserve that
evidence and resolve delivery by listening rather than asserting a spoken addition.

Final checks find no missing audio, 164 valid assembled passages and 207 passages
held for review (966 unresolved clip items). Review lists include context clips
and aggregate passage differences; this is not a count of confirmed defects.
No listening approvals were created, and no M4B was exported. The idle app was
restarted with the fixes and the job restored to `audio_review_required`; the
full generation scheduler was not restarted. Existing review decisions remain.

The preservation audit checked 10,638 protected files: 10,587 are unchanged in
place and 51 have byte-identical backups, with no missing originals. Raw source,
visual decisions and the plan remain hash-identical. Full native test discovery
passed 433 tests in the base runtime (118 dependency skips) and audio runtime
(one PyMuPDF skip covered by the base run). After the final omission/progress
adjustment, 55 affected phase, adapter and review tests passed. Evidence and all
replacement/retirement receipts are under `Output/Repair_2026_10_16/`, including
`final_result.json`, `preservation_result.json` and `final_runtime_tests.log`.
No installer, release, upload, recurring automation or commit was made.
