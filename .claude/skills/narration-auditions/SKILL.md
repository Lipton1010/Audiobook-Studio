---
name: narration-auditions
description: Narration voice and delivery audition history: the CosyVoice 3 and Fish Audio S2 evaluations (both rejected and deleted), the proposed local performance director design, and the Stage 0 / Stage 1 / Stage 2 blind listening methodology with full verdicts on segmentation and Chatterbox delivery parameters. Load before running another audition or changing exaggeration/cfg_weight.
---

Full verbatim history migrated out of CLAUDE.md on 2026-08-04. Nothing was edited; source line numbers are noted per block.
<!-- CLAUDE.md lines 371-473 -->
### Narration-quality A/B prototype (2026-07-29)

(V, user direction) The owner selected two candidates for the first controlled comparison: Chatterbox with improved logical segmentation and pauses, and CosyVoice 3. The supplied Audition excerpt was one continuous passage, not a splice. The local prototype reconstructed the passage from a Whisper large-v3 transcription because the exact source text was not available here. Both candidates therefore use the same reconstructed words and the same approved `samples\Voice_Sample\male_ref.wav`; this is a fair relative comparison, not an exact replay of the production input.

(V, isolated local generation) `app\ab_dialogue_chatterbox.py` generated a 26.370-second, 24 kHz Chatterbox comparison. It kept the complete 480-character character passage in one synthesis call, inserted an 850 ms transition, and synthesized the 27-character narrator return separately. Generation used Chatterbox's existing 0.5 exaggeration, 0.5 CFG and 0.8 temperature values with a fixed seed. The private result is under the gitignored `Output\Narration_AB` folder. Whisper large-v3 back-transcription recovered the complete supplied passage and narrator return. This verifies text coverage, not acting quality.

(V, isolated local setup and generation) CosyVoice source revision `074ca6dc9e80a2f424f1f74b48bdd7d3fea531cc` was tested in a private environment under `Output\CosyVoice3`, separate from the app runtime. The minimal files required by the CosyVoice 3 loader occupy 5,427,030,749 bytes (about 5.05 GiB), excluding the repository's unused duplicate weights. The final environment used Python 3.10.20 and CUDA-enabled torch 2.3.1+cu121. Official `openai-whisper==20231117` required `setuptools==69.5.1` and `--no-build-isolation` to build in this environment. The installed Windows ONNX Runtime exposed CPU rather than CUDA execution, producing a provider fallback warning; generation nevertheless completed.

(V, isolated local generation) `app\ab_dialogue_cosyvoice.py` generated a 32.930-second, 24 kHz CosyVoice 3 comparison from the same text and reference. It applied restrained, conversational character direction and a separate calm third-person-narrator direction, with the same 850 ms transition. The official inference API internally divided the 480-character character passage into two model pieces even though the prototype supplied it as one logical role segment; both pieces received the same direction and reference. Whisper large-v3 back-transcription recovered the complete passage and narrator return. Speaker-embedding cosine similarity between those two longer character pieces was 0.9772, a useful consistency proxy but not a substitute for listening.

(V, local measurements) Integrated loudness measured -20.94 LUFS for the Chatterbox result and -21.43 LUFS for the CosyVoice result, a 0.49 LU difference. On the development RTX 4090, cached CosyVoice model load took 12.817 seconds; peak CUDA allocation was 4.210 GiB and peak reservation was 5.285 GiB during this short test. This is not an HP Omen measurement. Reasoning from that reservation suggests the model may fit the Omen's 12 GB RTX 3060, but performance, thermal behaviour and successful execution there remain unverified.

(V, local cache observation) The first CosyVoice load downloaded its auxiliary WeText normalizer into `C:\Users\paulm\.cache\modelscope`; the folder's pre-test state was not recorded, so do not claim ownership or delete it. The successful controlled run redirected ModelScope and Hugging Face caches under `Output\CosyVoice3`; the isolated WeText cache contained 31,686,511 bytes.

(V, prototype scope) No human naturalness judgment has been made yet. Neutral blind copies were created as `Output\Narration_AB\Blind_Sample_1.wav` (32.930 seconds) and `Blind_Sample_2.wav` (26.370 seconds); preserve the mapping until the owner chooses. The generic prototype scripts are uncommitted, private passage text is not stored in them or their metadata, and neither production narration logic nor the installer was changed for this comparison. Do not integrate either backend or rebuild a full audiobook until blind listening identifies the preferred direction.

