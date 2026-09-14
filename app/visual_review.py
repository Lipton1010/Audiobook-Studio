"""Durable, local review state for visual material detected during extraction."""

import hashlib
import json
import os
import threading
import time
import re
from pathlib import Path


_LOCK = threading.RLock()
_DECISIONS = {"keep", "describe", "skip"}


def _json(path, default):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return default


def _required_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError) as exc:
        raise ValueError(f"Review data is unreadable: {Path(path).name}") from exc


def load_blocks(path):
    data = _required_json(path)
    blocks = data.get("blocks") if isinstance(data, dict) else None
    if not isinstance(blocks, list) or any(not isinstance(block, dict) for block in blocks):
        raise ValueError(f"Review data is unreadable: {Path(path).name}")
    return blocks


def _write(path, value):
    path = Path(path)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temp, path)


def fingerprint(block):
    source = {key: block.get(key) for key in ("type", "text", "visual_kind", "source_page")}
    return hashlib.sha256(json.dumps(source, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def _visuals(source):
    counts = {}
    items = []
    for index, block in enumerate(source):
        if block.get("type") != "visual":
            continue
        fp = fingerprint(block)
        counts[fp] = counts.get(fp, 0) + 1
        item_id = f"{fp[:16]}-{counts[fp]}"
        items.append((index, item_id, fp, block))
    return items


def _nearby(source, index):
    before, after = [], []
    for block in reversed(source[:index]):
        if block.get("type") != "visual" and block.get("text"):
            before.append(block["text"])
            if len(before) == 2:
                break
    for block in source[index + 1:]:
        if block.get("type") != "visual" and block.get("text"):
            after.append(block["text"])
            if len(after) == 2:
                break
    return {"before": list(reversed(before)), "after": after}


def _suggestion(block, source_available):
    if not source_available:
        return {"decision": "describe", "spoken_text": "", "reason": "The original visual text is unavailable. Add a manual description or skip it."}
    kind = str(block.get("visual_kind") or "visual material")
    return {"decision": "describe", "spoken_text": "", "reason": f"Review this {kind}; no automatic description is inferred from the extraction."}


def _recover_cached_pages(job_dir, state):
    if not isinstance(state, dict):
        return None
    try:
        expected = set(range(int(state["page_from"]), int(state["page_to"]) + 1))
    except (KeyError, TypeError, ValueError):
        return None
    pages = {}
    for page in (Path(job_dir) / "pages").glob("page_*.md"):
        match = re.fullmatch(r"page_(\d+)\.md", page.name)
        if match:
            pages[int(match.group(1))] = page
    if not expected or not expected.issubset(pages):
        return None
    import pipeline_text as pt
    grouped = []
    for page_number in sorted(expected):
        page = pages[page_number]
        raw = page.read_text(encoding="utf-8")
        tagged = ([{"type": "visual", "text": "", "visual_kind": "unreadable OCR page"}]
                  if not raw.strip() else pt.filter_copyright_blocks(pt.tag_blocks(raw)))
        for block in tagged:
            block["source_page"] = page_number
        grouped.append(tagged)
    return pt.stitch_pages(grouped) if grouped else None


def _legacy_visuals(blocks):
    import pipeline_text as pt
    blocks = pt.retag_legacy_visual_blocks(blocks)
    legacy = []
    for index, block in enumerate(blocks):
        copy = dict(block)
        kind = copy.get("type")
        text = str(copy.get("text", ""))
        if kind in ("table", "omitted_data", "diagram"):
            copy["type"] = "visual"
            copy["visual_kind"] = "legacy omitted material" if kind != "diagram" else "diagram"
            copy["_source_available"] = kind == "diagram" and "omitted" not in text.lower()
        elif kind in ("body", "heading"):
            tagged = pt.tag_blocks(text)
            if len(tagged) == 1 and tagged[0].get("type") == "visual":
                copy.update(tagged[0])
                copy["_source_available"] = True
            elif kind == "body" and re.match(r"\s*\d{1,2}:\d{2}\b", text):
                adjacent_code = any(
                    re.match(r"\s*\[[A-Za-z0-9]{2,}\]", str(blocks[pos].get("text", "")))
                    for pos in (index - 1, index + 1) if 0 <= pos < len(blocks)
                )
                if adjacent_code or (legacy and legacy[-1].get("type") == "visual"):
                    copy["type"] = "visual"
                    copy["visual_kind"] = "structured log"
                    copy["_source_available"] = True
        legacy.append(copy)
    grouped = []
    for block in legacy:
        text = str(block.get("text", ""))
        logish = bool(re.match(r"\s*(?:\[[A-Za-z0-9]{2,}\]|\d{1,2}:\d{2}|\|)", text))
        if (grouped and block.get("type") == "visual" and grouped[-1].get("type") == "visual"
                and logish and re.match(r"\s*(?:\[[A-Za-z0-9]{2,}\]|\d{1,2}:\d{2}|\|)", str(grouped[-1].get("text", "")))):
            grouped[-1]["text"] = grouped[-1].get("text", "").rstrip() + "\n" + text.lstrip()
            grouped[-1]["visual_kind"] = "structured log"
        else:
            grouped.append(block)
    return grouped


def _recover_path_a(state):
    if not isinstance(state, dict) or state.get("path") != "A":
        return None
    try:
        page_from, page_to = int(state["page_from"]), int(state["page_to"])
        import pipeline_text as pt
        for key in ("pdf_path", "processed_pdf_path", "source_pdf_original_path"):
            pdf = Path(str(state.get(key, "")))
            if pdf.is_file() and pdf.suffix.lower() == ".pdf":
                blocks, _mode = pt.extract_path_a(str(pdf), page_from, page_to)
                return blocks
        return None
    except (KeyError, TypeError, ValueError, OSError):
        return None


def prepare(job_dir, state=None):
    """Return review metadata, preserving source blocks before any projection."""
    job_dir = Path(job_dir)
    with _LOCK:
        source_path = job_dir / "source_blocks.json"
        source_available = source_path.exists()
        source_data = _required_json(source_path) if source_available else {}
        source = load_blocks(source_path) if source_available else None
        if source_available and source is None:
            raise ValueError("Review data is unreadable: source_blocks.json")
        if source is None:
            blocks_path = job_dir / "blocks.json"
            if not blocks_path.exists():
                raise ValueError("Visual review is not available until extraction finishes.")
            snapshot = job_dir / "legacy_blocks.json"
            if not snapshot.exists():
                temp = snapshot.with_suffix(".tmp")
                with temp.open("xb") as handle:
                    handle.write(blocks_path.read_bytes())
                os.replace(temp, snapshot)
            current = load_blocks(blocks_path)
            source = current if isinstance(current, list) else []
            state = state or _json(job_dir / "state.json", None)
            recovered = _recover_path_a(state) or _recover_cached_pages(job_dir, state)
            if recovered is not None and any(block.get("type") == "visual" for block in recovered):
                source, source_available = recovered, True
                _write(source_path, {"blocks": source, "source_available": True,
                                     "recovered_from": "pdf" if state.get("path") == "A" else "cached_pages"})
            else:
                # Do not replace prose-only legacy narration with a newer
                # extractor's paragraphing. Retag only visible legacy evidence.
                source = _legacy_visuals(source)
                _write(source_path, {"blocks": source, "source_available": False,
                                     "migrated_legacy": True})
                source_available = False
        else:
            source_available = bool(source_data.get("source_available", True))
        review_path = job_dir / "visual_review.json"
        review = _required_json(review_path) if review_path.exists() else {"decisions": {}}
        decisions = review.get("decisions") if isinstance(review.get("decisions"), dict) else None
        if decisions is None:
            raise ValueError("Review data is unreadable: visual_review.json")
        items = []
        for index, item_id, fp, block in _visuals(source):
            saved = decisions.get(item_id, {})
            valid = saved.get("fingerprint") == fp and saved.get("decision") in _DECISIONS
            available = block.get("_source_available", source_available)
            if (not available and block.get("type") == "visual" and block.get("text", "").strip()
                    and not str(block.get("visual_kind", "")).startswith("legacy omitted")):
                available = True
            items.append({
                "id": item_id, "index": index, "fingerprint": fp,
                "original_text": block.get("text", ""), "visual_kind": block.get("visual_kind", "visual"),
                "source_page": block.get("source_page"), "source_available": available,
                "nearby_prose": _nearby(source, index), "decision": saved.get("decision") if valid else None,
                "spoken_text": (block.get("text", "") if valid and saved.get("decision") == "keep"
                                else saved.get("spoken_text", "") if valid else ""),
                "keep_text": block.get("text", ""),
                "suggestion": _suggestion(block, available),
            })
        return source, items, decisions


def project(job_dir):
    source, items, decisions = prepare(job_dir)
    by_index = {item["index"]: item for item in items}
    blocks, unresolved = [], []
    for index, block in enumerate(source):
        item = by_index.get(index)
        if item is None:
            blocks.append(dict(block))
            continue
        decision = item["decision"]
        if decision is None:
            unresolved.append(item)
        elif decision != "skip":
            text = block.get("text", "") if decision == "keep" else item["spoken_text"]
            if text.strip():
                spoken = {"type": "body", "text": text}
                for key in ("source_page", "source_page_end"):
                    if key in block:
                        spoken[key] = block[key]
                blocks.append(spoken)
    return blocks, unresolved, items, decisions


def preview_blocks(job_dir):
    """Projected spoken blocks, with unresolved notices at their source position."""
    source, items, _decisions = prepare(job_dir)
    by_index = {item["index"]: item for item in items}
    blocks = []
    for index, block in enumerate(source):
        item = by_index.get(index)
        if item is None:
            blocks.append(dict(block))
        elif item["decision"] is None:
            blocks.append({"type": "body", "text": "[Visual review required: "
                           f"{item.get('visual_kind', 'visual')}]"})
        elif item["decision"] != "skip":
            text = block.get("text", "") if item["decision"] == "keep" else item["spoken_text"]
            if text.strip():
                blocks.append({"type": "body", "text": text})
    return blocks


def review_payload(job_dir):
    _source, items, _decisions = prepare(job_dir)
    unresolved = sum(item["decision"] is None for item in items)
    return {"items": items, "unresolved_count": unresolved, "editable": True}


def write_projection(job_dir):
    blocks, unresolved, _items, _decisions = project(job_dir)
    if unresolved:
        return False
    _write(Path(job_dir) / "blocks.json", {"blocks": blocks})
    return True


def save_decision(job_dir, item_id, fingerprint_value, decision, spoken_text):
    if decision not in _DECISIONS:
        raise ValueError("Choose keep, describe, or skip.")
    spoken_text = str(spoken_text or "").strip()
    if decision == "describe" and not spoken_text:
        raise ValueError("A description needs spoken text.")
    with _LOCK:
        _source, items, decisions = prepare(job_dir)
        item = next((entry for entry in items if entry["id"] == item_id), None)
        if item is None:
            raise ValueError("visual review item not found")
        if item["fingerprint"] != fingerprint_value:
            raise ValueError("This visual changed. Reload the review before saving.")
        if decision == "keep" and not item["original_text"].strip():
            raise ValueError("This visual has no extracted text to keep. Add a description or skip it.")
        decisions[item_id] = {"fingerprint": fingerprint_value, "decision": decision,
                              "spoken_text": item["original_text"] if decision == "keep" else spoken_text,
                              "updated_at": time.time()}
        _write(Path(job_dir) / "visual_review.json", {"decisions": decisions})
        return project(job_dir)
