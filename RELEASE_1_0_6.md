# Audiobook Studio 1.0.6

1.0.6 packages the Storybird VibeVoice reliability and performance repairs. VibeVoice now keeps CPU quality verification isolated, preserves verified checkpoints, batches eligible repair units on supported hardware, and applies the same parent-level transcript gate before publishing audio.

The release also fixes ordinary unsigned whole-number notation in the quality checker, so equivalent forms such as `100` and `one hundred` do not consume retries. Numeric signs, decimals, fractions, leading-zero forms, and identifiers remain distinct.

Extraction now keeps ordinary prose beginning with a label-like word out of visual review, restores numbered uppercase chapter titles as spoken headings, and preserves the existing visual-review path for genuine captions and graphics. Narration progress reports rendering and quality phases so healthy retries do not trigger the aggregate watchdog. Owned CPU verifier descendants are terminated with their exact worker run during cancellation or failure.

The patch updates the VibeVoice worker, planner, unit, quality, audio, and assembly modules and provisions the existing private runtime. The full installer copies the complete tracked source tree. Both installers require the release commit to contain every module before the canonical `git archive HEAD` build.

Build and handoff validation remain governed by `RELEASE_CHECKLIST.md`; this source note does not certify an installer artifact.
