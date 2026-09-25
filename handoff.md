# Narration auditions and context continuation

Updated 2026-09-13. Active owner request: execute this investigation in a new task. Prepare real, small blind auditions before choosing a production approach. Open weights only. The owner means Chatterbox Multilingual V3, not CosyVoice 3.

## Authority and current checkout

Read `D:\Audiobook_Pipeline\CLAUDE.md` completely, then `.claude/skills/narration-auditions/SKILL.md`. Use Graft before source searches. Run native Windows Graft outside the managed sandbox if Node cannot spawn Git; do not change protected output permissions. Read AGENTS.md and preserve all existing work.

The original checkout at `D:\Audiobook_Pipeline` contains authorized, uncommitted visual review implementation and unrelated branding assets. A new Codex worktree may not contain these changes, this handoff, local jobs, voices, or audio. Read this handoff by its absolute original path. Treat original local evidence as read only; keep audition scripts and outputs isolated. Do not reset, clean, stash, stage everything, or assume default branch equals the current app. No production changes are required for the initial auditions.

## What the owner wants

Original English Chatterbox has won their previous listening comparisons. Chatterbox Multilingual V3 has not yet been auditioned here. The owner favors continuation with context as the next approach and wants a worthwhile VibeVoice 7B quant audition. They now authorize bounded local setup, necessary model downloads, and generation for these experiments. Do not substitute proprietary services or reaudition rejected models without new evidence.

Use the saved current voice `D:\Audiobook_Pipeline\app\voices\Ray Porter PHM.wav`. Verify its existence and input requirements; make nondestructive converted copies if needed. Older audition results used `samples\Voice_Sample\male_ref.wav`, so historical scores are not a direct comparison with this reference.

## Why this matters

The latest Jurassic Park audiobook completed operationally, but the owner heard the title mispronounced immediately. Its opening was not actually listened to before completion was reported. No pronunciation correction has been verified. Successful generation, ASR coverage, and pleasant narration are different claims.

Preserve the existing output `D:\Audiobook_Pipeline\audiobooks\Jurassic Park\Jurassic Park.m4b` (reported 352,652,694 bytes). Preserve job `D:\Audiobook_Pipeline\app\jobs\993e8772-09ec-4f3f-a51f-191806c798d8` and all its segments. The September 12 run processed 211 PDF pages, 128,934 words, 4,958 narration blocks, 5,406 chunks and 570 buckets. These are prior recorded measurements; verify paths and state before relying on them.

Local job evidence includes `extraction_before_manual_review.json`, `source_blocks.json`, `blocks.json`, `visual_review.json`, `editorial_review_notes.json`, `manual_extraction_audit.json`, and `final_narration_preview.txt`. The job received manual visual passage and heading corrections. These do not prove the generic extraction bugs fixed: blank background images were flagged on 210 pages, table structure was damaged, DNA strings were spoken, and some headings/publication text needed correction. Audition ordinary reviewed prose and the title to isolate narration from extraction. Do not silently treat editorial descriptions as original prose.

The requested Drive folder was created at https://drive.google.com/drive/folders/1-Xpv23wMLpYVFePfhRKKley-zsOv16XL . Upload did not complete: the connector limit was 100 MB and browser fallback required sign in. Upload is paused following the quality complaint. This audition task must not resume it or rerun the full book.

## Current generation mechanism

Previously inspected source: `app/narrate_worker.py`, `_generate_batched` around lines 397 to 492, prepares the reference conditionals once, tokenizes independent plan chunks, sorts them by length, batches them, then restores source order for assembly. `app/batched_narrate.py`, `batched_generate` around lines 71 to 215, starts a fresh DynamicCache per request. `build_plan` around lines 175 to 210 carries text, pauses, headings and provenance, not scene or performance history. Recheck spans through Graft because source can change.

