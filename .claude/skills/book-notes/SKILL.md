---
name: book-notes
description: Per-book conversion records and page ranges for the Dungeon Master's Guide 2024, Return of the Lazy Dungeon Master, The Odyssey, Project Hail Mary, The Power of the Dog and The Shining, plus the Shining edition analysis (two different PDFs, chapter-mark behaviour). Load before creating or resuming a job for a specific book.
---

Migrated out of CLAUDE.md on 2026-08-04. Nothing was edited.
<!-- CLAUDE.md lines 333-340 -->
## Book-specific notes

- Dungeon Master's Guide 2024 (source_pdfs): 382 pages, Path B (two-column rulebook, text layer present but unusable by Path A). Structure: p1-5 front matter, Ch1 p6-21, Ch2 p22-51, Ch3 p52-105, Ch4 p106-127, Ch5 p128-173, Ch6 p174-213, Ch7 Treasure p214-333, Ch8 Bastions p334-354, Appendix A Lore Glossary p355-365, Appendix B Maps p366-380 (pure artwork, always exclude). COMPLETE 2026-07-26 for CHAPTERS 1-6 ONLY, pages 6 to 213: 11.55 hours, 5 chapter marks (Chapter 4's is missing, see above), cover art and tags, at audiobooks\Dungeon Masters Guide 2024 - Chapters 1 to 6\. 3961 blocks, 4413 chunks, 677k narratable chars; OCR ~5.5s/page warm, narration ~68 min. Chapter 7 was deliberately EXCLUDED: 120 pages of magic item entries and item tables, which is a third of the book and reads as a catalog rather than something to listen to. Ch7 and Ch8 remain available as a separate reference volume if ever wanted.
- Return of the Lazy Dungeon Master (samples\L_D_M): 88 pages, Path B. COMPLETE 2026-07-21: 3.62 hours, single file at audiobooks\Return of the Lazy Dungeon Master\. ffmpeg (chocolatey) is available on this machine for lossless concat / future m4b/mp3 encoding.
- The Odyssey (samples\The Odyssey): 793 pages, Path A verse. The poem is pages 78 to 610; pages 1-77 are front matter and 611+ are notes/commentary, so create the job with that range. COMPLETE 2026-07-26: 12.44 hours, 24 chapters (Book 1..Book 24), cover art and tags, single m4b at audiobooks\The Odyssey\. Narration took 66.7 min for 12.44 h of audio, about 11x realtime, versus ~6x for Power of the Dog: verse suits the batched engine because short uniform chunks fill every bucket to the BATCH_SIZE=12 row cap. Extraction was instant (0.5s, text layer) and the run was clean, 4539 rows with zero runaway rows, zero empty rows and zero serial fallbacks. One cosmetic wart: the artist tag reads "Homer, Daniel Mendelsohn, Daniel Mendelsohn" because that duplication is in the PDF's own metadata.
- PHM (samples\Novel sample): 523 pages, Path A prose, was the checkpoint 1 test book.
- The Power of the Dog - Don Winslow (source_pdfs): 818 pages, Path A prose. Novel proper is pages 5 to 818 (p1 cover, p2 title/dedication, p3 synopsis blurb, p4 Psalm epigraph, p5 Prologue, THE END on p818). User chose to start at the Prologue (page 5). 16 chapters (Prologue, Chapter One..Fourteen, Epilogue). Chapter headings are spelled-out ("Chapter One"), which is why HEADING_LINE_RE had to grow spelled-out-number support. COMPLETE: fully converted with cover art and metadata at audiobooks\The Power of the Dog\. It was the first full book done on the batched engine (2026-07-24, 3556 chunks, roughly 3.1 h of compute against the parallel engine's measured 6.26 h). Both jobs' segment data is kept.


<!-- CLAUDE.md lines 570-592 (The Shining edition analysis) -->
### The Shining: different typesetting, DIFFERENT EDITION, and it undercuts the boundary theory (2026-08-03)

The owner uploaded a Shining PDF to `source_pdfs`, which made the previous section's "reasonable hypothesis" testable. It is wrong, twice over.

(V) IT DOES NOT SHARE POWER OF THE DOG'S TYPESETTING. 31.45% of its lines are indented and its line-gap histogram is unimodal at 18 pt (704 occurrences, with the next bucket at 10). The probe returns `style=indent`, and extraction over pages 13 to 513 is BYTE FOR BYTE IDENTICAL between HEAD and the working tree. The adaptive fix is a deliberate no-op here. So the paragraph root cause does NOT explain the Shining complaint.

(V) IT IS NOT THE EDITION THAT WAS NARRATED ON THE HP OMEN. This file is 520 pages with 71 outline entries, Part One on PDF page 13 and Chapter One on page 14, outline titles formatted `Chapter One: Job Interview`. The Omen job recorded earlier in this file had 63 outline entries, Part One on page 5, chapter 1 on page 7, chapter 58 on page 575, and titles formatted `1 - Job Interview`. Different book file, so nothing here retro-diagnoses that job.

(V) CONSEQUENTLY THE ZERO-CHAPTERS DEFECT DOES NOT REPRODUCE. This edition renders its chapter openers as `CHAPTER ONE` and `JOB INTERVIEW` in caps at 21.2 and 16.9 pt, both of which survive extraction intact. Pages 13 to 513 give 5,058 blocks, 4,953 body, 105 headings and 65 `CHAPTER_RE` marks: `PART ONE`, `CHAPTER ONE` through `CHAPTER FIFTY-EIGHT`, `EPILOGUE / SUMMER`. Re-running The Shining from THIS PDF should produce a properly navigable m4b with no code change. The old job's missing marks were an edition property, not a pipeline defect.

One wart before creating that job: the 65 includes a trailing `CHAPTER ONE` AFTER the epilogue, almost certainly a preview excerpt of another novel in the back matter. The 13 to 513 range was inferred from the outline, not validated. Pin the real end page first.

THE UNCOMFORTABLE PART, and it is the reason Stage 2 was designed the way it was. The Shining is a book the owner HEARD and called phony, and its chunk profile is already close to what the fix achieves for Power of the Dog:

| | Shining (heard) | PotD old (heard-equivalent) | PotD new (the fix) |
|---|---|---|---|
| one speaker per call | 51.3% | 0.7% | 56.2% |
| split turns | 8.9% | 22.9% | 2.4% |
| chunks under 30 chars | 15.9% | 1.6% | 26.1% |
| median chunk | 113 | 341 | 59 |

So a book that ALREADY had good boundaries still drew the complaint. That does not make the extraction fix wrong; Power of the Dog was genuinely discarding 92.5% of its paragraphs and its split-turn rate was 22.9%. But it does mean correct boundaries are a PREREQUISITE rather than a cure, and it is why Stage 2 tested the delivery parameters in the same run instead of boundaries alone.

