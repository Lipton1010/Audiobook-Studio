"""Read-only, version-aware inventory for an explicitly chosen narration migration."""

import json
from pathlib import Path

import vibevoice_delivery as delivery
import vibevoice_worker as worker


def describe(unit):
    rendered = worker._profiled_unit(unit)
    return {"index": unit["index"], "identity": unit["identity"], "text": unit["text"],
            "text_sha256": unit["text_sha256"], "spoken_text": unit.get("spoken_text", unit["text"]),
            "spoken_text_sha256": delivery.text_hash(unit.get("spoken_text", unit["text"])),
            "render_text_sha256": worker._render_text_sha256(rendered, rendered["render_profile"]),
            "render_profile": rendered["render_profile"],
            "render_policy_sha256": delivery.policy_hash(rendered["render_profile"])}


def plan_migration(job, proposed_config):
    """Inventory all shifted indices and affected approvals without writing the job."""
    job = Path(job).resolve()
    plan, current = worker.load_plan(job)
    changed = []
    unchanged_units = 0
    for parent in plan['passages']:
        old = {u['index']: describe(u) for u in worker._units_for_parent(parent, current)}
        new = {u['index']: describe(u) for u in worker._units_for_parent(parent, proposed_config)}
        rows = []
        for index in sorted(old.keys() | new.keys()):
            before, after = old.get(index), new.get(index)
            reasons = []
            if before is None or after is None:
                reasons.append('unit added or removed by boundary repair')
            else:
                for key, label in [('identity', 'unit boundary or index changed'),
                                   ('spoken_text_sha256', 'intended spoken text changed'),
                                   ('render_policy_sha256', 'delivery policy changed')]:
                    if before[key] != after[key]:
                        reasons.append(label)
            if not reasons:
                unchanged_units += 1
                continue
            artifacts = []
            for folder in ('units', 'review_units', 'pending_units'):
                path = worker._receipt_path(job / worker.SEGMENTS_DIR / folder, index)
                if not path.exists():
                    continue
                receipt = json.loads(path.read_text(encoding='utf-8'))
                wav = worker._wav_path(path.parent, index)
                artifacts.append({'receipt': str(path.relative_to(job)), 'receipt_sha256': worker.sha256_file(path),
                                  'audio': str(wav.relative_to(job)) if wav.exists() else None,
                                  'audio_sha256': worker.sha256_file(wav) if wav.exists() else None,
                                  'listening_approval': receipt.get('listening_approval'),
                                  'attempt': receipt.get('attempt'), 'status': receipt.get('status'),
                                  'recorded_render_profile': receipt.get('render_profile', receipt.get('unit', {}).get('render_profile')),
                                  'recorded_render_text_sha256': receipt.get('render_text_sha256'),
                                  'recorded_spoken_text_sha256': receipt.get('spoken_text_sha256'),
                                  'recorded_render_policy_sha256': receipt.get('render_policy_sha256')})
            rows.append({'index': index, 'reasons': reasons, 'old': before, 'new': after,
                         'action': 'retire old index' if after is None else 'replace audio' if any(a['audio'] for a in artifacts) else 'generate',
                         'artifacts': artifacts, 'transfer_approval': False})
        if rows:
            parent_wav = worker._wav_path(job / worker.SEGMENTS_DIR, parent['index'])
            parent_receipt = worker._receipt_path(job / worker.SEGMENTS_DIR, parent['index'])
            changed.append({'parent_index': parent['index'], 'parent_identity': parent['identity'],
                            'source_pages': parent.get('source_pages', []), 'units': rows,
                            'reassemble': True,
                            'assembled_audio_exists': parent_wav.exists(),
                            'assembled_audio': str(parent_wav.relative_to(job)),
                            'assembled_audio_sha256': worker.sha256_file(parent_wav) if parent_wav.exists() else None,
                            'parent_receipt_sha256': worker.sha256_file(parent_receipt) if parent_receipt.exists() else None})
    return {'job': str(job), 'plan_sha256': worker.sha256_file(job / 'vibevoice_plan.json'),
            'old_config_sha256': worker.sha256_file(job / 'vibevoice_config.json'),
            'new_config': proposed_config, 'changed_parents': changed, 'unchanged_units': unchanged_units,
            'changed_units': sum(len(p['units']) for p in changed),
            'affected_approvals': sum(bool(a['listening_approval']) for p in changed for u in p['units'] for a in u['artifacts']),
            'production_writes': False}


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('job', type=Path)
    parser.add_argument('proposed_config', type=Path)
    args = parser.parse_args()
    config = json.loads(args.proposed_config.read_text(encoding='utf-8'))
    print(json.dumps(plan_migration(args.job, config), ensure_ascii=False, indent=2))