Sharing the same voice reference does not carry narrative context. The public Chatterbox multilingual generate interface inspected September 13 has no explicit previous text/audio continuation argument. Do not describe reference conditioning as true stateful continuation. Existing custom English batching is not proven compatible with V3.

## Model candidates and primary sources

1. Original English Chatterbox: existing production baseline, neutral exaggeration 0.5, CFG 0.5, temperature 0.8 unless actual config establishes otherwise. Preserve the production environment.
2. Chatterbox Multilingual V3: https://github.com/resemble-ai/chatterbox and https://github.com/resemble-ai/chatterbox/blob/master/src/chatterbox/mtl_tts.py . The inspected README selects `ChatterboxMultilingualTTS.from_pretrained(device=device, t3_model="v3")`; omitting the version selects legacy V2 in the inspected implementation. Verify current revisions and explicitly pin V3. Begin with the stock backend in an isolated environment.
3. VibeVoice Large/7B selective 8 bit: https://huggingface.co/FabioSarracino/VibeVoice-Large-Q8 . Publisher reports 11.6 GB weights and about 12 GB VRAM, quantizing the language backbone while preserving audio components. Those are publisher estimates, not local measurements or proven identical quality. Inspect actual files and loader compatibility before choosing this build.
4. Alternative selective 8 bit: https://huggingface.co/marksverdhai/vibevoice-7b-bnb-8bit . Publisher reports about 11.3 GB weights and 11.4 GB VRAM, preserving acoustic components in BF16. Choose one practical 8 bit implementation first, not both automatically.
5. Smaller fallback only if needed: https://huggingface.co/marksverdhai/vibevoice-7b-bnb-4bit . NF4 with audio components preserved. Its short ASR test is not evidence of acting or audiobook quality.

Base references: https://huggingface.co/vibevoice/VibeVoice-7B , https://github.com/microsoft/VibeVoice , https://arxiv.org/abs/2508.19205 . Confirm the downloaded model is the TTS 7B/Large model, not VibeVoice ASR 7B. Long context/up to 90 minute generation is a research capability claim, not a validated local audiobook configuration. Refresh primary sources, record licenses, exact model/code revisions, loader requirements and disk estimates. Do not install an entire GUI stack just because one model card uses it if a supported isolated CLI works.

Optional mechanism reference, not another required audition: https://github.com/boson-ai/higgs-audio/blob/main/examples/generation.py accumulates text/audio history. Use it to distinguish actual history conditioning from Chatterbox reference reuse.

## Bounded experiment

1. Establish a small common listening set: title pronunciation microtest plus roughly three 30 to 90 second scenes spanning narrator prose, a sustained dialogue turn, and a narrator/dialogue transition. Use existing local reviewed source, with paths and exact selections stored only in ignored private output. Preserve canonical wording across models. If pronunciation aliases are tested, record the canonical to spoken mapping and compare them explicitly rather than silently rewriting one arm.
2. Audition original Chatterbox, explicit Multilingual V3, and one viable VibeVoice 7B selective 8 bit build. Use the same reference and comparable processing. Generate two or three repeats where practical; record seeds and all settings. Do not assume seeds make the vocoder deterministic. Avoid an unnecessarily large Cartesian test matrix.
3. Compare context strategies while holding model, text, voice and settings constant: current independent chunks; intact paragraph or speaker turn; previous sentence plus target generation with alignment and removal of repeated audio. Only add recent generated audio conditioning if technically supported and useful, with scene resets and periodic anchoring to the original reference. Label this as a conditioning experiment, not native continuation. Reject skips, duplicated words, alignment errors and voice drift. Investigate actual native context support before claiming it exists.
4. Deliver randomized blind WAV samples, a short neutral listening guide and a separate concealed model/settings mapping. Do not reveal the mapping before the owner ranks samples. Retain raw audio plus consistently loudness matched listening copies. Measure generation time, audio duration, peak dedicated VRAM, clipping, silence, and text coverage. Automated scores support diagnosis but do not establish pronunciation, naturalness or the user's preference. Listen using available audio tools where possible and state any limitations honestly.
5. Report what actually ran, failed or remains untested, and await the owner's listening verdict before selecting a winner or integrating into production. Update this handoff with artifact locations and results, keeping private book text and audio out of Git.