(V, owner blind listening and focused local rerun) The owner judged Blind Sample 1 (CosyVoice 3) awful and Blind Sample 2 (Chatterbox) better. Both pronounced the source-style word `helluva` as an unacceptable elongated `he-looov-uh` rather than the intended `hell of a`. Treat this as a speech-input normalization defect, separate from the broader acting-quality judgment. An isolated Chatterbox rerun changed only that spoken form to `hell of a`, retained the same logical segmentation, settings, reference, seed and 850 ms role transition, and produced `Output\Narration_AB\Chatterbox_pronunciation_fixed.wav` (26.210 seconds, SHA-256 `b739b8813aabb88b6f7c3147703834dddad1f192dd34540bafc95179f51409b8`). Whisper large-v3 back-transcribed the corrected opening as `a hell of a shriek`. This verifies ASR recognition of the requested words; the owner has not yet judged the corrected audio. The book text itself was not edited, and no production normalization rule has been implemented.

(V, owner-directed cleanup 2026-07-30) After rejecting the CosyVoice result, the owner asked to remove CosyVoice to conserve disk space. The verified cleanup removed the isolated `Output\CosyVoice3` source, environment, model and redirected caches; the CosyVoice output and metadata; its blind copy; its untracked prototype script and generated bytecode. It removed 76,657 files totaling 15,537,004,256 bytes (14.470 GiB) and then verified that every explicit target was absent. Chatterbox assets were retained. The ambiguous `C:\Users\paulm\.cache\modelscope` folder was not removed because its pre-test ownership was not recorded.

### Fish Audio S2 evaluation (2026-07-30)

(V, owner-directed cleanup) The owner separately authorized deletion of the Whisper large-v3 diagnostic model. `C:\Users\paulm\.cache\whisper\large-v3.pt` was verified at 3,087,371,615 bytes, permanently removed, and its absence verified. The Whisper cache then contained no remaining files.

(V, official documentation and license inspection; not local execution) Fish Audio S2-Pro v2.0.0-beta is a 4B slow/400M fast Dual-AR model with 44.1 kHz output, reference cloning and free-form inline delivery controls. Fish's current documentation lists Linux or WSL and 24 GB GPU memory for inference. The Fish Audio Research License permits personal evaluation/testing but grants no commercial rights; commercial use requires a separate written license, and distribution has license/attribution requirements. Do not select Fish for a public or commercial release without resolving those terms.

(V, Windows preflight) WSL was absent and the current Codex process was non-administrative. Two unelevated WSL install forms exited 1 and made no system change. A later Windows administrator prompt was canceled, so WSL remains uninstalled. The evaluation therefore used a fully removable native-Windows fallback rather than claiming the documented WSL path was tested.

(V, isolated native-Windows setup) Official Fish source tag `v2.0.0-beta` was cloned under gitignored `Output\FishS2\src` at commit `3578e4e7099ee85464756dab27a3af86b5a21331`. The official `fishaudio/s2-pro` model snapshot revision was `1de9996b6be38b745688de084d87a5633f714e4e`; its 13 published files total 11,011,629,649 bytes, while the local directory including Hugging Face metadata totals 11,011,631,121 bytes. An isolated Python 3.12.13 environment was created under the same Fish root. A direct editable dependency resolution incorrectly selected `llvmlite==0.36.0`, which rejects Python 3.12; using the repository's frozen official lock instead installed its intended `numba==0.61.2`/`llvmlite==0.44.0` combination. Torch 2.8.0+cu128 imported successfully, reported CUDA 12.8, and detected the RTX 4090. This proves the tested native environment, not general Windows support.

(V, local Fish inference) The same approved `male_ref.wav` was used. Because Fish cloning requires matching reference words and no transcript had been stored, an isolated Whisper small-English model transcribed the 20-second reference; that temporary model was deleted after validation. Fish synthesized the same reconstructed passage with speech-only `helluva` -> `hell of a`, restrained conversational direction for the quoted character and calm neutral direction for the narrator return. Model load took 56.37 seconds, reference encoding then completed, and 603 semantic tokens generated in 139.99 seconds at 4.31 tokens/second. The complete process returned in 218.2 seconds and produced 27.956825 seconds of audio.

