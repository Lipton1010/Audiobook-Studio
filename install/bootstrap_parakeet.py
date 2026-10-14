"""Install Parakeet in a dedicated runtime, or register verified existing paths."""

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "app"))
from vibevoice_quality import PARAKEET_MODEL_ID, PARAKEET_REVISION, PARAKEET_WORKFLOW, parakeet_setup_error


def register(config_path, python, model):
    config_path = Path(config_path)
    config = json.loads(config_path.read_text(encoding="utf-8")) if config_path.exists() else {}
    config.update(vibevoice_workflow=PARAKEET_WORKFLOW,
                  parakeet_python=str(Path(python).resolve()), parakeet_model=str(Path(model).resolve()))
    temporary = config_path.with_suffix(".tmp")
    temporary.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(config_path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--install", action="store_true")
    mode.add_argument("--configure-existing", action="store_true")
    mode.add_argument("--check-only", action="store_true")
    parser.add_argument("--python", type=Path)
    parser.add_argument("--runtime-root", type=Path, default=REPO / "runtime")
    parser.add_argument("--model-dir", type=Path)
    parser.add_argument("--config", type=Path, default=REPO / "app/config.json")
    args = parser.parse_args()
    root = args.runtime_root.resolve()
    model = args.model_dir or root / "models/parakeet-tdt-0.6b-v3"
    python = args.python
    if args.install:
        if python:
            parser.error("--install creates a new environment; use --configure-existing with --python.")
        environment = root / "parakeet"
        if environment.exists():
            raise ValueError("The target runtime already exists; verify it with --configure-existing instead of modifying it.")
        subprocess.run([sys.executable, "-m", "venv", str(environment)], check=True)
        python = environment / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
        subprocess.run([str(python), "-m", "pip", "install", "torch==2.10.0+cu128", "--index-url", "https://download.pytorch.org/whl/cu128"], check=True)
        subprocess.run([str(python), "-m", "pip", "install", "-r", str(REPO / "install/requirements-parakeet.txt")], check=True)
        code = ("import sys; from huggingface_hub import snapshot_download; "
                "snapshot_download(sys.argv[1],revision=sys.argv[2],local_dir=sys.argv[3],"
                "allow_patterns=['*.json','*.safetensors'])")
        subprocess.run([str(python), "-c", code, PARAKEET_MODEL_ID, PARAKEET_REVISION, str(model)], check=True)
    error = parakeet_setup_error(python, model)
    if error:
        raise ValueError(error)
    with (model / "model.safetensors").open("rb") as source:
        checksum = hashlib.file_digest(source, "sha256").hexdigest()
    if checksum != "3a2026366188c8c68598edbbff92f8d11590a08e0ae2e6775544e7b07d6a5e11":
        raise ValueError("Parakeet weights do not match the pinned, tested revision.")
    subprocess.run([str(python), "-c", "import torch, soundfile, scipy, pyloudnorm; from transformers import AutoModelForTDT, AutoProcessor; assert torch.cuda.is_available(), 'CUDA is required'"], check=True)
    if not args.check_only:
        register(args.config, python, model)
    print("Parakeet runtime verified. Existing book workflow settings are preserved.")


if __name__ == "__main__":
    main()
