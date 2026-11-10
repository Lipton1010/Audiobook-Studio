"""Inspect the optional Drama pack or explicitly register exact existing assets.

No download, inference, narrator-default change or existing-job migration occurs.
Fresh provisioning remains blocked until the runtime release gates are complete.
"""
import argparse
import json
import os
from pathlib import Path
import sys
import tempfile

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "app"))
import drama3
from model_hardware import inventory, describe, require_generation_capacity
from vibevoice_quality import parakeet_setup_error


def register(path, settings):
    """Update only paths, atomically. Never set narration_backend or touch jobs."""
    path = Path(path)
    data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    data.update(settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(prefix="drama-config-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as out:
            json.dump(data, out, indent=2)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--plan", action="store_true")
    mode.add_argument("--check-only", action="store_true")
    mode.add_argument("--configure-existing", action="store_true")
    parser.add_argument("--executable", type=Path)
    parser.add_argument("--model", type=Path)
    parser.add_argument("--cuda-bin", type=Path)
    parser.add_argument("--parakeet-python", type=Path)
    parser.add_argument("--parakeet-model", type=Path)
    parser.add_argument("--config", type=Path, default=REPO / "app/config.json")
    parser.add_argument("--accept-model-terms", action="store_true")
    args = parser.parse_args()
    manifest = json.loads((REPO / "install/drama3-pack.json").read_text(encoding="utf-8"))
    if args.plan:
        print(json.dumps(manifest, indent=2))
        return
    if any(value is None for value in (args.executable, args.model, args.cuda_bin, args.parakeet_python, args.parakeet_model)):
        parser.error("Supply the existing executable, model, CUDA directory and Parakeet runtime paths.")
    if args.configure_existing and not args.accept_model_terms:
        parser.error("Review " + manifest["model"]["license_url"] + " and acknowledge with --accept-model-terms.")
    machine = inventory(REPO)
    print(describe(machine))
    require_generation_capacity("drama3", REPO, machine)
    settings = dict(drama3_executable=str(args.executable.resolve()), drama3_model=str(args.model.resolve()),
                    drama3_cuda_bin=str(args.cuda_bin.resolve()), parakeet_python=str(args.parakeet_python.resolve()),
                    parakeet_model=str(args.parakeet_model.resolve()))
    drama3.assets(settings, verify=True)
    error = parakeet_setup_error(args.parakeet_python, args.parakeet_model)
    if error:
        raise ValueError(error)
    if args.configure_existing:
        register(args.config, settings)
    print("Pinned native/model hashes and local prerequisite files checked. No inference was run; fresh-machine compatibility is not certified. Existing jobs and default narrator are unchanged.")


if __name__ == "__main__":
    main()