(V, local resource measurements) During generation, repeated `nvidia-smi` samples reached 23,574 MiB used out of 24,564 MiB, 75-82% GPU utilization, 45 C and about 233 W. Fish's own log reported 22.33 GB used. This executed configuration cannot fit the HP Omen's 12 GB RTX 3060; do not describe that as a projection anymore. No reduced-memory or quantized Fish configuration was tested.

(V, output validation) `Output\Narration_AB\FishS2_directed.wav` is mono 44.1 kHz, 27.956825 seconds, 2,465,836 bytes, SHA-256 `cd0db540a147a41c5a02341508f375ba32e2087dc5445ff6155182eef591027e`, -23.96 LUFS integrated and -4.99 dBFS true peak. FFmpeg decoded it without error. Whisper small-English back-transcription recovered the complete passage and narrator return, recognized `a hell of a shriek`, and did not transcribe the inline delivery tags. This verifies coverage and the corrected phrase, not naturalness, voice match or acting quality. The owner has not listened yet.

(V, cache cleanup and remaining footprint) After successful generation, the isolated Whisper model and redundant UV, pip, Conda and Hugging Face setup caches were removed and verified absent: 54,675 files totaling 9,709,544,880 bytes (9.043 GiB). The still-runnable Fish test tree now contains 51,218 files totaling 19,753,189,832 bytes (18.397 GiB): about 10.26 GiB model, 8.12 GiB environment and 0.02 GiB source. It remains entirely under `Output\FishS2` and can be permanently removed as one verified target after listening. No production narration file, installer, tracked source or WSL component was changed for Fish.

(V, owner listening verdict and cleanup 2026-07-30) The owner judged Fish worse than Chatterbox and asked for its removal. The verified cleanup permanently removed `Output\FishS2` and `Output\Narration_AB\FishS2_directed.wav`: 51,219 files totaling 19,755,655,668 bytes (18.399 GiB). Both explicit targets were then verified absent. Chatterbox assets were retained, and `wsl.exe --status` still reports that WSL is not installed.

### Proposed local performance director (2026-07-30; design only)

(V, local source/package inspection) The installed `chatterbox-tts==0.1.7` generation API exposes `exaggeration`, `cfg_weight`, `temperature`, sampling controls and an audio reference. It does not expose named emotions, character identities or acting-direction tags. Its `exaggeration` value is passed as a scalar conditioning value. The current serial worker calls Chatterbox with its defaults; the custom batched path also uses one voice-conditioning object and common default controls. Current production planning reduces narration to text plus before/after silence. Path A labels ordinary prose and dialogue alike as `body`, and no current plan field preserves speaker, tone or pronunciation direction. This explains a missing capability; it does not by itself prove which setting will sound best.

(V, official documentation inspection; not local execution) Resemble's current Chatterbox guidance recommends the original model's default `exaggeration=0.5` and `cfg_weight=0.5`, with a lower CFG value around 0.3 and exaggeration at 0.7 or higher as a starting point for more dramatic delivery. Current Chatterbox-Turbo documentation describes paralinguistic tags such as `[laugh]`, `[cough]` and `[chuckle]`. Those are a different model's nonverbal controls, not evidence that the installed original model understands arbitrary tags such as `[angry]` or `[pause]`. Turbo and Multilingual V3 must be treated as separate backends rather than assumed drop-in replacements for the current custom batching code.

(R, recommended architecture; not implemented) Do not let an LLM rewrite the book. Add an optional, validated `performance_plan.json` sidecar after extraction and before speech chunking. A local text model should review one scene or overlapping window at a time, carry forward a character bible based only on explicit textual evidence, and return strict structured annotations anchored to exact source offsets and hashes: narration/dialogue kind, stable speaker ID, one bounded delivery-profile label, pace, deterministic pause requests, explicit speech-only pronunciation aliases and confidence. A deterministic compiler must reject mismatched source spans, retain canonical extracted text, fall back to neutral settings when confidence is low, segment on speaker turns and semantic beats, and include the performance plan in the resumability hash so changed direction cannot reuse stale speech segments.

(R, Chatterbox mapping; not tested) Map the LLM's small label set to a few owner-approved Chatterbox presets rather than allowing it to invent raw numeric settings per line. Keep temperature fixed during the first comparison. Reasonable audition starting points are the current neutral defaults for narration and, for clearly expressive dialogue, approximately `exaggeration=0.65-0.75` with `cfg_weight=0.3-0.4`; these are hypotheses derived from the official guidance, not validated application defaults. Insert pauses as deterministic PCM silence rather than text tags. Keep one licensed reference voice and use subtle, consistent profile changes per recurring character; do not fabricate accents or alter dialect grammar. A word such as `helluva` can have a separate spoken alias such as `hell of a` while the source text remains unchanged.

