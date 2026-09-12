"""Private-runtime environment settings shared by setup and the launcher."""

import os
from pathlib import Path


def configure_managed_runtime(runtime_root, create_dirs=False):
    root = Path(runtime_root).resolve()
    miniconda = root / "miniconda3"
    if not create_dirs and not (miniconda / "python.exe").exists():
        return None
    cache = root / "cache"
    if create_dirs:
        for folder in (cache, miniconda / "envs", miniconda / "pkgs"):
            folder.mkdir(parents=True, exist_ok=True)
    os.environ.update({
        "HF_HOME": str(cache / "huggingface"),
        "TORCH_HOME": str(cache / "torch"),
        "PIP_CACHE_DIR": str(cache / "pip"),
        "XDG_CACHE_HOME": str(cache),
        "XDG_CONFIG_HOME": str(root / "config"),
        "CONDA_ENVS_PATH": str(miniconda / "envs"),
        "CONDA_PKGS_DIRS": str(miniconda / "pkgs"),
        "CONDA_REGISTER_ENVS": "false",
        "CONDA_NO_PLUGINS": "true",
        "CONDA_SOLVER": "classic",
        "CONDA_ANACONDA_ANON_USAGE": "false",
        "ANACONDA_ANON_USAGE": "false",
    })
    return root
