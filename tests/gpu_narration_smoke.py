"""Explicit CUDA safety check; run in the Chatterbox environment with a local voice.

Not part of unittest discovery. Uses synthetic text and does not write audio.
"""
import argparse
import faulthandler
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", required=True)
    args = parser.parse_args()
    faulthandler.dump_traceback_later(300, exit=True)
    import torch
    import narrate_worker as worker
    import batched_narrate as batch
    from gpu_oom import bisect_cuda_oom, configure_memory_limit

    configure_memory_limit(torch)
    total = torch.cuda.mem_get_info()[1]
    # The 4090 test deliberately emulates a restricted allocator. This is
    # not evidence of throughput or driver behavior on a physical 6 GB card.
    limit = min(6 * 1024**3, int(total * 0.65))
    torch.cuda.set_per_process_memory_fraction(limit / total)
    model = worker.ChatterboxTTS.from_pretrained(device="cuda")
    model.prepare_conditionals(args.reference)
    blocks = [{"type": "body", "text": "The lantern shone beside the quiet garden."}] * 12
    plan = worker.build_plan(blocks, worker.PAUSE_PROFILES["A"])
    tokens = [(i, batch.tokenize_chunk(model, row["text"]).cpu()) for i, row in enumerate(plan)]
    buckets = worker._make_buckets(tokens, worker.BATCH_SIZE, worker.BATCH_TOKEN_BUDGET)
    assert len(buckets) == 1 and len(buckets[0]) == 12
    splits = []

    def force_long_decode(items):
        return batch.batched_generate(model, [token for _, token in items], model.conds,
            forced_ids=[[100] * batch.MAX_NEW_TOKENS for _ in items])

    def on_split(failed, left, right, exc):
        splits.append([failed, left, right])
        print(json.dumps({"oom_split": splits[-1]}), flush=True)

    started = time.monotonic()
    torch.cuda.reset_peak_memory_stats()
    sequences = bisect_cuda_oom(buckets[0], force_long_decode, torch, on_split)
    assert splits, "Stress case did not exercise a real allocator OOM"
    assert len(sequences) == 12
    assert all(seq == [100] * batch.MAX_NEW_TOKENS for seq in sequences)
    assert torch.cuda.max_memory_reserved() <= limit
    print(json.dumps({"forced_decode_seconds": time.monotonic() - started,
        "peak_reserved_gib": torch.cuda.max_memory_reserved()/1024**3,
        "splits": splits, "capped_rows_not_vocoded": len(sequences)}), flush=True)

    # Verify the same CUDA context is usable after the forced failures.
    torch.manual_seed(1234)
    normal = worker._oom_bisect_generate(model, model.conds, buckets[0], 0)
    assert all(0 < len(seq) < batch.MAX_NEW_TOKENS for seq in normal)
    wavs = worker._oom_bisect_vocode(model, model.conds, normal, True, 0)
    import numpy as np
    assert len(wavs) == len(normal)
    assert all(wav is not None and len(wav) > 0 and np.isfinite(wav).all()
               and np.max(np.abs(wav)) > 0.001 for wav in wavs)
    print(json.dumps({"normal_audio_rows": len(wavs), "status": "PASS"}), flush=True)
    faulthandler.cancel_dump_traceback_later()


if __name__ == "__main__":
    main()
