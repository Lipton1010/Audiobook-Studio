"""
Batched T3 generation for Chatterbox (chatterbox env). Generates N text
chunks that share ONE voice in a single forward-pass batch through the T3
token model, for a real speedup over the one-at-a-time v1 path, while
reproducing v1's per-sequence math so the audio is perceptually identical.

Design (verified by a design panel + adversarial review):
- RIGHT-pad text; per row the layout is
      [ cond(C) | real_text(T_j) | text_pad(T_max-T_j) | BOS | BOS ]
  so real text tokens sit at the front (learned text pos-emb = emb(0..T_j-1),
  byte-identical to v1) and the two BOS sit at a shared physical frontier.
- CFG as a 2N-row batch, block-ordered: rows [0:N] conditional, [N:2N]
  unconditional (text tokens zeroed, positions kept), matching v1's cat of
  [cond, uncond] widened from 1 sequence to N.
- position_ids = cumsum(attention_mask)-1, passed EXPLICITLY every forward and
  kept distinct from cache_position; the pad columns add 0 to the cumsum so the
  BOS positions close the gap and every real row's RoPE spacing equals v1's.
- Call the LlamaModel (t3.tfmr) directly; T3HuggingfaceBackend drops the mask
  and positions. The installed chatterbox package is NOT modified.
- Per-row EOS; finished rows are frozen to a safe one-hot before multinomial so
  one degenerate row can never abort the batch. S3Gen runs unbatched per row on
  v1's exact code path.

KNOWN TRADE-OFF (perf, not correctness): the batch runs until EVERY row hits EOS
(or max_new_tokens), so a bucket's wall-clock is set by its slowest row, and one
chunk that never emits EOS makes the whole bucket run the full 1000 steps at 2N
rows. Output stays correct (finished rows are frozen and truncated at their own
EOS); only throughput suffers. Shrinking the batch mid-run would require
re-indexing the DynamicCache, so the mitigation is length-bucketing (group
similar-length chunks) plus modest bucket sizes.

This module only reaches into an already-loaded ChatterboxTTS instance's
submodules; it imports no model weights of its own.
"""
import torch
import torch.nn.functional as F
from torch.nn.functional import softmax
from transformers.generation.logits_process import (
    RepetitionPenaltyLogitsProcessor,
    MinPLogitsWarper,
    TopPLogitsWarper,
)

try:
    from transformers import DynamicCache
except Exception:  # pragma: no cover - version fallback
    from transformers.cache_utils import DynamicCache

from chatterbox.models.s3tokenizer import drop_invalid_tokens

BOS = 6561  # start_speech_token
EOS = 6562  # stop_speech_token
SPEECH_VOCAB_LIMIT = 6561  # keep tokens strictly below this (drops start/stop), tts.py:262


def tokenize_chunk(model, text):
    """v1's exact text prep (tts.py:234-243): punc_norm -> tokens -> SOT/EOT.
    Returns a 1D LongTensor [SOT, ...tokens..., EOT] on the model device."""
    from chatterbox.tts import punc_norm

    text = punc_norm(text)
    toks = model.tokenizer.text_to_tokens(text).to(model.device)  # (1, L)
    sot = model.t3.hp.start_text_token
    eot = model.t3.hp.stop_text_token
    toks = F.pad(toks, (1, 0), value=sot)
    toks = F.pad(toks, (0, 1), value=eot)
    return toks.squeeze(0)  # (L+2,)


