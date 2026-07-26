"""
Pre-fetch Chatterbox's TTS weights during install, instead of letting the
first narration hit a silent ~3 GB download with no progress bar.

Deliberately does NOT run any model inference or touch CUDA. It only calls
hf_hub_download() for the exact five files ChatterboxTTS.from_pretrained()
loads (confirmed by reading chatterbox/tts.py 0.1.7):

    ve.safetensors, t3_cfg.safetensors, s3gen.safetensors,
    tokenizer.json, conds.pt

repo_id is ResembleAI/chatterbox. Because this is a plain HTTP download via
huggingface_hub (already a pinned dependency of chatterbox-tts, see
install/requirements-chatterbox.txt), it can run right after the chatterbox
conda env is created and before verify() -- so if something is going to go
wrong on this machine, it fails on "download some files", not on "the
first time you actually try to narrate a book", which is a much worse
place to debug a stranger's machine.

Uses the same HF cache torch/transformers/chatterbox will look in later
(the default ~/.cache/huggingface, or HF_HOME if set), so the later
from_pretrained() call is a cache hit, not a second download.

Must be run with the chatterbox env's python (it's the one with
huggingface_hub installed at the pinned version); setup.py invokes this via
`conda run -n chatterbox python bootstrap_weights.py`.
"""
import sys

REPO_ID = "ResembleAI/chatterbox"
FILES = ["ve.safetensors", "t3_cfg.safetensors", "s3gen.safetensors", "tokenizer.json", "conds.pt"]


def main():
    try:
        from huggingface_hub import hf_hub_download
    except ImportError:
        print("  [FAIL] huggingface_hub not importable in this env; run this inside the "
              "chatterbox conda env (it's a pinned dependency of chatterbox-tts).")
        return 1

    print(f"  Pre-fetching {REPO_ID} weights (~3 GB total, one-time)...")
    for fname in FILES:
        try:
            path = hf_hub_download(repo_id=REPO_ID, filename=fname)
            print(f"  [ OK ] {fname} -> {path}")
        except Exception as e:
            print(f"  [FAIL] {fname}: {e}")
            return 1

    print("  [ OK ] All Chatterbox weights cached. First narration will not need to download them.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
