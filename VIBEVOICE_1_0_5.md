# Storybird 1.0.5 integration verification

VibeVoice 1.5B is the default for new audiobooks. Chatterbox remains selectable;
saved jobs without a backend retain Chatterbox and its existing cache semantics.
The owner preferred the 1.5B chapter audition and authorized this integration.

## Implemented

- Separate VibeVoice interpreter, model paths, planner, worker, checkpoints and receipts.
- Pinned 1.5B BF16, CFG 2, 20 diffusion steps and SDPA settings. Whole paragraphs
  are packed into bounded passages; the actual speaker parser must preserve every word.
- The selected reference is converted to mono 24 kHz locally. WAV reference
  conversion does not require ffmpeg.
- Gain-only adjustment targets -21 LUFS with peak headroom. Native timing remains intact.
- CPU speech recognition checks missing/extra wording, with bounded retries for
  rejected generation. Infrastructure failures stop immediately. Rejected takes remain local.
- Resume validates text, voice, runtime settings, local model layout and WAV hashes,
  plus mono/sample-rate/finite/non-silent audio checks.
- The visual-treatment and signed full-preview gates remain in the shared app path.
  OCR and TTS remain sequential; Windows Job Objects own worker descendants.
- Atomic M4B/MP3/WAV assembly, chapter marks, cover art, metadata and passage pauses.
  Large WAV output selects RF64 when necessary.
- Setup can provision owned, isolated runtimes or verify/register existing ones
  without changing their packages. No private machine paths are tracked defaults.

## Executed verification, 2026-09-14

Terra workers implemented the runtime and app integration. Sol independently
reviewed the changes, ran focused native tests and inspected actual output. The
orchestrator performed the final application and output checks.

- Two successful real HTTP/GPU smoke jobs: synthetic PDF extraction, two visual
  treatments, full-preview approval, two generated passages, CPU speech checks,
  M4B assembly and copy into the audiobook library.
- The final job used the production worker and existing isolated Python 3.11
  runtime. Both passage WAVs measured -21.000 LUFS; peak amplitudes were 0.7583
  and 0.7113. The text checker passed both passages.
- Actual subprocess resume with CUDA disabled preserved WAV hashes and did not
  load the model. A modified checkpoint failed validation.
- All three output formats passed ffprobe checks. M4B and MP3 retained the
  CHAPTER ONE marker and attached cover. Cancelled assembly left the completed
  output unchanged.
- Browser interaction confirmed VibeVoice selected by default, Chatterbox
  selectable, the voice selector and output choices present.
- Runtime modules compile with the actual Python 3.11 interpreter. Runtime-only
  voice-conversion and cached-resume tests pass in that environment; the base
  suite deliberately skips them when audio dependencies are absent.
- Native full-suite results and private synthetic fixtures are retained under
  ignored `Output/Integration_1_0_5/`. No book text, reference samples or generated
  audio are included in tracked source.

Execution caught and corrected a Python 3.11 f-string incompatibility, tokenizer
cache initialization, aggregate ASR coverage, and NumPy cached-progress JSON
serialization. These are covered by the executed checks and regression tests.

## Scope of verification

This verifies the source integration on the owner's RTX 4090 and existing
isolated runtimes. It does not certify every pronunciation or exclude every
audible artifact. A complete fresh-machine environment installation, smaller-GPU
behavior, and an installer/patch run have not been verified for 1.0.5.

The source verification above preceded packaging. On 2026-09-14 the owner
authorized a full installer and patch, with extensive final audit and exact-build
testing before Google Drive upload. Packaging evidence belongs to that separate
validation run; the public release checklist still applies.
