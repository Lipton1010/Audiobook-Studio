"""
Numerical equivalence self-tests for batched_narrate.batched_generate
(chatterbox env). No listening required: these catch masking / position /
double-BOS / CFG bugs by comparing against v1's real code.

Run in EAGER attention + fp32 so the only residual difference is float
reduction order (~1e-6); a difference that GROWS across decode steps is the
fingerprint of RoPE position drift (the #1 risk of this design).

TEST A  seeded token-equivalence: batched-of-1 vs the real model.t3.inference,
        same RNG seed -> speech-token sequences must match.
TEST B  padding isolation: a SHORT target row's teacher-forced post-CFG logits
        must be ~identical whether it runs alone (no pad) or in a batch with a
        LONGER chunk (target then carries text-pad + a cache_position vs
        position_ids divergence). Drift across steps = position bug.

Usage: python ab_selftest.py <ab_chunks.json> <ref_wav>
"""
import json
import sys
from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as F

import perth


class _NoWatermark:
    def apply_watermark(self, wav, sample_rate=None):
        return wav


perth.PerthImplicitWatermarker = _NoWatermark

from chatterbox.tts import ChatterboxTTS
import batched_narrate as B


def force_eager_fp32(model):
    # fp32 already per env check; force eager attention so sdpa/flash kernel
    # choice cannot inject ~1e-3 noise that masks/fakes a position bug.
    model.t3.tfmr.config._attn_implementation = "eager"


def v1_real_tokens(model, conds, text, seed, max_new_tokens=1000):
    """Exactly v1's generate() token path (tts.py:234-260), seeded, returning
    the raw speech-token list truncated at EOS (invalid tokens filtered)."""
    from chatterbox.tts import punc_norm

    text = punc_norm(text)
    tt = model.tokenizer.text_to_tokens(text).to(model.device)
    tt = torch.cat([tt, tt], dim=0)                        # CFG pair
    sot, eot = model.t3.hp.start_text_token, model.t3.hp.stop_text_token
    tt = F.pad(tt, (1, 0), value=sot)
    tt = F.pad(tt, (0, 1), value=eot)
    torch.manual_seed(seed)
    with torch.inference_mode():
        st = model.t3.inference(
            t3_cond=conds.t3, text_tokens=tt, max_new_tokens=max_new_tokens,
            temperature=0.8, cfg_weight=0.5, repetition_penalty=1.2, min_p=0.05, top_p=1.0,
        )
    row = st[0].tolist()
    out = []
    for tok in row:
        if tok == B.EOS:
            break
        out.append(tok)
    return out


def test_a(model, conds, chunks, seed=1234):
    print("\n===== TEST A: seeded token-equivalence (batched-of-1 vs v1 real) =====")
    ok = True
    for c in chunks:
        text = c["text"]
        v1 = v1_real_tokens(model, conds, text, seed)
        tok = B.tokenize_chunk(model, text)
        torch.manual_seed(seed)
        seqs = B.batched_generate(model, [tok], conds, cfg_weight=0.5, temperature=0.8,
                                  repetition_penalty=1.2, min_p=0.05, top_p=1.0)
        bt = seqs[0]
        n = min(len(v1), len(bt))
        first_div = next((i for i in range(n) if v1[i] != bt[i]), None)
        match = (len(v1) == len(bt)) and first_div is None
        status = "EXACT" if match else f"DIVERGES at {first_div} (v1 len {len(v1)}, batched len {len(bt)})"
        print(f"  [{c['index']:>4}] len={c['char_len']:>3}  v1_tok={len(v1):>4} batched_tok={len(bt):>4}  -> {status}")
        ok = ok and match
    print(f"TEST A: {'PASS' if ok else 'FAIL'}")
    return ok


def test_b(model, conds, short_c, long_c, k=32):
    print("\n===== TEST B: padding isolation (short target row, teacher-forced logits) =====")
    # Forced token sequences: get real tokens so the forced stream is plausible.
    tgt_tokens = v1_real_tokens(model, conds, short_c["text"], seed=7)[:k]
    if len(tgt_tokens) < k:
        k = len(tgt_tokens)
    dummy_forced = [100] * k  # any valid non-EOS speech token; target logits don't depend on it

    tgt = B.tokenize_chunk(model, short_c["text"])
    lng = B.tokenize_chunk(model, long_c["text"])
    assert lng.numel() > tgt.numel(), "long dummy must be longer than the target"

    # batched-of-1: target alone (no padding)
    _, tr1 = B.batched_generate(model, [tgt], conds, forced_ids=[tgt_tokens],
                                capture_logits=True, max_new_tokens=k)
    # batched-of-2: [target, longer dummy] -> target row gets right-pad + pos divergence
    _, tr2 = B.batched_generate(model, [tgt, lng], conds, forced_ids=[tgt_tokens, dummy_forced],
                                capture_logits=True, max_new_tokens=k)

    print(f"  target idx {short_c['index']} (len {short_c['char_len']}), pad-dummy idx {long_c['index']} "
          f"(len {long_c['char_len']}), delta_text_tokens={lng.numel()-tgt.numel()}, steps={len(tr1)}")
    print(f"  {'step':>4} {'max_abs_diff':>14} {'rel_to_scale':>12}")
    diffs = []
    for t in range(min(len(tr1), len(tr2))):
        a = tr1[t][0].float()
        b = tr2[t][0].float()
        d = (a - b).abs().max().item()
        scale = a.abs().max().item()
        diffs.append(d)
        if t in (0, 1, 2, 4, 8, 16) or t == min(len(tr1), len(tr2)) - 1:
            print(f"  {t:>4} {d:>14.3e} {d/max(scale,1e-9):>12.3e}")
    dmax = max(diffs)
    grew = diffs[-1] > 5 * (diffs[0] + 1e-9) and diffs[-1] > 1e-3
    print(f"  max diff over all steps: {dmax:.3e}; first={diffs[0]:.3e} last={diffs[-1]:.3e}")
    verdict = (dmax < 1e-3) and not grew
    print(f"TEST B: {'PASS' if verdict else 'FAIL'} "
          f"({'flat/tiny' if not grew else 'DRIFT GROWS -> position bug'})")
    return verdict


def main():
    chunks_json = Path(sys.argv[1])
    ref_wav = sys.argv[2]
    data = json.loads(chunks_json.read_text(encoding="utf-8"))
    body = [c for c in data["chunks"] if not c["is_heading"] and c["char_len"] > 40]

    print("loading model (fp32, forcing eager) ...", flush=True)
    model = ChatterboxTTS.from_pretrained(device="cuda")
    force_eager_fp32(model)
    print("t3 dtype:", next(model.t3.tfmr.parameters()).dtype,
          "attn:", model.t3.tfmr.config._attn_implementation, flush=True)
    model.prepare_conditionals(ref_wav)
    conds = model.conds

    # TEST A on 3 representative chunks (short, mid, long)
    body_sorted = sorted(body, key=lambda c: c["char_len"])
    a_chunks = [body_sorted[0], body_sorted[len(body_sorted) // 2], body_sorted[-1]]
    a_ok = test_a(model, conds, a_chunks)

    # TEST B: short target padded by a longer dummy
    short_c = body_sorted[1]
    long_c = body_sorted[-1]
    b_ok = test_b(model, conds, short_c, long_c)

    print(f"\n==== SELF-TEST {'PASS' if (a_ok and b_ok) else 'FAIL'} (A={a_ok}, B={b_ok}) ====")
    sys.exit(0 if (a_ok and b_ok) else 1)


if __name__ == "__main__":
    main()
