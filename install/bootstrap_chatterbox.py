"""Explicit pinned Chatterbox pack. Never selects a narrator or migrates jobs."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
sys.path.insert(0, str(ROOT / "install"))
from chatterbox_pack import manifest, verify_model
from pinned_download import download
from bootstrap_parakeet import create_runtime


def check_registration_target(path):
    path = Path(path)
    data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    # Legacy jobs use the application's interpreter fallback. Adding a new
    # runtime must not silently change the interpreter behind those jobs.
    for jobs in (path.parent / "jobs", path.parent.parent / "jobs"):
        if jobs.is_dir() and any(jobs.glob("*/config.json")):
            raise ValueError("Existing legacy narration jobs need an explicit runtime migration review; no settings were changed.")
    if data.get("chatterbox_python") or data.get("chatterbox_model_dir"):
        raise ValueError("An existing Chatterbox runtime is configured; it was not replaced. Use check-only or review migration separately.")
    return data


def register(path, python, model):
    path = Path(path)
    data = check_registration_target(path)
    data.update(chatterbox_python=str(Path(python).resolve()), chatterbox_model_dir=str(Path(model).resolve()))
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    temp.replace(path)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument("--install", action="store_true")
    mode.add_argument("--check-only", action="store_true")
    mode.add_argument("--plan", action="store_true")
    p.add_argument("--accept-model-terms", action="store_true")
    p.add_argument("--accept-runtime-terms", action="store_true")
    p.add_argument("--runtime-root", type=Path, default=ROOT / "runtime")
    p.add_argument("--python", type=Path, help="Python 3.11 base for a new isolated environment, or interpreter to check")
    p.add_argument("--conda", type=Path)
    p.add_argument("--existing-model", type=Path, help="Verify and reuse existing exact weights without copying or changing them")
    p.add_argument("--config", type=Path, default=ROOT / "app/config.json")
    a = p.parse_args(); spec = manifest()
    if a.plan:
        print(json.dumps(spec, indent=2)); return
    if a.install and not (a.accept_model_terms and a.accept_runtime_terms):
        p.error("Review the MIT model card and separate runtime terms (including GPL/LGPL dependencies); explicit acknowledgments are required.")
    root = a.runtime_root.resolve(); environment = root / "chatterbox"
    model = a.existing_model or root / "models/chatterbox-original"
    if a.existing_model:
        verify_model(model)
    python = a.python
    if a.install:
        from model_hardware import inventory, describe
        import shutil
        check = root
        while not check.exists(): check = check.parent
        machine = inventory(check); print(describe(machine))
        if machine.get("selected_gpu") is None:
            p.error("NVIDIA compatibility is unknown; no model or runtime installation started.")
        if shutil.disk_usage(check).free < 15 * 1024**3:
            p.error("Keep 15 GiB free for runtime, weights and installation cache (setup estimate).")
        if environment.exists():
            p.error("Target runtime exists and was left unchanged; use --check-only or a fresh runtime root.")
        check_registration_target(a.config)
        python = create_runtime(environment, python, a.conda)
        lock = ROOT / "install/requirements-chatterbox-win311.lock.txt"
        build = root / "chatterbox-build-tools.lock.txt"
        build.write_text("\n".join(l for l in lock.read_text().splitlines() if l.startswith(("setuptools @", "wheel @"))) + "\n")
        base = [str(python), "-m", "pip", "install", "--require-hashes", "--no-index"]
        subprocess.run(base + ["-r", str(build)], check=True)
        subprocess.run(base + ["--no-build-isolation", "-r", str(lock)], check=True)
        base_url = f"https://huggingface.co/{spec['repo']}/resolve/{spec['revision']}/"
        for item in spec["files"]:
            if a.existing_model and item["name"] != "README.md": continue
            target = root / "notices/chatterbox/README.md" if item["name"] == "README.md" else model / item["name"]
            download(base_url + item["name"], target, item["sha256"], item["bytes"])
        notices = root / "notices/chatterbox/DEPENDENCIES.md"
        notices.parent.mkdir(parents=True, exist_ok=True)
        notices.write_text((ROOT / "docs/CHATTERBOX_DEPENDENCIES.md").read_text(encoding="utf-8"), encoding="utf-8")
    if not python: p.error("Supply --python for check-only")
    verify_model(model)
    subprocess.run([str(python), "-m", "pip", "check"], check=True)
    code = "import torch,numpy,scipy,soundfile,perth; from chatterbox.tts import ChatterboxTTS; assert torch.cuda.is_available(); print('Chatterbox imports and CUDA verified; no weights loaded')"
    subprocess.run([str(python), "-c", code], check=True)
    if a.install: register(a.config, python, model)
    print("Chatterbox pack verified. Narrator defaults and existing jobs were not changed.")


if __name__ == "__main__":
    main()
