"""Local-only setup inventory. Observations are not certified minimum requirements."""
import csv
import io
import json
import math
import os
import shutil
import subprocess


MODEL_CHOICES = {
    "none": {"name": "Core only", "vram": "No GPU required for core/text work",
             "evidence": "Narration unavailable until an optional runtime is configured."},
    "vibevoice": {"name": "VibeVoice 1.5B", "vram": "Observed 5.6-7.1 GiB reservation on RTX 4090; minimum not certified",
                  "evidence": "Smaller NVIDIA GPUs are candidates, not validated devices. RAM/disk minimum not yet measured for a clean install.",
                  "terms": "https://huggingface.co/microsoft/VibeVoice-1.5B"},
    "chatterbox": {"name": "Chatterbox original English", "vram": "Minimum not certified; a 16 GB laptop trial failed with OOM",
                   "evidence": "Pinned optional pack produced a 2.56-second built-in-voice sample offline on RTX 4090 with 3.19 GiB peak PyTorch reserved VRAM. This short test is not a long-book memory requirement. Prior 4090 tests and simulated memory caps do not certify physical smaller GPUs; clean-install RAM/disk minima remain unmeasured.",
                   "terms": "https://huggingface.co/ResembleAI/chatterbox"},
    "drama3": {"name": "Drama 3 Q3 (optional Ada pack)", "vram": "Observed 18,920 MiB whole-board peak for existing runtime; 19,534 MiB in isolated portable-build smoke on RTX 4090 24 GB",
               "evidence": "An untrimmed load previously exhausted 32 GB RAM. Correction: earlier standalone tests passed CPU placement through the wrong CLI option and used the four-layer default, not twelve. Their successful short synthetic speech does not validate the app's twelve-layer configuration. A matched twelve-layer loading diagnostic hit the same protective test cap in original and portable runtimes; neither completed inference in that comparison. RAM and Windows commit requirements for the twelve-layer profile remain unvalidated. Q3 uses CPU expert offload, not CPU-only inference. The pinned executable targets CUDA capability 8.9 (Ada) only. The optional verified runtime downloads from the Storybird runtime-only prerelease; weights download from their original pinned repositories. Parakeet checker observed 4,544 MiB whole-board peak in a separate fresh-runtime smoke. Keep 50 GiB free disk for setup (estimate). Checker terms: https://creativecommons.org/licenses/by/4.0/legalcode.en . Runtime/vendor notices accompany the verified ZIP. CUDA terms: https://docs.nvidia.com/cuda/archive/12.9.1/eula/index.html . Runtime source: https://github.com/JarodMica/audio.cpp .",
               "terms": "https://huggingface.co/fishaudio/drama-3/blob/main/LICENSE"},
}


def parse_gpus(text):
    result = []
    for row in csv.reader(io.StringIO(text)):
        if len(row) != 5:
            continue
        try:
            index, name, total, free, driver = [x.strip() for x in row]
            total, free = float(total), float(free)
            if not math.isfinite(total) or not math.isfinite(free) or total <= 0 or not 0 <= free <= total:
                continue
            result.append(dict(index=int(index), name=name, total_gib=total / 1024,
                               free_gib=free / 1024, driver=driver))
        except ValueError:
            continue
    return result