## Lessons already learned

CosyVoice 3 and Fish S2 Pro lost prior auditions and their test environments were removed. Do not confuse that with rejection of Chatterbox V3. Intact long turns beat splitting into semantic beats in one controlled historical sample. Expressive settings 0.7/0.35 helped a long 480 character turn but lost on short turns; do not apply them globally. Most measured turns were short. Chatterbox S3Gen is stochastic; waveform differences alone cannot establish regression. Prior blind mappings were once revealed too early; keep them concealed this time.

Current assembly defaults are 150 ms chunk and 650 ms paragraph gaps. Historical model padding added about 380 ms across joins, so nominal pauses are not audible pauses. Keep pause treatment controlled and report it. Scene break timing remains a separate unimplemented idea, not a reason to inflate every pause.

## Execution constraints

Hardware: RTX 4090 24 GB, i9-13900K, 32 GB RAM, native Windows. OCR and TTS must never overlap on the GPU. Check active processes before starting; do not kill unrelated workloads. Run candidate GPU inference sequentially. Keep production chatterbox, fish speech and dnd transcribe environments isolated and unchanged. Existing chatterbox was Python 3.11 / torch 2.6.0+cu124; verify rather than upgrading it. Base Python is `C:\Users\paulm\miniconda3\python.exe`; PATH python can resolve to the Windows Store alias. Keep new environments/model code outside the repository and private audition output under an ignored location, checking Git exclusions before writing book content.

Do not overwrite completed audio or source caches. No full book generation, Drive upload, installer, release, destructive cleanup, or production model switch is in scope. Do not track or distribute purchased books, generated narration or voice samples. Use native Windows for any authorized Git writes. This handoff is documentation only; no model has been downloaded or audition generated by the handoff preparation itself.

## Executed audition results, 2026-09-13

The authorized bounded audition has run. Original English Chatterbox, explicit Chatterbox Multilingual V3, and FabioSarracino/VibeVoice-Large-Q8 selective 8-bit TTS all produced real audio using the saved Ray Porter PHM reference. No production backend was changed. No full book was regenerated and nothing was uploaded.

Primary playback package: `D:\Audiobook_Pipeline\Output\Narration_20260913\Listening\Listening guide.md`. Start with `Audition_A_Take1.wav`, `Audition_B_Take1.wav`, and `Audition_C_Take1.wav`; each includes the title, prose, sustained dialogue and narrator/dialogue transition. The same letters identify candidates across scenes and both takes. The listening guide links the separate scenes and context comparisons. This directory is Git ignored.

The mapping is deliberately concealed until the owner ranks the samples. It is stored outside the Listening folder at `D:\Audiobook_Pipeline\Output\Narration_20260913\concealed_mapping_private.json`. Do not read or reveal it to the owner before the verdict. Raw directories and detailed measurement files also identify models and must stay out of blind playback. No winner or production integration has been selected.

Completed scope: 92 raw synthesis calls, including rejected diagnostics, generated 1,166.05 seconds of raw audio in 1,550.51 seconds of measured synthesis time, excluding model loading, setup and validation. The accepted package has 37 playable WAVs, including six convenient audition reels, separate scenes and context comparisons. This count includes alternate presentations of the same speech, not 37 independent experiments. All 37 decoded through FFmpeg. Listening copies are mono 24 kHz PCM16, matched to -21 LUFS; measured output range is -21.018 to -21.000 LUFS, with maximum sample peak 0.90964 and no clipped listening samples. Float raw audio is retained. Model padding remains, with 150 ms nominal chunk and 650 ms paragraph gaps. Changing segmentation also changes the number of pauses, which remains a confound.

