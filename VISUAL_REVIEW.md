# Visual review before narration

Storybird preserves visual passages for an explicit editorial decision. This replaces the
blanket table and data omission policy, as authorized by the owner on 2026-09-12.

## Review workflow

Extraction flags tables, structured log fragments, codes, visual indications and detectable
PDF graphics. A job with flagged passages waits in `review_required`, releasing the worker
queue so other jobs can continue. No TTS worker is launched while required choices remain
unresolved. Prose-only jobs continue through the existing sequential pipeline.

Open **Review narration text** on an idle job. Each passage shows its original extraction,
nearby prose, source page when known, and an original PDF preview when available. The page
renderer runs on the CPU. Missing source graphics are explicitly labelled unavailable.

Treatments are:

* **Keep as spoken text:** preserve the displayed source text exactly. This is read-only;
  use a description to remove formatting or irrelevant codes.
* **Replace with a spoken description:** write and save an editable adaptation. The exact
  proposed speech is displayed as it is edited.
* **Skip: surrounding prose conveys it:** no speech is inserted at that position. Confirm
  the author already conveys the visual's contribution.

Descriptions are manual. The default suggestion asks the reviewer to describe uncertain
material; Storybird does not invent an automatic summary, infer missing graphic details, or
decide that nearby dialogue is sufficient. Preserve story-critical numbers, changes,
warnings and discovery order. Iteration headings and quotations remain source text.

Save every treatment, open **Inspect final narration text**, then select **Start narration**.
An edit makes a prior preview obsolete. The server also enforces these gates on direct
narration and resume paths. Saved choices are available after closing or restarting the app.

## Source, decisions and existing work

All files below live in the ignored job folder, never in distributed application files:

* `source_blocks.json`: preserved extraction used by the review.
* `visual_review.json`: explicit decisions and descriptions, matched to source fingerprints.
* `blocks.json`: narration projection derived from source and saved decisions.
* `legacy_blocks.json`: exact extraction saved before migrating an older job.
* `pages/page_####.md`: original cached OCR, when available.
* `output_history/`: prior finished audio preserved before explicit regeneration.

Legacy migration recovers source from available extraction evidence without deleting the
job. Complete cached OCR page ranges can be retagged without another OCR run. Missing or
partial source is handled conservatively; an old omission announcement cannot reconstruct
the table it replaced. Unavailable evidence needs manual review.

Spoken text and type changes use the existing segment-plan identity rules. The current cache
supports whole-plan invalidation, not selective reuse after changed chunk indices. Identical
spoken projections preserve valid segments; provenance and assembly-only metadata remain
outside that identity. Stale finished audio is withheld from current playback/download
controls until regeneration succeeds. Earlier audio is preserved separately.

Source and decision corruption fails closed rather than silently discarding review state.
Review editing and queue transitions are serialized. Review does not introduce GPU processing;
OCR and TTS remain sequential and their environments remain isolated.

## Verification and limits

The full native Windows test suite passed: **136 tests, zero skips or failures**. The
focused visual-review integration suite passed all 25 tests. Python compilation, embedded
JavaScript syntax checks and Git diff checks passed. Graft reparsed all 54 indexed files
and reported the graph in sync.

Synthetic regression coverage includes fragmented tables, standalone codes, numerical
changes, dialogue around charts, missing visuals, source boundaries, persistence, HTTP
review/start transitions, pre-worker gating, legacy migration, prior-audio preservation and
segment-cache invalidation. The production narration planner is checked separately from
extraction using synthetic speech text and dependency stubs, without loading a TTS model.

An isolated localhost instance exercised the actual interface with synthetic data: PDF
preview, editable numerical description, chart skip, warning kept as text, saved choices
after reload and a server restart, exact full-text preview, disabled/enabled Start, and
keyboard queueing. Light and dark themes were inspected, and a 390-pixel viewport had no
horizontal overflow. A real synthetic PDF also verified text, table and image ordering.
This is source-app verification, not an
installed-build or audio-quality certification.

The reference Markdown was inspected read-only. Its 37-line log probe initially produced
seven table omissions, five headings and five body blocks. The new detector preserves that
continuous log as one visual passage. The full Markdown has no Markdown image links or HTML
image tags; missing original graphics cannot be reconstructed from it. No purchased text
or derived audio was added to tests or tracked artifacts.

Detection is conservative and heuristic. A text conversion with no surviving visual signal
cannot reveal a vanished chart, and ambiguous decorative graphics may require a skip decision.
Reviewers must use the original PDF where available. A skipped graphic can leave a paragraph
boundary in place; source order is preserved rather than joining prose across an undecided
visual. No installers, uploads or releases were produced for this change.