@torch.inference_mode()
def batched_generate(
    model,
    chunk_tok_list,           # list of 1D LongTensors (each [SOT..EOT]) sharing one voice
    conds,                    # Conditionals for that voice (model.conds after prepare_conditionals)
    *,
    cfg_weight=0.5,
    temperature=0.8,
    repetition_penalty=1.2,
    min_p=0.05,
    top_p=1.0,
    max_new_tokens=1000,
    forced_ids=None,          # test hook: list[N] of list[int]; force these tokens instead of sampling
    capture_logits=False,     # test hook: also return per-step post-CFG combined logits (N,V)
):
    """Returns list of speech-token lists (one per chunk). With capture_logits,
    returns (seqs, logits_trace) where logits_trace[t] is the (N,V) post-CFG
    combined logits at step t (step -1 = prefill frontier)."""
    t3 = model.t3
    dev = model.device
    N = len(chunk_tok_list)

    # ---- once per voice ----
    cond1 = t3.prepare_conditioning(conds.t3)              # (1, C, dim)
    C = cond1.size(1)
    dim = cond1.size(-1)
    bos_vec = t3.speech_emb(torch.tensor([[BOS]], device=dev)) \
        + t3.speech_pos_emb.get_fixed_embedding(0)         # (1, 1, dim), speech pos 0

    # ---- right-pad text ----
    lens = [int(t.numel()) for t in chunk_tok_list]
    Tmax = max(lens)
    txt = torch.full((N, Tmax), t3.hp.stop_text_token, dtype=torch.long, device=dev)
    for j, t in enumerate(chunk_tok_list):
        txt[j, :lens[j]] = t.to(dev)

    # ---- 2N embeds, CFG block-ordered ----
    text_pos = t3.text_pos_emb(txt)                        # (Tmax, dim) learned positions 0..Tmax-1
    te_cond = t3.text_emb(txt) + text_pos                  # (N, Tmax, dim) real front tokens -> emb(0..T_j-1)
    te_unc = text_pos.unsqueeze(0).expand(N, Tmax, dim)    # uncond: tokens zeroed, positions kept (t3.py:114-119)
    condC = cond1.expand(N, C, dim)
    bos2 = bos_vec.expand(N, 2, dim)                       # TWO BOS, both at speech pos 0
    pre_c = torch.cat([condC, te_cond, bos2], dim=1)       # (N, P, dim)
    pre_u = torch.cat([condC, te_unc, bos2], dim=1)
    embeds = torch.cat([pre_c, pre_u], dim=0).contiguous() # (2N, P, dim)
    P = C + Tmax + 2

    # ---- mask + positions ----
    baseN = torch.zeros(N, P, dtype=torch.long, device=dev)
    for j in range(N):
        baseN[j, :C + lens[j]] = 1                         # cond + real text
        baseN[j, C + Tmax:C + Tmax + 2] = 1                # the two trailing BOS
    prefill_mask = torch.cat([baseN, baseN], dim=0)       # (2N, P)
    pos = prefill_mask.cumsum(-1) - 1
    pos = pos.masked_fill(prefill_mask == 0, 0)
    cpos = torch.arange(P, device=dev)

    # Preallocate the full-length key mask once instead of torch.cat-ing a
    # growing tensor every step (that was O(steps^2) in both alloc and the
    # cumsum used to read the last position).
    full_mask = torch.zeros(2 * N, P + max_new_tokens, dtype=torch.long, device=dev)
    full_mask[:, :P] = prefill_mask
    # Real (attended) prefill tokens per row = C + T_j + 2, which is exactly the
    # position the FIRST generated token must take; step t then sits at base+t.
    base_real = prefill_mask.sum(-1, keepdim=True)        # (2N, 1)

    # ---- prefill ----
    o = t3.tfmr(
        inputs_embeds=embeds, attention_mask=prefill_mask, position_ids=pos,
        past_key_values=DynamicCache(), cache_position=cpos,
        use_cache=True, return_dict=True,
    )
    frontier = o.last_hidden_state[:, -1, :]
    assert not torch.isnan(frontier).any(), "NaN in prefill frontier hidden state"
    logits = t3.speech_head(frontier)                      # (2N, V)
    past = o.past_key_values

    # ---- decode ----
    gen = torch.full((N, 1), BOS, dtype=torch.long, device=dev)   # rep-penalty history seed (single BOS)
    finished = [False] * N
    seqs = [[] for _ in range(N)]
    rep = RepetitionPenaltyLogitsProcessor(float(repetition_penalty))
    mpw = MinPLogitsWarper(min_p)
    tpw = TopPLogitsWarper(top_p)
    logits_trace = []

    for t in range(max_new_tokens):
        c = logits[:N]
        u = logits[N:]
        L = c + cfg_weight * (c - u)                       # (N, V) post-CFG combined
        if capture_logits:
            logits_trace.append(L.detach().clone())

        Lp = rep(gen, L)
        if temperature != 1.0:
            Lp = Lp / temperature
        Lp = mpw(gen, Lp)
        Lp = tpw(gen, Lp)

        # Freeze finished rows to a safe one-hot so a degenerate distribution can
        # never raise 'invalid multinomial distribution' and abort the batch.
        for j in range(N):
            if finished[j]:
                Lp[j] = float("-inf")
                Lp[j, 0] = 0.0

        nxt = torch.multinomial(softmax(Lp, dim=-1), num_samples=1)   # (N, 1)

        if forced_ids is not None:
            for j in range(N):
                if forced_ids[j] is not None and t < len(forced_ids[j]):
                    nxt[j, 0] = forced_ids[j][t]

        gen = torch.cat([gen, nxt], dim=1)
        for j in range(N):
            if not finished[j]:
                tj = int(nxt[j, 0])
                if tj == EOS:
                    finished[j] = True
                else:
                    seqs[j].append(tj)
        if all(finished):
            break

        emb = t3.speech_emb(nxt) + t3.speech_pos_emb.get_fixed_embedding(t + 1)  # (N,1,dim)
        emb2 = torch.cat([emb, emb], dim=0)                # (2N, 1, dim)
        full_mask[:, P + t] = 1                            # the new speech token is always attended
        npos = base_real + t                               # (2N, 1) -> C+T_j+2+t per row
        o = t3.tfmr(
            inputs_embeds=emb2, attention_mask=full_mask[:, :P + t + 1], position_ids=npos,
            past_key_values=past, cache_position=torch.tensor([P + t], device=dev),
            use_cache=True, return_dict=True,
        )
        past = o.past_key_values
        logits = t3.speech_head(o.last_hidden_state[:, -1, :])

    # Release the batched kv-cache before the caller vocodes. Measured: without
    # this the reserved pool climbs across buckets and pushes S3Gen onto
    # PyTorch's cudaFree-and-retry path (one 728-token chunk took 95s instead
    # of 0.87s). Freeing here keeps reserved flat (~5 GB) and S3Gen fast.
    del past, o, logits, embeds, full_mask, prefill_mask
    torch.cuda.empty_cache()

    if capture_logits:
        return seqs, logits_trace
    return seqs


@torch.inference_mode()
def seqs_to_wavs(model, conds, seqs):
    """Vocode each row's speech tokens unbatched on v1's exact path (tts.py:260-269)."""
    dev = model.device
    wavs = []
    for st_list in seqs:
        if len(st_list) == 0:
            wavs.append(None)
            continue
        st = torch.tensor(st_list, dtype=torch.long, device=dev)
        st = drop_invalid_tokens(st)                       # 1D, matches v1 exactly
        st = st[st < SPEECH_VOCAB_LIMIT].to(dev)
        wav, _ = model.s3gen.inference(speech_tokens=st, ref_dict=conds.gen)
        wav = wav.squeeze(0).detach().cpu().numpy()
        # Route through the SAME watermarker v1 uses (tts.py:271). On this stack
        # it is stubbed to a no-op, so this is currently identity; keeping the
        # call means the two engines stay identical if watermarking is restored.
        wav = model.watermarker.apply_watermark(wav, sample_rate=model.sr)
        wavs.append(wav)
    return wavs