Correctness: all six title microtests back-transcribed as the requested title. This does NOT verify how the title sounds. Baseline scenes have word-level transcription differences, including names and pronunciation-sensitive words; they are not declared correct or improved by ASR alone. Exact source selections, word-level results, edits, silence intervals, per-call generation times and GPU allocator/device measurements are private. Local CPU voice-encoder first/last-window consistency proxies were measured for 25 listening clips, without inventing a validated drift threshold. The assistant had no local audio-listening tool; pronunciation, naturalness, voice match and drift still need the owner's listening verdict.

Context outcome: independent chunks, an intact turn, and preceding-sentence regeneration with aligned prefix removal were generated through original Chatterbox with matched settings. The first matched take passed the accepted content/crop checks. The second failed short-response extra-word checks. One additional matched-seed repeat passed raw boundary matching but then failed independent checks on the actual cropped audio: a word substitution and an extra word before the short response remained. Both entire matched repeats are held out and preserved, including their failed listening copies under `RejectedListening`. Only the clean first take is offered for J/K/L. No fourth repeat was attempted. Prefix continuation is NOT qualified for production; raw ASR token matching alone did not make the crop reliable.

VibeVoice also generated two full-dialogue, single-call probes, compared against its same-text independent-chunk results as M/N. Neither hit the generation cap; one had word-level back-transcription substitutions and the other matched normalized text. This tests within-call context plus segmentation/pause changes. Neither Chatterbox interface exposes native prior text/audio history. The selected VibeVoice loader maintains history inside one call but does not return a complete resumable context state; cross-call stateful continuation was not implemented or validated. Recycling generated audio as the next voice reference was not added.

Resources: the isolated code, environments, weights and tokenizer occupy approximately 25.03 GiB at `D:\ml_repos\narration-auditions-20260913`. Exact model/code revisions, local weight hashes, package lists and reference hashes are in `provenance_private.json` and `method_private.md`. The sampled maximum total dedicated GPU use across loading and generation was 15,336 MiB, including desktop use. Sampling was every 0.5 seconds and can miss brief peaks; CUDA allocator peaks are also recorded per call. CPU transcription overlapped some synthesis, so elapsed times are operational measurements, not a controlled speed ranking. TTS GPU processes were sequential; OCR did not run on the GPU concurrently.

Environment correction: the production environment actually already had Transformers 5.2.0 alongside torch 2.6.0+cu124 and chatterbox-tts 0.1.7. It was not upgraded. The V3 environment is isolated and explicitly loads `t3_mtl23ls_v3.safetensors` via the stock loader. The separate VibeVoice runtime uses Transformers 4.51.3 and bitsandbytes 0.49.2 with SDPA; 197 Linear8bitLt modules were verified, with acoustic, semantic and prediction components excluded from quantization. The selected model and code declare MIT. The maintained community TTS loader was used because Microsoft's current main branch removed the original TTS implementation.

Detailed records are at the package root: `summary_private.json`, `results_private.json`, `session_peaks_private.json`, `voice_consistency_private.json`, `crop_verification_private.json`, `rejections_private.json`, `decode_verification.json`, and `method_private.md`. A working copy also remains in the task's ignored Output directory. Existing source-job text hashes still match, the reference hash still matches, and the completed M4B remains 352,652,694 bytes. Existing uncommitted app and branding work was preserved. Await the owner's blind rankings before revealing identities or choosing a production direction.


## Owner blind listening verdict decoded, 2026-09-13

The owner ranked the samples before identities were revealed. All 11 reviewed playback files were hash-verified against the saved blind receipts. Full observations and timestamps: `Output/Narration_20260913/owner_verdict_20260913.md`.

Mapping: A = Chatterbox Multilingual V3; B = original English Chatterbox; C = VibeVoice Large/7B selective 8-bit. J = original Chatterbox intact turn; K = original independent chunks; L = original preceding-sentence regeneration plus prefix trimming. M = VibeVoice independent chunks; N = the same VibeVoice model/configuration with the whole dialogue in one generation call.