(R, local model candidate and next experiment; not installed) `qwen3:8b` is a plausible first local director model because its Ollama Q4 package is about 5.2 GB and its model card emphasizes instruction following and creative/dialogue tasks. This machine currently has Ollama and several vision/OCR models but no dedicated text-only performance-review model. Do not download `qwen3:8b` without confirming the additional removable disk use. The next useful experiment is isolated: give the model the supplied dialogue plus nearby context, validate its sidecar, and render three short blind Chatterbox samples—current defaults; speaker-aware segmentation/pronunciation/pauses only; then the same plan with a stable character delivery preset. Do not run another full book or modify protected production narration logic unless that listening test shows a clear improvement.

### Stage 0 narration audition: owner verdict decoded (2026-07-30 runs, verdict 2026-08-02)

`app/stage0_narration_audition.py` is the untracked Stage 0 harness. It builds a private canonical plan, verifies source preservation with SHA-256 per segment, renders each arm through one common fade and loudness path (30 ms fades, -21.0 LUFS target, PCM_16, 24 kHz mono), then copies the arms to neutral `Stage0_Blind_NN.wav` filenames with a `secrets.SystemRandom()` shuffle and writes the concealed mapping beside them. No book text lives in the script; the passage sits only in gitignored `Output\Narration_Stage0\<run>\performance_plan_private.json`. It does not import or modify production narration code.

Two runs exist. `20260730_Stage0_v1` rendered arms A, B, C; no owner verdict for that run is recorded in this file. `20260730_Stage0_followup_v2` rendered arms A, C, D to answer one question: does the restrained character profile work better when the complete character turn stays in ONE synthesis call?

(V, owner blind listening 2026-08-02, mapping opened only after the verdict) Ranking best to worst was `Stage0_Blind_01` then `Stage0_Blind_02` then `Stage0_Blind_03`, which decodes to **D best, A middle, C worst**.

- Arm A, 25.670 s, 2 calls of 364 and 143 chars, neutral defaults `exaggeration=0.5 cfg_weight=0.5`, 150 ms gap, NO pronunciation alias. This is the production-equivalent baseline.
- Arm C, 30.100 s, 6 calls: the character turn split into five sentence segments of 117/93/72/79/115 chars at `exaggeration=0.7 cfg_weight=0.35` with 250/220/260/240/850 ms pauses, then the 27-char narrator return at neutral defaults.
- Arm D, 25.450 s, 2 calls: the whole 480-char character turn in ONE call at `exaggeration=0.7 cfg_weight=0.35`, 850 ms transition, then the same narrator return at neutral defaults.

WHAT THIS ESTABLISHES. C and D are parameter-matched, speaker-matched, reference-matched and share both seeds (21260730 dialogue, 21261211 narrator) and the 850 ms transition. Segmentation is the ONLY variable between them. D won and C came last, so within this run fragmenting a single speaker turn is what hurt, not the expressive profile. Two supporting details: fragmentation order is monotonic with preference (D splits the character turn into 1 call, A into 2 because its 364/143 packing cuts mid-turn, C into 5, and the ranking was D, A, C); and C carried the `helluva` to `hell of a` alias while A did not (`spoken_characters` exceeds `canonical_characters` by 2 in C-01 and D-01 and is equal in both A segments), so C had a pronunciation advantage over A and still lost.

This contradicts one plank of the design proposal in the previous section, which recommended segmenting on speaker turns AND semantic beats. Semantic-beat splitting inside a single speaker turn is exactly what Arm C did.

WHAT IT DOES NOT ESTABLISH, and do not let this get rounded up later:
- n=1 passage, n=1 listener, one render per arm. S3Gen is stochastic and the earlier Stage 0 repeat check was not byte identical despite per-segment reseeding, so this ranking is not shown to be reproducible.
- D versus C confounds the call boundaries with the five 220 to 260 ms pauses those boundaries force. Either could be the audible cause.
- D versus A confounds delivery parameters with segmentation AND with the pronunciation alias, so this run does NOT show that `exaggeration=0.7 cfg_weight=0.35` beats the neutral defaults.