def inventory(path):
    """Never infer GPU presence from the existence of nvidia-smi or failed queries."""
    result = {"gpus": [], "warnings": [], "ram_gib": None, "free_ram_gib": None,
              "free_disk_gib": None, "selected_gpu": None}
    try:
        result["free_disk_gib"] = shutil.disk_usage(path).free / 1024 ** 3
    except OSError:
        result["warnings"].append("Free disk space is unknown.")
    try:
        query = subprocess.run(["nvidia-smi", "--query-gpu=index,name,memory.total,memory.free,driver_version",
                                "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=15)
        if query.returncode == 0:
            result["gpus"] = parse_gpus(query.stdout)
    except (OSError, subprocess.SubprocessError):
        pass
    if result["gpus"]:
        try:
            caps = subprocess.run(["nvidia-smi", "--query-gpu=index,compute_cap", "--format=csv,noheader,nounits"],
                                  capture_output=True, text=True, timeout=15)
            if caps.returncode == 0:
                mapping = {}
                for row in csv.reader(io.StringIO(caps.stdout)):
                    if len(row) == 2:
                        mapping[int(row[0].strip())] = row[1].strip()
                for gpu in result["gpus"]:
                    gpu["compute_capability"] = mapping.get(gpu["index"])
        except (OSError, subprocess.SubprocessError, ValueError):
            pass
    if not result["gpus"]:
        result["warnings"].append("NVIDIA GPU detection unavailable. Narration compatibility is unknown, not confirmed.")
    elif os.environ.get("CUDA_VISIBLE_DEVICES"):
        result["warnings"].append("CUDA_VISIBLE_DEVICES is set; runtime device mapping needs explicit verification.")
    else:
        result["selected_gpu"] = next((g for g in result["gpus"] if g["index"] == 0), None)
        if len(result["gpus"]) > 1:
            result["warnings"].append("Multiple GPUs: memory is not combined. Runtime default device 0 must be verified before narration.")
    if os.name == "nt":
        try:
            import ctypes
            class MemoryStatus(ctypes.Structure):
                _fields_ = [("length", ctypes.c_ulong), ("load", ctypes.c_ulong)] + [(n, ctypes.c_ulonglong) for n in
                    ("total", "available", "page_total", "page_available", "virtual_total", "virtual_available", "extended")]
            status = MemoryStatus()
            status.length = ctypes.sizeof(status)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
                result["ram_gib"] = status.total / 1024 ** 3
                result["free_ram_gib"] = status.available / 1024 ** 3
        except (OSError, AttributeError):
            pass
    return result


def describe(machine):
    lines = ["Local hardware check (no hardware data is sent anywhere):"]
    for gpu in machine["gpus"]:
        lines.append(f"  GPU {gpu['index']}: {gpu['name']}; VRAM {gpu['total_gib']:.1f} GiB total, {gpu['free_gib']:.1f} GiB free; driver {gpu['driver']}; CUDA capability {gpu.get('compute_capability') or 'unknown'}")
    for key, label in (("ram_gib", "Total RAM"), ("free_ram_gib", "Free RAM"), ("free_disk_gib", "Free disk")):
        value = machine[key]
        lines.append(f"  {label}: {value:.1f} GiB" if value is not None else f"  {label}: unknown")
    lines.extend("  WARNING: " + text for text in machine["warnings"])
    for key, model in MODEL_CHOICES.items():
        lines.extend((f"  {key}: {model['name']}", "    " + model["vram"], "    " + model["evidence"]))
        if key != "none":
            policy = "20 GiB free VRAM / 22 GiB free RAM" if key == "drama3" else "8 GiB free VRAM / 8 GiB free RAM"
            qualification = " (Drama twelve-layer requirements unvalidated)" if key == "drama3" else ""
            lines.append("    Current conservative admission policy" + qualification + ": " + policy + "; at least 2 GiB free job disk, more for long books. Not a fit guarantee.")
        if model.get("terms"):
            lines.append("    Terms/model card: " + model["terms"])
    lines.append("Free memory changes. Recheck before generation; no automatic CPU fallback or change to existing jobs.")
    return "\n".join(lines)


def require_generation_capacity(backend, path, machine=None):
    """Conservative admission policy, NOT a certified minimum or fit guarantee.

    Recheck before spawning, not once at install time. Never migrates jobs or
    chooses another model. Actual runtime OOM safeguards remain necessary.
    """
    machine = inventory(path) if machine is None else machine
    gpu = machine.get("selected_gpu")
    if gpu is None:
        raise RuntimeError("Narration hardware is unknown. Check the NVIDIA driver/device mapping; no CPU fallback or model change was made.")
    # Temporary conservative hold, NOT a validated twelve-layer requirement.
    # Earlier standalone evidence used the four-layer default due to an option
    # mistake. Keep existing safety behavior pending a separately validated
    # physical-RAM/Windows-commit policy; do not infer that passing guarantees fit.
    floors = {"drama3": (20, 22), "vibevoice": (8, 8), "chatterbox": (8, 8), "parakeet": (4, 4)}
    if backend not in floors:
        raise RuntimeError("Unknown narrator hardware policy; choose a supported runtime.")
    if backend == "drama3" and gpu.get("compute_capability") != "8.9":
        raise RuntimeError("The pinned Drama runtime was built only for CUDA compute capability 8.9 (Ada). This GPU is unsupported or unverified; a multi-architecture runtime needs separate validation. No model choice changed.")
    vram, ram = floors[backend]
    issues = []
    for actual, floor, label in ((gpu.get("free_gib"), vram, "free GPU memory"),
                                 (machine.get("free_ram_gib"), ram, "free host RAM"),
                                 (machine.get("free_disk_gib"), 2, "free job disk space")):
        if actual is None or not math.isfinite(actual) or actual < floor:
            issues.append(f"{label}: {'unknown' if actual is None else f'{actual:.1f} GiB'}, policy requires {floor} GiB")
    if issues:
        raise RuntimeError("Narration paused before model loading. " + "; ".join(issues) +
                           ". These are conservative admission estimates, not certified minimum requirements. Close other workloads and retry; saved audio and model choices remain unchanged.")
    return machine
