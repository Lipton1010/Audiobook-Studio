"""
Voice sample converter. Runs in the chatterbox env (has soundfile).
Reads any libsndfile-supported upload (wav, mp3, flac, ogg), mixes to
mono, trims to the first 20 seconds, writes PCM_16 WAV. Per the
project rule, audio files are read with soundfile, never torchaudio.

Usage: python convert_voice.py <input_file> <output_wav>
"""

import sys

import numpy as np
import soundfile as sf

MAX_SECONDS = 20


def main():
    src, dst = sys.argv[1], sys.argv[2]
    data, sr = sf.read(src, dtype="float32")
    if data.ndim > 1:
        data = data.mean(axis=1)
    data = data[: sr * MAX_SECONDS]
    if len(data) < sr * 3:
        print("ERROR: sample shorter than 3 seconds, too short to clone from")
        sys.exit(2)
    peak = float(np.abs(data).max())
    if peak > 0:
        data = data * (0.95 / max(peak, 0.95))
    sf.write(dst, data, sr, subtype="PCM_16")
    print(f"ok {len(data)/sr:.1f}s at {sr}Hz")


if __name__ == "__main__":
    main()
