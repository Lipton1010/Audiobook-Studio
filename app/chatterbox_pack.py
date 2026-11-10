"""Pinned optional English Chatterbox assets; inference never downloads weights."""
import hashlib
import json
from pathlib import Path


def manifest():
    return json.loads((Path(__file__).resolve().parents[1] / "install/chatterbox-pack.json").read_text(encoding="utf-8"))


def verify_model(folder):
    folder = Path(folder)
    for item in manifest()["files"]:
        if item["name"] == "README.md":
            continue  # Attribution is also retained beside the optional runtime.
        if Path(item["name"]).name != item["name"]:
            raise ValueError("Invalid Chatterbox manifest filename")
        path = folder / item["name"]
        if not path.is_file() or path.stat().st_size != item["bytes"]:
            raise ValueError("Chatterbox file missing or wrong size: " + item["name"])
        with path.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        if digest != item["sha256"]:
            raise ValueError("Chatterbox checksum mismatch: " + item["name"])
    return folder


def load_local(model_class, model_dir=None):
    if model_dir:
        folder = verify_model(model_dir)
    else:
        # Preserve legacy cached selection, but never fetch missing weights as a
        # side effect of narration. Explicit optional setup owns downloads.
        from huggingface_hub import hf_hub_download
        paths = []
        try:
            for item in manifest()["files"]:
                if item["name"] != "README.md":
                    paths.append(Path(hf_hub_download(repo_id="ResembleAI/chatterbox",
                        filename=item["name"], local_files_only=True)))
        except Exception as exc:
            raise RuntimeError("Chatterbox weights are not cached. Open optional narrator setup; no model was downloaded.") from exc
        parents = {p.parent for p in paths}
        if len(parents) != 1:
            raise RuntimeError("Legacy Chatterbox cache spans different snapshots; configure a verified optional pack.")
        folder = parents.pop()
    return model_class.from_local(folder, device="cuda")