Take 1 preference was B > A > C. Original Chatterbox therefore beat V3 on these chunked auditions. However, C Take 2 sounded fantastic beneath musical artifacts and slow pacing, and the owner explicitly said it could have been the favorite if those problems were resolved. VibeVoice is NOT rejected. N Take 1 sounded fantastic; N Take 2 was the owner's overall favorite, with great inflection and continuity. Whole-dialogue VibeVoice is the preferred direction for the next bounded investigation, not an authorized production switch or proof of book-length reliability.

The owner heard breath reverb in A/B around 0:14–0:15; daiquiris mispronunciation around 0:30; A's hard-g InGen (required pronunciation: In-jen) and jarring mid-dialogue tempo change around 1:17. C had musical/non-speech artifacts at the opening and around 0:30; C Take 2 additionally had artifacts behind dialogue at 1:36–1:41 and briefly around 1:57. M Take 1 slowed around 0:36; M Take 2 was slow/robotic with music around 0:32–0:35. Causes of the breath and music artifacts remain unproven.

J and K both sounded good; K had a barely perceptible seam tempo change. No strict J-versus-K ranking was stated. L was the least favorite short-context sample, robotic, with repeated s after calculations around 0:17 and repeated ior from behavior around 0:24. L is REJECTED BY OWNER LISTENING. This supersedes the earlier clean/accepted wording for its first take. Whole-word ASR acceptance did not detect faulty phoneme/tail joins. Reports and the listening guide now carry this correction; original audio remains preserved.

Next investigation should retain VibeVoice whole-dialogue generation, isolate the musical artifacts, compare pace separately, and verify speech-only pronunciation corrections without modifying source text. Do not infer that quantization alone caused the artifacts. Production and completed audiobook files remain unchanged. No new synthesis was initiated while recording this verdict.

## ADHD-friendly audition presentation, 2026-09-13

The owner explicitly invoked the i-have-adhd skill for future auditions. The persistent narration-auditions record now contains the skill path and presentation defaults: one listening question per round; two or three short playable clips on the same passage; exact listening duration; one simple preference response; repeats and diagnostics retained internally for subsequent focused rounds. Do not present another large mixed matrix as the initial listening task. The September 13 owner verdict is also recorded there, including N Take 2 as favorite and L's failed listening acceptance.

## VibeVoice lead and focused pace round, 2026-09-13

Owner clarification: VibeVoice shows the most promise, especially pronunciation. Even in the first ABC comparison, it would have been the favorite without hallucinations and with quicker tempo. Preserve the observed first-take B > A > C ranking but do not interpret it as a preference for Chatterbox's underlying performance. VibeVoice is the lead candidate; whole-dialogue N Take2 is the preferred reference performance.

Prepared Output/Narration_20260913/Pace_Round1/Listening: three blind timing variants of the full N Take2 performance, with pitch/formants preserved and common -21 LUFS loudness. Total listening time is 142.97175 seconds. All three WAVs passed decode, finite-audio, clipping and loudness checks and the delivered copies match their SHA-256 receipts. No new TTS ran. This calibrates pace, not artifact removal or native model speed control. Await the owner's A/B/C/none preference before revealing this round's separate mapping_private.json.

After the pace choice, focus the next small generation comparison on unwanted musical audio using intact passages and matched repeats, with one setting changed at a time. Existing artifact causes remain unproven. The owner also asked about VibeVoice-1.5B. Verified Microsoft's August 2025 announcement includes both 1.5B and 7B; a separate 1.5B audition is worth consideration but has not been generated or downloaded here. Do not assume the smaller model fixes artifacts, and do not confuse size-plus-precision comparisons with a controlled quantization test. Source links and full method are in Pace_Round1/round_notes.md.


## Pace round owner verdict, September 13, 2026