OPERATIONAL BLOCKER. Arm D's winning call is 480 canonical characters (482 spoken). Production `CHAR_CEILING` is 400, so the current worker cannot produce what the owner preferred. Raising the ceiling is not free: the 2026-07-26 measurements in this file show long chunks are compute-bound and forced into small batches, giving only ~1.1-1.2x on the batched engine. The cost at 480 chars has not been measured. Do not raise `CHAR_CEILING` as a side effect of some other change.

### Stage 1: delivery parameters isolated, RENDERED and judged (2026-08-02)

The harness gained a `prepare-stage1` subcommand that builds a three-arm plan from the follow-up plan, because `_render` and `_blind` both hard-require exactly three unique arm names.

- Arm D: the Stage 0 winner, copied verbatim, seeds unchanged. Anchor.
- Arm E: Arm D with the character turn reverted to the current neutral defaults and EVERYTHING else held fixed, including seeds, spoken text, alias and pauses. A preference between D and E is attributable to the delivery parameters alone, which is the confound Stage 0 could not resolve.
- Arm D2: Arm D with every seed shifted by an explicit offset and parameters untouched. A preference between D and D2 measures the stochastic noise floor, which bounds how much any of this ranking is real.

(V, local execution against the real follow-up plan, output written to a temp directory only) `prepare-stage1` produced `arm_order ["D","E","D2"]`, schema 3, a canonical SHA-256 matching the source plan, and 2 segments per arm. Verified: D and E dialogue parameters differ ONLY in `exaggeration` (0.7 vs 0.5) and `cfg_weight` (0.35 vs 0.5); D and E seeds are identical `[21260730, 21261211]`; spoken text, pauses and alias counts are identical across D and E; D2 keeps D's parameters and shifts both seeds. Four guards were also executed and fired correctly: a zero seed offset is rejected, a source plan with no Arm D is rejected, an existing output plan is refused, and the three-unique-arm gate passes. The in-code isolation assertions (seed, spoken text, pauses, source span must match between D and E) are what make this trustworthy rather than a copy that silently drifted.

(V, owner-executed render on the 4090, `Output\Narration_Stage0\20260802_Stage1_v1`) chatterbox-tts 0.1.7, torch 2.6.0+cu124, CUDA 12.4, RTX 4090. All three arms rendered through the same fade and loudness path to -21.0 LUFS. Durations: D 25.450 s, E 26.650 s, D2 25.090 s. The reference hash guard passed, so all three used the approved `male_ref.wav`.

(V, owner blind listening 2026-08-02, mapping opened only after the verdict) Ranking best to worst was `Stage0_Blind_03` then `Stage0_Blind_02` then `Stage0_Blind_01`, which decodes to **D2 best, D second, E worst**. The owner described the gap between best and worst as obvious and said he would pick it every time. Blind copies were hash-verified against the mapping.

WHAT THIS RESOLVES, and it is the confound Stage 0 could not touch. D and E differ ONLY in `exaggeration` (0.7 vs 0.5) and `cfg_weight` (0.35 vs 0.5). Same seeds, same single 482-character call, same alias, same pauses, same narrator segment at neutral defaults. E finished BELOW both renders of the D configuration, so at fixed segmentation the restrained expressive profile beats the current neutral defaults on this passage. Stage 0 isolated segmentation with parameters matched; Stage 1 isolates parameters with segmentation matched. Both contributors are now independently demonstrated rather than confounded.

THE NOISE FLOOR IS BOUNDED, and this is the other half of the design paying off. D and D2 are the same configuration with different seeds. They landed adjacent at ranks 1 and 2 with E below both. Had seed variation dominated, E could have landed between them; it did not. So seed variation is real (the owner did prefer one identical-configuration render over the other) but it is SMALLER than the parameter effect. That is the precise claim; do not inflate it into "the result is reproducible".

STILL NOT ESTABLISHED:
- Same single 480-character excerpt, same listener, one render per arm per configuration. Two runs agreeing is better than one, but this has never been tested on narration-heavy text or on a second passage.
- NO evidence about narration parameters. Both D and E used the neutral defaults for the narrator return, so nothing here supports applying `exaggeration=0.7 cfg_weight=0.35` to ordinary prose. Apply it to dialogue only.
- No sweep. 0.7/0.35 is shown to beat 0.5/0.5, not to be optimal. 0.6/0.4 and 0.8/0.3 are untested.
- The `CHAR_CEILING` 400 versus 480 blocker from the previous section is unchanged and is now load-bearing, because the winning configuration depends on keeping the turn whole.

