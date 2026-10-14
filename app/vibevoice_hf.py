"""Pinned Transformers VibeVoice inference with compiled static-cache decoding."""

TRANSFORMERS_VERSION = "5.19.0"  # Includes upstream TTS batch-row fix #48902 (2026-09-21).
MODEL_ID = "vibevoice/VibeVoice-1.5B-hf"
MODEL_REVISION = "d4cd82eb4371bf3e3d088e1ea7fa4eefb60449bf"


def load(torch, config):
    import transformers
    from transformers import AutoModelForTextToWaveform, AutoProcessor

    if transformers.__version__ != TRANSFORMERS_VERSION:
        raise RuntimeError(f"Compiled VibeVoice requires transformers=={TRANSFORMERS_VERSION} in its isolated runtime")
    processor = AutoProcessor.from_pretrained(config["model_dir"], local_files_only=True)
    model = AutoModelForTextToWaveform.from_pretrained(
        config["model_dir"], local_files_only=True, dtype=torch.bfloat16,
        device_map="cuda", attn_implementation={"text_config": "sdpa", "audio_config": "eager",
                                                "semantic_model_config": "eager"},
    ).eval()
    return processor, model


def generate(torch, processor, model, voice, passages, config, *, compiled=True):
    from transformers import CompileConfig

    conversations = [[{"role": "0", "content": [
        {"type": "text", "text": passage.get("render_text", passage["text"])},
        {"type": "audio", "audio": voice},
    ]}] for passage in passages]
    inputs = processor.apply_chat_template(
        conversations, tokenize=True, return_dict=True, add_generation_prompt=True,
        processor_kwargs={"padding": True, "return_tensors": "pt"},
    )
    if any(count > int(config["max_input_tokens"]) for count in inputs["attention_mask"].sum(-1).tolist()):
        raise RuntimeError("passage exceeds VibeVoice input-token ceiling; rebuild the plan with smaller passages")
    inputs = inputs.to(model.device, model.dtype)
    torch.compiler.cudagraph_mark_step_begin()
    execution = (dict(cache_implementation="static", compile_config=CompileConfig(mode="default", dynamic=False))
                 if compiled else dict(cache_implementation="dynamic", disable_compile=True))
    result = model.generate(
        **inputs, guidance_scale=float(config["cfg_scale"]), num_diffusion_steps=int(config["ddpm_steps"]),
        max_new_tokens=int(config["max_new_tokens"]), do_sample=False,
        return_dict_in_generate=True, **execution,
    )
    # EOS and padding share an ID. Only inspect new tokens, never the padded
    # prompt; a row without EOS was truncated and must not become a checkpoint.
    tokens = result.sequences[:, inputs["input_ids"].shape[1]:]
    eos = model.generation_config.eos_token_id
    eos_ids = [eos] if isinstance(eos, int) else eos
    capped = ~torch.isin(tokens, torch.tensor(eos_ids, device=tokens.device)).any(dim=1)
    return result.audio, capped
