"""Small audio conversions shared only by the isolated VibeVoice runtime."""

from math import gcd

import numpy as np


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
