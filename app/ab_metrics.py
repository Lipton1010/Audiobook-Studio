"""
Objective audio-comparison helpers for the batched-vs-v1 A/B (chatterbox env).
Speaker-embedding cosine similarity is used as an OBJECTIVE proxy for "same
voice"; it does not replace the human listen test, it flags regressions.

We reuse Chatterbox's own VoiceEncoder (the same d-vector model the pipeline
uses to build speaker conditioning) so the metric is aligned with what the
model itself considers speaker identity.
"""
import numpy as np
import librosa

S3_SR = 16000  # voice encoder sample rate


def speaker_embed(ve, wav_f32, sr):
    """d-vector for a mono float32 waveform, resampled to 16k."""
    w16 = librosa.resample(wav_f32.astype(np.float32), orig_sr=sr, target_sr=S3_SR) if sr != S3_SR else wav_f32
    emb = ve.embeds_from_wavs([w16], sample_rate=S3_SR)  # (1, D)
    v = np.asarray(emb).reshape(-1)
    n = np.linalg.norm(v)
    return v / n if n > 0 else v


def cosine(a, b):
    return float(np.dot(a, b))  # inputs are unit-normalized


def audio_stats(wav_f32, sr):
    rms = float(np.sqrt(np.mean(wav_f32.astype(np.float64) ** 2))) if len(wav_f32) else 0.0
    peak = float(np.max(np.abs(wav_f32))) if len(wav_f32) else 0.0
    return {"sec": round(len(wav_f32) / sr, 3), "rms": round(rms, 5), "peak": round(peak, 4)}