Owner ranking: C best by far. A was bad with reverb throughout; B was horrible and robotic. A and B are rejected for audible quality.

Verified mapping: A = Rubber Band tempo 1.1 (10 percent faster); B = tempo 1.2 (20 percent faster); C = tempo 1.0 (original rate). Every arm used the same N Take2 performance and passed through Rubber Band with pitch=1 and preserved formants, followed by loudness normalization. C is original rate, not a byte-identical unprocessed source copy.

The faster processed variants degraded the preferred voice. This rejects the tested time-stretching configuration for delivery. It does not establish that the owner prefers slow narration: the pace comparison was confounded by the audible processing defects. The owner's earlier desire for quicker natural delivery remains open. It also does not establish that every possible speed-adjustment algorithm would fail.

Decode, finite samples, no clipping, and matched loudness were technical checks only. They did not validate perceptual pitch/timbre preservation or naturalness. The assistant did not directly listen before delivery. Do not present those checks as proof that an audition sounds good.

Keep the original N Take2 waveform and natural rate as the quality reference. Prioritize the next bounded VibeVoice generation investigation on musical hallucinations, using original-rate playback and intact context. If tempo is investigated again, first establish whether the generator supports a genuine speaking-rate control or another controlled generation approach; do not silently insert spoken instructions or equate faster rendering with faster speech. Do not reuse the rejected A/B processing as a quality fix.

Owner model-link clarification: the recently released microsoft/VibeVoice-ASR-Streaming-1.5B is speech recognition (audio to text), not the older VibeVoice-1.5B TTS model. The owner was asking about that ASR release. It is not a narration candidate; no new 1.5B audition was requested by that question.



## First 1.5B TTS audition and VibeVoice artifact round, 2026-09-13

The owner authorized proceeding and asked about 1.5B TTS. Official microsoft/VibeVoice-1.5B TTS has now actually generated four samples locally. This is the older text-to-speech model, not ASR Streaming 1.5B. Weights are pinned to c00898d257e6b46004e3e2866a47534085fb685a, with three hashed shards totaling 5,408,202,454 bytes, saved outside the repo at D:/ml_repos/narration-auditions-20260913/vibevoice-1.5b-model. It runs BF16 in the existing isolated VibeVoice environment without package changes. Runtime count is 2,704,021,985 parameters including audio components; zero quantized linear modules. The existing 7B retains its verified 197 selective 8-bit modules.

Private delivery: Output/Narration_20260913/Artifact_Round1/Listening/Listening guide.md. The first round presents only Prose_A_Take1, Prose_B_Take1 and Prose_C_Take1, totaling 143.07 seconds. Ask which has the least unwanted music/ringing/reverb/robotic sound. Configuration identities are randomized in mapping_private.json and must remain concealed until the verdict. The same labels carry into the retained repeat and dialogue samples.

Configurations: 7B CFG 1.3; same 7B CFG 2.0; official 1.5B BF16 CFG 1.3. Same saved voice reference, original wording, intact prose/dialogue, 20 diffusion steps, SDPA, 1200 token cap, and two matched seeds per passage. Stronger guidance is exploratory, not an established music fix. The small-versus-large comparison changes size and precision and cannot isolate quantization. Each scene is a single call, so comparisons against old chunked C also include context, pauses and random-draw changes. All playback is natural generated speed with gain-only loudness matching and PCM16 conversion. No time stretching, denoising or internal cropping.

Completed: 12 synthesis calls, 583.33 seconds of raw audio, 1047.38 seconds measured generation excluding loading and checks. Peak sampled total GPU memory during generation was 14443 MiB, including desktop; half-second sampling can miss peaks. GPU inference was sequential and Ollama had no loaded model at preflight or before each call. CPU Whisper checks overlapped some TTS, so timing is operational rather than a controlled speed ranking.

