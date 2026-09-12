"""Workload-aware ETA helpers for length-sorted narration buckets."""

import json
import os
import time

PROGRESS_FILENAME = "narration_progress.json"
MIN_BUCKET_SAMPLES = 20
STALE_PROGRESS_SECONDS = 120
STALLED_BATCH_SECONDS = 300


def estimate_remaining_seconds(observations, remaining_tmax):
    """Fit bucket duration to input-token length and forecast the remainder."""
    if not remaining_tmax:
        return 0.0
    if len(observations) < MIN_BUCKET_SAMPLES:
        return None

    # A few tiny headings cannot calibrate the cost of the remaining prose.
    # Wait until the middle of the remaining workload is within 2x the
    # observed input lengths instead of extrapolating across an entire book.
    remaining_sorted = sorted(remaining_tmax)
    if remaining_sorted[len(remaining_sorted) // 2] > 2 * max(x for x, _ in observations):
        return None

    xs = [float(tmax) for tmax, _ in observations]
    ys = [float(seconds) for _, seconds in observations]
    mean_x = sum(xs) / len(xs)
    mean_y = sum(ys) / len(ys)
    variance = sum((x - mean_x) ** 2 for x in xs)

    if variance:
        covariance = sum(
            (x - mean_x) * (y - mean_y) for x, y in zip(xs, ys)
        )
        slope = max(0.0, covariance / variance)
    else:
        slope = 0.0
    intercept = mean_y - slope * mean_x

    return sum(max(0.1, intercept + slope * float(tmax)) for tmax in remaining_tmax)


def write_progress(path, payload):
    """Replace the worker progress sidecar without exposing partial JSON."""
    tmp = path.with_suffix(f".tmp{os.getpid()}")
    for attempt in range(6):
        try:
            tmp.write_text(json.dumps(payload), encoding="utf-8")
            os.replace(tmp, path)
            return True
        except OSError:
            if attempt < 5:
                time.sleep(0.05 * (attempt + 1))
    try:
        tmp.unlink(missing_ok=True)
    except OSError:
        pass
    return False