CONSEQUENCE FOR THE PERFORMANCE DIRECTOR DESIGN two sections above: amend it. Segment on speaker turns ONLY, never on semantic beats inside a turn (Stage 0), and map the expressive profile to dialogue only while narration keeps the neutral defaults (Stage 1). The rest of that design, especially the validated sidecar anchored to source offsets and hashes, is unaffected.

No production narration logic, tracked source, installer or job data was touched. Both Stage 0 runs, the Stage 1 run and all three mappings are preserved.


<!-- CLAUDE.md lines 593-623 (Stage 2) -->
### Stage 2: recovered boundaries WIN on listening; the expressive profile does NOT transfer to short turns (2026-08-03)

`app/stage2_boundary_audition.py` is a new prototype that runs in the BASE env (the chatterbox env has no PyMuPDF, so PDF selection cannot live in the Stage 0 harness). It writes only the private plan; the validated `stage0_narration_audition.py` renders and blinds it unchanged, so no existing narration code was touched.

Run at `Output\Narration_Stage2\20260803_Stage2_v1`. Passage auto-selected from Power of the Dog: 579 chars, 16 recovered paragraphs (new body block indices 1151 to 1166), verified to sit inside a SINGLE old block so today's production genuinely fuses it. It contains 12 clean dialogue turns of lengths 7, 7, 9, 10, 11, 12, 15, 16, 17, 21, 28 and 55. That is deliberately the COMMON case; Stage 0 and Stage 1 both used a 480 char turn from the top 0.4% of this book.

- Arm P: production today. The passage packed by the real `narrate_worker.pack_text`, giving 2 calls of 346 and 232 chars, neutral parameters, 150 ms gaps.
- Arm B: the extraction fix only. 16 calls at the recovered paragraph boundaries, neutral parameters everywhere, 400 ms paragraph gaps.
- Arm BD: Arm B plus Stage 1's finding. Identical segmentation, seeds, spoken text, pauses and spans, asserted in code; the ONLY difference is `exaggeration` 0.7 and `cfg_weight` 0.35 on the 12 dialogue turns.

No pronunciation alias in any arm, so an alias cannot confound this the way it did Stage 0's A against C.

(V) Rendered on the 4090, chatterbox-tts 0.1.7, torch 2.6.0+cu124, CUDA 12.4, all three through the same fade and loudness path to -21.0 LUFS. Durations P 32.270 s, B 39.800 s, BD 41.400 s. The reference hash guard passed, so all three used the approved `male_ref.wav`.

(V) Owner blind listening 2026-08-03, mapping opened only after the verdict, every blind copy hash-verified against both the mapping and the rendered arm. Ranking best to worst was `Stage0_Blind_02`, then `Stage0_Blind_03`, then `Stage0_Blind_01`, which decodes to **B best, BD second, P worst**.

WHAT THIS SETTLES.

- THE EXTRACTION FIX IS VALIDATED BY LISTENING. P is exactly what production does today and it came last. P versus B is a clean isolation: same text, same neutral parameters, only segmentation and the pauses it implies differ. Both arms carrying recovered boundaries beat P, and they did so under DIFFERENT parameter settings, which makes the boundary result robust rather than a lucky pairing. This is the first listening evidence for the change, and unlike Stage 0 and Stage 1 it lands on the short-turn common case.
- THE STAGE 1 EXPRESSIVE PROFILE DOES NOT TRANSFER TO SHORT TURNS, and this negative result is the more useful half. B versus BD is a clean parameter isolation and BD finished BELOW B. Stage 1 established 0.7/0.35 beats the neutral defaults on a 480 char turn; Stage 2 shows it does not beat neutral on turns of 7 to 55 chars. The benefit is LENGTH DEPENDENT.

CONSEQUENCE FOR THE PERFORMANCE DIRECTOR DESIGN, and this narrows the amendment recorded at the end of the Stage 1 section. That amendment says to map the expressive profile to dialogue and keep narration neutral. On this evidence that is TOO BROAD. Only 19 of this book's 5,024 turns exceed 400 chars, so applying 0.7/0.35 to all dialogue would have made 99.6% of turns worse. The cheapest correct action is to NOT build it: production applies no such profile today, so nothing needs changing. If it is ever revisited, gate it on turn length and prove the gate on a length sweep first.

