# Audiobook Studio 1.0.7 source candidate

1.0.7 is a source candidate. No 1.0.7 installer, patch, tag, or public release has been built or published. The 1.0.6 installer artifacts remain current.

Selecting a voice file now imports it immediately. Creating an audiobook shows the new job at the top of the main window. Additional books enter a durable first-in, first-out queue and start after earlier work finishes; required visual decisions and final-preview approval still pause their own jobs.

Right-click or the visible More actions button opens playback, artwork, export, details/log, regeneration, and deletion controls. Artwork changes update the library cover and embedded cover in owned M4B/MP3 files while preserving audio and chapters. WAV files retain their audio and use the library cover. Deletion lets the user remove the library entry or also remove generated audio/checkpoints; source PDFs and saved voices remain. Regeneration creates a separate job with the selected model and requires a fresh preview. Collapsed Advanced options include supported pause/model/performance settings, a Modified indicator, and Restore recommended defaults.

The recovered Annihilation run completed from story-PDF pages 6 through 98. It was recovered rather than uninterrupted: 5:32:09 active time and 14:38:45 wall time produced 4:26:56.75 of finished audio. This is completion evidence, not a performance comparison.

Automatic performance now renders one bounded batch from the next passage while the CPU checks the current passage. Provisional audio still passes the same unit and parent quality gates before becoming a checkpoint; cancellation, retry limits, and accepted audio reuse remain enforced. Conservative performance disables this overlap and uses serial generation.

A controlled RTX 4090 comparison used four authored short passages, fixed seeds, unchanged quality checks, and off/on/on/off ordering. The two baseline runs took 92.48 and 92.89 seconds; overlap took 73.13 and 71.67 seconds: 21.9% less elapsed time on this sample. All four runs produced identical WAV hashes, with the same 5.56 GiB peak Torch reservation. This is not a whole-book speed guarantee. Native batches remain at two on the tested 24 GB class and one on smaller cards; physical 12 GB and 16 GB performance remains untested.

The CPU-thread check retained four threads: four threads took 148.93 seconds, eight took 171.36 seconds, and twelve took 149.83 seconds. Each setting ran six checks and all 18 transcript hashes matched by input clip. More threads did not improve this sample.

Verification passed: 291 source tests (47 runtime-dependent skips), plus all 100 focused VibeVoice and assembly tests in the isolated runtime with no skips. Python and embedded JavaScript syntax checks passed. Graft reparsed all 80 eligible Python files and its wiring check passed; HTML and installer scripts remain outside that graph.

Two fresh synthetic PDFs completed through the normal app controls, GPU narration, CPU checks, assembly, and owned library publication. The second job was queued while the first ran and began narration 0.063 seconds after the first finished. Both outputs decoded without errors and passed cache-only validation with model/ASR loading forbidden. Regeneration with a different model created a separate job and stopped for the required preview. Browser checks covered immediate voice import, new-job placement, right-click/keyboard actions, artwork, export, and restoring advanced defaults. Independent source and privacy audits passed. These checks do not certify a new installer; build and handoff validation remain governed by `RELEASE_CHECKLIST.md`.