All 12 presentation WAVs decoded, were finite and unclipped, and measured -21.010 to -21.000 LUFS. CPU faster-whisper-large-v3 checked all raw clips. Word differences, including spelling variants and possible substitutions/omissions, are retained in raw ASR reports. These checks do not verify pronunciation, musical artifacts, or naturalness. No artifact-free claim or winner is established before owner listening. All raw takes remain; no take was selected for pleasantness or removed for sounding bad. 72 copied files were hash-verified; the listening guide was deliberately rewritten to use original-project playback paths.

Detailed evidence: method_private.md, small_model_provenance.json, tokenizers_private.json, loader_*.json, raw generation/ASR receipts, results_private.json and summary_private.json. The installed source acknowledges spontaneous BGM as a known behavior; its cause in our clips remains unresolved. Model/source/voice isolation is preserved, and no production backend, completed audiobook, installer or release changed.


## Owner prose verdict, September 13, 2026

The owner preferred B among the three first-take prose clips. A was described as not bad/not terrible, not very emotive, and flat overall. B was good and the favorite. C had an artifact around 0:08, strangely accelerated delivery around 0:17, and another artifact around 0:34. C was very natural and emotive and would have been liked a lot without the artifacts, but was the most imperfect of the batch. No strict A-versus-C ranking was supplied.

Verified mapping: A = VibeVoice Large/7B selective 8-bit, CFG 1.3; B = the same model, CFG 2.0; C = official VibeVoice-1.5B TTS in BF16, CFG 1.3. These are the artifact round labels, not the original engine or pace labels.

This supports stronger 7B guidance on this prose take. It does not establish artifact-free output, reliable improvement across seeds, or suitability across a whole book. B had no specific artifact reported by the owner; do not convert that into verified absence of artifacts. A and B held model, text, reference, seed, context, diffusion steps and presentation constant; guidance was the intended changed variable. The cause of C's artifacts is unproven. C was generated at its native rate with gain-only presentation, so the reported acceleration was not introduced by the rejected time-stretching process. The 1.5B model remains promising for expressiveness and is not categorically rejected.

Next focused listening check uses the already generated Dialogue_A_Take2 and Dialogue_B_Take2, reblinded as D/E in Dialogue_Check. This compares the two 7B guidance settings on the intact dialogue passage associated with the earlier N preference. It uses the matched second seed (20270913), the same text and reference, natural generated timing and common loudness. Both saved second takes matched normalized source words in CPU back-transcription; this does not validate pronunciation or naturalness. The original N recording remains preserved and is not substituted for either new arm. No new synthesis is needed. Ask only which dialogue performance sounds more natural, allowing neither; reveal D/E after that choice. Both first dialogue takes and all 1.5B repeats remain retained for later checks.

Dialogue check delivery: Output/Narration_20260913/Artifact_Round1/Dialogue_Check/Listening/Listening guide.md. Total 100.00 seconds. D/E mapping is private until the verdict. No new GPU inference ran while recording this feedback.


## Owner dialogue verdict, September 13, 2026

The owner preferred D as more natural. E was decent, but variations in cadence made it lose to D.

Verified mapping: D = Dialogue_B_Take2, VibeVoice Large/7B selective 8-bit with CFG 2.0. E = Dialogue_A_Take2, the same model with CFG 1.3. Both use the same intact dialogue, voice reference, second seed (20270913), 20 diffusion steps, natural generated timing and gain-only loudness matching. D is 47.866667 seconds; E is 52.133333 seconds. Their delivery hashes match the retained source receipts.

CFG 2.0 has now won the first-take prose comparison and this matched second-take dialogue comparison. It is the lead setting for further VibeVoice narration tests. This is evidence across two passages and two seed values, but not a same-passage repeatability result, an optimum-guidance sweep, or proof of full-book reliability. The owner did not report a specific musical artifact in the winning clips; absence of a report is not proof that musical hallucinations are eliminated.

