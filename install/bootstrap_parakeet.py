"""Install Parakeet in a dedicated runtime, or register verified existing paths."""

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import shutil
import os

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "app"))
from vibevoice_quality import PARAKEET_MODEL_ID, PARAKEET_REVISION, PARAKEET_WORKFLOW, parakeet_setup_error


def verify_model_files(folder, manifest):
    """Bind tokenizer/configuration and attribution, not only the large tensor."""
    for item in manifest['files']:
        name = item['name']
        if Path(name).name != name or '/' in name or '\\' in name:
            raise ValueError('Invalid model manifest filename')
        path = Path(folder) / name
        if not path.is_file() or path.stat().st_size != item['bytes']:
            raise ValueError(f'Parakeet file missing or wrong size: {name}')
        with path.open('rb') as stream:
            checksum = hashlib.file_digest(stream, 'sha256').hexdigest()
        if checksum != item['sha256']:
            raise ValueError(f'Parakeet file checksum mismatch: {name}')


def register(config_path, python, model):
    config_path = Path(config_path)
    config = json.loads(config_path.read_text(encoding="utf-8")) if config_path.exists() else {}
    config.update(vibevoice_workflow=PARAKEET_WORKFLOW,
                  parakeet_python=str(Path(python).resolve()), parakeet_model=str(Path(model).resolve()))
    temporary = config_path.with_suffix(".tmp")
    temporary.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(config_path)


def create_runtime(environment, base_python=None, conda=None):
    """Create only a new private prefix, with no global registration or PATH changes."""
    environment = Path(environment)
    if environment.exists():
        raise ValueError("The target runtime already exists; configure it explicitly instead.")
    if sys.platform != 'win32':
        raise ValueError('This pinned pack supports Windows x64 only.')
    if base_python:
        probe = subprocess.run([str(base_python), '-c', "import sys,struct; print('%s.%s:%s' % (*sys.version_info[:2],struct.calcsize('P')*8))"], check=True, capture_output=True, text=True)
        if probe.stdout.strip() != '3.11:64':
            raise ValueError('The supplied base interpreter must be Windows x64 Python 3.11.')
        subprocess.run([str(base_python), '-m', 'venv', str(environment)], check=True)
        return environment / 'Scripts/python.exe'
    conda = Path(conda) if conda else REPO / 'runtime/miniconda3/Scripts/conda.exe'
    if not conda.is_file():
        raise ValueError('Install the core runtime first, or supply --conda or a Windows x64 Python 3.11 --python.')
    env = os.environ.copy()
    env.update(CONDA_REGISTER_ENVS='false', CONDA_NO_PLUGINS='true', CONDA_SOLVER='classic')
    subprocess.run([str(conda), 'create', '--prefix', str(environment), '--file', str(REPO / 'install/parakeet-python-win64.lock.txt'), '--no-default-packages', '--yes'], env=env, check=True)
    return environment / 'python.exe'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--install", action="store_true")
    mode.add_argument("--configure-existing", action="store_true")
    mode.add_argument("--check-only", action="store_true")
    mode.add_argument("--plan", action="store_true")
    parser.add_argument("--accept-model-terms", action="store_true")
    parser.add_argument("--python", type=Path)
    parser.add_argument("--conda", type=Path, help="Existing private Miniforge conda executable")
    parser.add_argument("--runtime-root", type=Path, default=REPO / "runtime")
    parser.add_argument("--model-dir", type=Path)
    parser.add_argument("--config", type=Path, default=REPO / "app/config.json")
    args = parser.parse_args()
    manifest = json.loads((REPO / 'install/parakeet-pack.json').read_text(encoding='utf-8'))
    if args.plan:
        print(json.dumps(manifest, indent=2))
        return
    if args.install and not args.accept_model_terms:
        parser.error('Review the NVIDIA model attribution and CC-BY-4.0 terms with --plan, then acknowledge with --accept-model-terms.')
    root = args.runtime_root.resolve()
    model = args.model_dir or root / "models/parakeet-tdt-0.6b-v3"
    python = args.python
    if args.install:
        from model_hardware import inventory, describe
        check_path = root
        while not check_path.exists():
            check_path = check_path.parent
        machine = inventory(check_path)
        print(describe(machine))
        gpu = machine.get('selected_gpu')
        if not gpu or gpu['free_gib'] < 4:
            parser.error('Checker setup needs a verified NVIDIA device with at least 4 GiB currently free VRAM. This is an admission estimate, not a fit guarantee.')
        if machine.get('free_ram_gib') is None or machine['free_ram_gib'] < 8:
            parser.error('Checker setup needs at least 8 GiB currently free RAM (conservative estimate).')
        if shutil.disk_usage(check_path).free < 20 * 1024**3:
            parser.error('Keep at least 20 GiB free for the checker runtime, weights and download cache.')
        environment = root / "parakeet"
        if environment.exists():
            raise ValueError("The target runtime already exists; verify it with --configure-existing instead of modifying it.")
        python = create_runtime(environment, python, args.conda)
        subprocess.run([str(python), "-m", "pip", "install", "--require-hashes", "--no-index", "-r", str(REPO / "install/requirements-parakeet-win311.lock.txt")], check=True)
        code = ("import sys; from huggingface_hub import snapshot_download; "
                "snapshot_download(sys.argv[1],revision=sys.argv[2],local_dir=sys.argv[3],"
                "allow_patterns=['*.json','*.safetensors','README.md'])")
        subprocess.run([str(python), "-c", code, PARAKEET_MODEL_ID, PARAKEET_REVISION, str(model)], check=True)
    error = parakeet_setup_error(python, model)
    if error:
        raise ValueError(error)
    verify_model_files(model, manifest)
    subprocess.run([str(python), "-c", "import sys, torch, soundfile, scipy, pyloudnorm, librosa; from transformers import AutoModelForTDT, AutoProcessor; AutoProcessor.from_pretrained(sys.argv[1], local_files_only=True); assert torch.cuda.is_available(), 'CUDA is required'", str(model)], check=True)
    if not args.check_only:
        register(args.config, python, model)
    print("Parakeet runtime verified. Existing book workflow settings are preserved.")


if __name__ == "__main__":
    main()
