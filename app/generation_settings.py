"""Validated, job-local narration settings shared by the UI and workers."""

import math


BACKENDS = ("chatterbox", "vibevoice")
PERFORMANCE_MODES = ("auto", "conservative")

_DEFAULTS = {
    "chatterbox": {
        "A": {
            "gap_ms": 150,
            "block_gap_ms": 650,
            "heading_before_ms": 200,
            "heading_after_ms": 150,
            "performance_mode": "auto",
        },
        "B": {
            "gap_ms": 50,
            "block_gap_ms": 100,
            "heading_before_ms": 200,
            "heading_after_ms": 150,
            "performance_mode": "auto",
        },
    },
    "vibevoice": {
        "A": {
            "passage_gap_ms": 150,
            "heading_lead_ms": 200,
            "cfg_scale": 2.0,
            "ddpm_steps": 20,
            "performance_mode": "auto",
        },
        "B": {
            "passage_gap_ms": 150,
            "heading_lead_ms": 200,
            "cfg_scale": 2.0,
            "ddpm_steps": 20,
            "performance_mode": "auto",
        },
    },
}

_PAUSE_KEYS = {
    "chatterbox": ("gap_ms", "block_gap_ms", "heading_before_ms", "heading_after_ms"),
    "vibevoice": ("passage_gap_ms", "heading_lead_ms"),
}


def _backend_path(backend, path):
    if backend not in BACKENDS:
        raise ValueError("backend must be 'chatterbox' or 'vibevoice'")
    if path not in ("A", "B"):
        raise ValueError("path must be 'A' or 'B'")
    return backend, path


def _integer(value, name, minimum=0, maximum=5000):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be an integer number of milliseconds")
    if not math.isfinite(value) or int(value) != value:
        raise ValueError(f"{name} must be a finite integer number of milliseconds")
    value = int(value)
    if not minimum <= value <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum} milliseconds")
    return value


def default_settings(backend, path):
    """Return a new canonical settings dict for one backend and extraction path."""
    backend, path = _backend_path(backend, path)
    return dict(_DEFAULTS[backend][path])


def normalize_settings(backend, path, values=None):
    """Validate untrusted settings and fill omissions with the recommended defaults.

    The result is safe to persist in a job state.  Values are deliberately flat:
    this makes the browser payload and the worker config identical.
    """
    backend, path = _backend_path(backend, path)
    if values is None:
        values = {}
    if not isinstance(values, dict):
        raise ValueError("generation settings must be an object")
    defaults = default_settings(backend, path)
    unknown = sorted(set(values) - set(defaults))
    if unknown:
        raise ValueError("unknown generation settings: " + ", ".join(unknown))

    result = dict(defaults)
    for key in _PAUSE_KEYS[backend]:
        if key in values:
            result[key] = _integer(values[key], key)
    if backend == "vibevoice":
        if "cfg_scale" in values:
            value = values["cfg_scale"]
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                raise ValueError("cfg_scale must be a finite number")
            if not 1.0 <= float(value) <= 5.0:
                raise ValueError("cfg_scale must be between 1.0 and 5.0")
            result["cfg_scale"] = float(value)
        if "ddpm_steps" in values:
            result["ddpm_steps"] = _integer(values["ddpm_steps"], "ddpm_steps", 10, 100)
    if "performance_mode" in values:
        value = values["performance_mode"]
        if value not in PERFORMANCE_MODES:
            raise ValueError("performance_mode must be 'auto' or 'conservative'")
        result["performance_mode"] = value
    return result


def runtime_settings(backend, path, values=None):
    """Map canonical settings to the job config keys consumed by each worker.

    ``generation_settings`` is retained for display/editing.  ``batch_preference``
    is a scheduling hint only; it is intentionally absent from audio identities.
    """
    backend, path = _backend_path(backend, path)
    settings = normalize_settings(backend, path, values)
    mapped = {
        "generation_settings": settings,
        "batch_preference": settings["performance_mode"],
    }
    if backend == "vibevoice":
        mapped.update({
            "cfg_scale": settings["cfg_scale"],
            "ddpm_steps": settings["ddpm_steps"],
            "passage_gap_ms": settings["passage_gap_ms"],
            "heading_lead_ms": settings["heading_lead_ms"],
            "cross_parent_render_ahead": settings["performance_mode"] == "auto",
        })
    else:
        mapped.update({key: settings[key] for key in _PAUSE_KEYS[backend]})
    return mapped