The 1.5B TTS model remains an expressive but less reliable candidate on the reviewed prose take, with artifacts near 0:08 and 0:34 and an abrupt speed change near 0:17. This dialogue check compared only the two 7B guidance settings, so it adds no direct 1.5B-versus-7B evidence.

Preserve the existing production backend and all original audio. For the next bounded continuity pilot, use 7B selective 8-bit, CFG 2.0, 20 diffusion steps, the same original voice reference, intact context and native timing. Test a longer passage with narration/dialogue transitions for music, missing/repeated words, pronunciation and cadence before any production integration. No new synthesis or production change occurred while recording this verdict.



## Continuous pilot and VRAM findings, September 13, 2026

The owner authorized a longer continuous passage with the preferred CFG 2.0 setting and asked whether 7B would run on a 12 GB card.

Selected source blocks 843 through 857 inclusive, 432 whitespace-delimited words, form an intact landing scene with dialogue, narration, helicopter noise and electronic-beeping descriptions. These descriptions make spontaneous non-speech generation relevant to the stress test. No wording or source-job data was modified. Earlier candidate ranges contained evident source-text defects; the selected scene avoids those known defects rather than silently correcting them during this narration test. Source and reference hashes remain guarded against the parent experiment records.

This is one single-call pilot, not a seed repeatability or full-book qualification run. The winning 7B selective 8-bit weights, BF16 audio components, original Ray Porter PHM reference, SDPA, 20 diffusion steps, CFG 2.0 and deterministic token selection were retained. Seed 20270913. The generated-token cap is 4000 to permit the longer passage; successful completion requires that the cap flag is false. The allocator ceiling is unchanged at 85 percent of this 24 GiB GPU. There is no simulated 12 GB allocator cap, CPU model offload or physical 12 GB card test.

Generation took 295.70 seconds and produced 126.53 seconds of audio. CUDA peak allocations during loading were 10.833 GiB, with 10.855 GiB reserved. During generation the peaks were 11.188 GiB allocated and 11.430 GiB reserved. Whole-run sampled device memory peaked at 14508 MiB, including desktop and CUDA overhead; the sampled pre-load baseline after CUDA setup was 2183 MiB. Half-second samples can miss brief peaks. Reserved memory includes allocations; do not add allocated and reserved values together. PyTorch allocator values exclude some driver/library memory; do not equate them with the complete physical-card requirement.

The publisher advertises 12 GB minimum and 16+ GB recommended for this selective-8-bit model: https://huggingface.co/FabioSarracino/VibeVoice-Large-Q8 . These are publisher claims, not physical-card validation here. More specifically, our unchanged 85 percent allocator ceiling would allow only approximately 10.2 GiB on a nominal 12 GiB card, below the measured 10.833 GiB needed for loading alone. The installed PyTorch API documentation confirms that the fraction limits the allocator to total visible memory multiplied by the fraction. Thus the CURRENT settings are not a fit for 12 GB; this is an inference from a measured allocation and the configured limit, not a physical-card trial. A different memory budget, offload strategy or quantization might permit 12 GB, but none was tested and headroom would still be tight. A 16 GB card is a more realistic capacity target for this tested 8-bit configuration, still subject to actual-card and longer-input validation. These measurements do not describe full-precision 7B. Previously tested 1.5B BF16 peaked at 7,974 MiB total device memory, with more headroom but outstanding owner-reported quality issues.

Presentation uses only common loudness gain and PCM16 conversion. Actual loudness -21.000 LUFS, sample peak 0.754883, no clipping, successful full FFmpeg decode. CPU faster-whisper-large-v3 checks the raw output without a source-text prompt. It does not verify musical artifacts, voice match, naturalness or phonetic accuracy. SequenceMatcher differences are retained rather than called WER or silently corrected. All raw and presentation audio is preserved. No production backend, installer, completed book or environment packages were changed.

Playback and measurements: Output/Narration_20260913/Continuity_Pilot/Listening/Listening guide.md and summary_private.json. Owner listening verdict pending. No artifact-free claim has been made.
