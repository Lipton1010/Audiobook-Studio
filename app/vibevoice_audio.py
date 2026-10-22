"""Small audio conversions shared only by the isolated VibeVoice runtime."""

from math import gcd

import numpy as np


def normalize_audio(audio, sample_rate, target_lufs=-21.0):
    """Gain-only normalization at the real rate, retaining short valid clips."""
    wav = np.asarray(audio, dtype=np.float32)
    if wav.ndim != 1 or len(wav) <= sample_rate / 10 or not np.isfinite(wav).all() or np.max(np.abs(wav)) <= 0.001:
        raise RuntimeError("generated audio was empty, nonfinite, or silent")
    import pyloudnorm as pyln
    if len(wav) < sample_rate * 0.4:
        return wav * min(1.0, 0.95 / float(np.max(np.abs(wav))))
    loudness = pyln.Meter(sample_rate).integrated_loudness(wav)
    if not np.isfinite(loudness):
        raise RuntimeError("loudness normalization could not measure audible energy")
    target = min(float(target_lufs), loudness + 20 * np.log10(0.95 / np.max(np.abs(wav))))
    wav = pyln.normalize.loudness(wav, loudness, target)
    if not np.isfinite(wav).all() or np.max(np.abs(wav)) > 1.0:
        raise RuntimeError("loudness normalization produced invalid audio")
    return wav


def mono_24k(audio, source_sr):
    if not isinstance(source_sr, int) or source_sr <= 0:
        raise ValueError("voice reference has an invalid sample rate")
    audio = np.asarray(audio, dtype=np.float32)
    if audio.ndim != 2 or not audio.size or not np.isfinite(audio).all():
        raise ValueError("voice reference has invalid samples")
    mono = audio.mean(axis=1, dtype=np.float32)
    if source_sr == 24000:
        return mono
    from scipy.signal import resample_poly
    divisor = gcd(source_sr, 24000)
    return resample_poly(mono, 24000 // divisor, source_sr // divisor).astype(np.float32)