STILL NOT ESTABLISHED, and do not let this get rounded up:
- One passage, one listener, one render per arm, same limits as every stage so far.
- NO SEED CONTROL in this run. Stage 1 included Arm D2 to bound the noise floor; Stage 2 has no equivalent. B and BD landed adjacent and the owner's verdict on BD was soft ("not as bad as 1"). Treat "B beats BD" as suggestive. The well-supported gap is that BOTH beat P, which the owner separated clearly.
- Durations differ for known reasons, not content: B and BD carry fifteen 400 ms paragraph gaps that P does not, and BD's parameters render slightly slower on identical text.
- Nothing here says anything about narration parameters, or about a second book.

WHAT REMAINS BEFORE A FULL BOOK: throughput (unmeasured, see the previous section), then the Power of the Dog re-narration, roughly 3 hours of 4090 time, which requires DELETING `blocks.json` rather than resuming over it.

### Stage 3: pause timing against a commercial reference; block_gap_ms settled at 650 (2026-08-04)

The owner bought the Audible edition of Power of the Dog and downloaded it via Libation as a plain mp3 (20.21 h, 26 chapter marks including front matter, 44.1 kHz mono). It sits in gitignored `Output\Reference_Audio\`. Analysis extracted TIMING STATISTICS ONLY: no transcription, no content, nothing from the recording in the repo. Having the same book made structural comparison possible rather than comparing against someone else's prose rhythm.

METHOD ERROR WORTH NOT REPEATING. The first pass anchored the silence threshold to the noise floor (5th percentile plus a fraction of the range). Both files contain TRUE DIGITAL SILENCE (11.7% of the commercial, 5.5% of ours), so the 5th percentile clamped at the -200 dB floor and the threshold collapsed to -127 dB, counting only exact zeros. Every number in that pass was measuring the wrong thing. The fix is to anchor to the SPEECH level instead, p90 minus 35 dB, which lands near -54 dB and correctly separates speech from both room tone and model padding. The segment-level padding measurement was unaffected because raw segments have only 0.3% digital silence, so its threshold landed correctly at -49.5 dB by accident.

(V) THE MODEL PADDING, and this is the load-bearing number. Measured directly on 402 of the 10,042 real segment WAVs: median 180 ms leading and 200 ms trailing, so **380 ms across every join**. Confirmed independently in the assembled book, where gaps pile up at 680-880 ms (11.4% of all gaps, predicted 400+380=780) and 430-630 ms (7.8%, predicted 150+380=530). So the nominal pause values in `PAUSE_PROFILES` understate the audible pause by roughly half. Anyone reasoning about pause length from the nominal number alone will be wrong.

(V) DISTRIBUTIONS, 112 minutes sampled from each file at matched fractional positions:

| band | commercial | ours at 400 |
|---|---|---|
| word/clause 60-150 ms | 30.1% | 45.8% |
| comma/phrase 150-350 | 20.2% | 23.9% |
| sentence 350-700 | 26.5% | 14.1% |
| paragraph 700-1200 | 17.2% | 16.0% |
| scene break 1200-2500 | 5.6% | 0.1% |
| section over 2500 | 0.5% | 0.0% |

p50 340 vs 160 ms, p90 1030 vs 790, p99 1792 vs 1070, max 4700 vs 1070. Speech occupies 70.8% of their timeline against 76.9% of ours. Our narration is DENSER at every level, which reverses the worry that the recovered-paragraph book was too spaced out.

ROUND 1 (`Output\Narration_Gap\20260804_gap_v1`), arms 400 / 510 / 650 nominal on a 4 minute excerpt with 70 paragraph joins (17.2 per minute, chunks 6902-6971). Owner verdict: "they all sound incredibly similar". THAT WAS A BRACKET-DESIGN ERROR, NOT A NULL RESULT. Measured long-gap medians were 720 / 790 / 930 ms, i.e. +9.7% and +29.2%, and duration discrimination inside continuous speech needs roughly 20-25%. The arms were verified genuinely distinct by hash and duration, so the files were fine; the span was 32% end to end and could not resolve anything. PROCESS ERROR TOO: the mapping was revealed in the same message that asked for a verdict, and the owner had to volunteer that his pick preceded reading it. Seal the mapping until the ranking arrives.

ROUND 2 (`Output\Narration_Gap\20260804_gap_v2`), same excerpt, arms 650 / 900 / 1200, verified BEFORE handing over: measured medians 930 / 1180 / 1470 ms, steps of +26.9% and +24.6%, both above threshold. Owner verdict, blind: 1200 "way too long", 900 "too long", **650 the favourite**. Severity scaled monotonically with length.

CONCLUSION: `block_gap_ms` 650, audibly ~1030 ms. It beat 400 and 510 from below in round 1 and 900 and 1200 from above in round 2, so it is bracketed on both sides rather than sitting at a boundary. `gap_ms` stays 150 because its audible 530 ms already matches the commercial sentence pause of 480 ms. The chosen value lands on the commercial p90 (1030 ms) rather than its median (890 ms).

WHY THIS COMPARISON IS CLEANER THAN STAGES 0-2: all three arms are byte-identical speech with only inserted silence differing. There is NO stochastic confound at all, unlike every previous audition where S3Gen randomness meant part of any difference was luck. The seed-control arm that Stage 1 needed is unnecessary here by construction.

STILL NOT ESTABLISHED: one passage, one listener. The excerpt was deliberately dialogue-dense at 17.2 paragraph joins per minute, so the value is tuned on the case where the dial fires most often; narration-heavy stretches have far fewer paragraph breaks and the effect there is smaller. Whether 650 suits a different book or narrator is untested.

THE OPEN QUESTION IS STRUCTURAL. The commercial recording's distinguishing feature is a long-pause register we lack entirely, 6.1% of its gaps between 1200 and 4700 ms against our 0.1%. Round 2 shows that reaching those lengths with a UNIFORM gap is rejected, so the answer is not a bigger number, it is a different KIND of pause at the right places. Scene breaks should be detectable from the same page geometry `detect_paragraph_style` / `_modal_leading` already measure, at roughly 2.5x leading rather than the 1.5x that marks a paragraph, and an audition can inject them at assembly with no re-narration. `app/gap_audition.py` is the harness; it takes `--gaps a,b,c`, `--start-chunk` and `--num-chunks` so a prior excerpt can be reproduced exactly.


### Owner verdict and audition presentation preference (2026-09-13)

Owner listening supersedes automated acceptance. In the September 13 blind audition, A was explicit Chatterbox Multilingual V3, B original English Chatterbox, C VibeVoice Large/7B selective 8-bit. First-take ranking was B > A > C, but C Take 2 had highly preferred underlying delivery despite musical artifacts and slow pacing. M was VibeVoice independent chunks; N was the same configuration generating the whole dialogue in one call. N Take 2 was the owner's overall favorite; N Take 1 also sounded fantastic. Preserve VibeVoice whole-dialogue generation as the preferred investigation direction, not a production switch or book-length reliability claim.

J was original Chatterbox intact turn, K independent chunks, and L preceding-sentence regeneration plus trimming. J/K both sounded good; L was robotic with repeated phoneme tails. L FAILED OWNER LISTENING despite passing automated whole-word checks. The prior clean designation is superseded. The detailed verdict, timestamps and verified mapping are in ignored `Output/Narration_20260913/owner_verdict_20260913.md`; current operational authority remains `handoff.md`. No production change followed this verdict.

The owner explicitly invoked the i-have-adhd skill for future auditions: `C:/Users/paulm/.codex/plugins/cache/i-have-adhd/i-have-adhd/0.3.0/skills/i-have-adhd/SKILL.md`. Read the installed skill when applying it; search for its current path if the version changes. Apply its presentation rules. These audition-specific defaults are an operational interpretation, not verbatim skill requirements:

1. Present one listening question per round with two or three short, directly playable clips. Keep the first listening action obvious.
2. Put the same short passage in each clip and state the exact measured listening time. State one thing to judge, such as pronunciation, musical artifacts, pacing or continuity.
3. Keep blind labels stable within a round. State what the labels refer to without revealing candidate identities. Reveal identities after the owner ranks that round.
4. Request one simple response, such as A, B or neither, plus an optional timestamp. Keep visible choices small; do not start with a large folder, mixed test families or a long matrix of repeats.
5. Retain all repeats and diagnostics internally and make them available when needed. Use a second take or another passage in the next round to test reproducibility. This limits presentation burden, not experiment completeness.

No further listening is required merely to acknowledge or save this preference.

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
