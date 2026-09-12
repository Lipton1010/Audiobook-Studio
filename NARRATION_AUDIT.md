# Narration reliability and efficiency audit

2026-09-12. Scope: the reported narration stall, GPU memory, progress estimates, recovery,
and update-package completeness. This is a focused audit, not an exhaustive repo review.

## Findings and implemented changes

1. **Input batching did not bound output memory.** Short text can still generate a long
   speech sequence; rows multiplied by input tokens does not cap the growing decoder cache.
   The stalled run reached about 22.36 GiB dedicated plus 3.86 GiB shared GPU memory.
   Workers now set a PyTorch allocator limit before loading models: at most 80% of total
   VRAM, also constrained by initially free VRAM minus the greater of 1 GiB or 15% of total.
   Parallel workers divide this allowance. Existing ordered bisection retries oversized
   T3 and S3Gen batches. Ordinary bucket sizes and inference math are unchanged.

2. **A stalled batch left a believable but stale ETA indefinitely.** The server now hides
   the estimate after 120 seconds without a bucket progress update and stops the owned
   worker after 300 seconds, preserving completed segments for resume. New log entries
   distinguish token generation from conversion to audio. Model loading before the first
   progress record is deliberately outside this batch timeout.

3. **Tiny headings gave unrepresentative ETA samples.** The estimator now waits until the
   median remaining input length is within twice the largest observed length, in addition
   to the existing 20-bucket minimum. It can show no estimate for longer at startup; this
   is preferable to extrapolating a whole book from a few tiny headings. It remains an
   estimate: voice, generated length, retries, and GPU contention affect actual runtime.

4. **The earlier patch omitted current code dependencies.** Version 1.0.3 explicitly
   ships the batched engine, capped-sequence safety, assembly metadata, extraction helper,
   and voice converter along with the previous patch files. An AST-based regression test
   checks local import closure. This repairs the identified packaging omission, but does
   not establish that every pre-existing installation or runtime issue is repaired.

5. **Assembly-only resumes needlessly loaded the narration model.** A worker with no
   missing segments now returns before model loading or allocating GPU memory.

## Evidence

The real job was canceled at the user's request after 336 of 5676 segments. Completed
segments were retained and GPU allocation fell to about 1.2 GB. Retrying the first
unfinished bucket with a fixed seed took 4.078 seconds and peaked at 4.916 GiB reserved.
The original stochastic trigger and exact stalled stage therefore remain unconfirmed.

Five real production-plan buckets were then exercised sequentially on the RTX 4090 with
a deliberately restricted 6 GiB allocator. No purchased text or audio is stored here.

| Bucket | Rows | Maximum input tokens | Total seconds | Peak reserved GiB | Recovery observed |
| --- | ---: | ---: | ---: | ---: | --- |
| 29 | 12 | 13 | 4.141 | 4.916 | None |
| 100 | 12 | 23 | 15.047 | 6.000 | T3: 12 into 6 + 6 |
| 300 | 12 | 91 | 7.468 | 5.758 | None |
| 500 | 5 | 220 | 14.610 | 5.877 | S3Gen: 5 into 2 + 3 |
| 593 | 4 | 299 | 58.390 | 5.998 | T3 and S3Gen: 4 into 2 + 2 |

The committed synthetic CUDA harness, `tests/gpu_narration_smoke.py`, forced all 12 rows
to run for 1000 generated tokens. Real allocator OOM split 12 into 6 + 6 and each 6 into
3 + 3. Decode completed in 127.36 seconds with peak reserved memory of 6.000 GiB.
All rows were returned intact; capped rows were not vocoded. The same CUDA context then
generated and vocoded 12 normal, finite, nonempty, non-silent segments. The test passed.
This is numerical output validation, not a listening-quality assessment.

All 66 dependency-free unit tests pass, including stale ETA, ordered OOM recovery,
process ownership, segment preservation, memory budgets, and patch import completeness.
Changed Python files compile and `git diff --check` passes.

The allocator behavior is documented in
[PyTorch's memory-fraction API](https://docs.pytorch.org/docs/main/generated/torch.cuda.memory.set_per_process_memory_fraction.html).
It limits PyTorch-managed allocations, not every driver's allocation. Initial headroom
cannot guarantee against another application consuming VRAM later.

## Next validation priorities

1. Apply the exact patch to a real older install, starting with a short synthetic or
   properly licensed narration. Check launch, audio download, beta reports, and retained
   user data. Test Brandon's physical 16 GB card rather than treating an allocator cap
   on a 24 GB card as equivalent hardware.
2. Complete an installed-build book run while recording dedicated/shared GPU memory and
   per-bucket timing. Check several voices and listen to output before making reliability,
   quality, or throughput claims. The canceled full job has not been resumed by this audit.
3. Satisfy the remaining exact-build gates in `RELEASE_CHECKLIST.md` before public release.
   Locally built installers are candidates, not certification that those gates passed.

Do not begin with a broad rewrite or more workers. Prior measurements already rejected
extra Windows CUDA processes, overlapping T3/S3Gen, and raising the token budget to 1800
as useful speedups here. If sustained throughput remains a problem after safety validation,
profile active-row decoder waste and long-tail buckets before proposing a narrowly tested
optimization. No universal speedup is claimed for this update.
