"""Private chapter preparation/review for the existing Drama 3 app backend.

prepare, review and audition are CPU-only. analyze requires an explicitly coordinated
GPU slot. Nothing here resumes a job, starts TTS, changes a default or downloads a model.
"""
import argparse
import copy
import json
from pathlib import Path
import shutil

import scene_direction as d
import scene_analysis as analysis
from vibevoice_plan import pack_passages, sha256_file


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def write(path, value):
    path = Path(path)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    temporary.replace(path)


def chapters(plan):
    passages = plan['passages']
    starts = [i for i, p in enumerate(passages) if p.get('heading')]
    if not starts or starts[0] != 0:
        starts.insert(0, 0)
    result = []
    for start, end in zip(starts, starts[1:] + [len(passages)]):
        text = '\n\n'.join(p['text'] for p in passages[start:end])
        result.append({'chapter': len(result), 'start': start, 'end': end,
                       'heading': passages[start].get('heading', 'Opening'),
                       'words': len(text.split()), 'quote_marks': sum(text.count(c) for c in '\"\u201c\u201d\u2018\u2019')})
    return result


def prepare(job, output, chapter):
    job, output = Path(job).resolve(), Path(output).resolve()
    plan, config = read(job / 'vibevoice_plan.json'), read(job / 'vibevoice_config.json')
    if config.get('backend') != 'drama3':
        raise ValueError('Select an existing Drama 3 source job')
    selected = chapters(plan)[chapter]
    blocks = [{'text': p['text'], 'type': 'heading' if p.get('heading') else 'body',
               'source_page': (p.get('source_pages') or [None])[0]}
              for p in plan['passages'][selected['start']:selected['end']]]
    passages = pack_passages(blocks, preserve_sentences=True)
    original = job / ('source_blocks.json' if (job / 'source_blocks.json').exists() else 'blocks.json')
    source = d.canonical(passages, sha256_file(original))
    output.mkdir(parents=True, exist_ok=False)
    shutil.copy2(original, output / 'original_extraction.json')
    shutil.copy2(job / 'blocks.json', output / 'original_spoken_blocks.json')
    write(output / 'chapter_blocks.json', blocks)
    write(output / 'canonical.json', source)
    write(output / 'directions.json', d.new_plan(source, analysis.MODEL, analysis.MODEL_DIGEST))
    write(output / 'baseline_config.json', config)
    write(output / 'source_manifest.json', {'source_job': str(job), 'selection': selected,
          'source_plan_sha256': sha256_file(job / 'vibevoice_plan.json'),
          'source_config_sha256': sha256_file(job / 'vibevoice_config.json'),
          'extraction_sha256': source['extraction_sha256'], 'canonical_sha256': d.digest(source),
          'reference_wav': config['reference_wav'], 'reference_sha256': sha256_file(config['reference_wav']),
          'analysis_status': 'not_started_gpu_gate', 'production_changed': False})
    return selected


def review(folder):
    folder = Path(folder)
    source, plan = read(folder / 'canonical.json'), read(folder / 'directions.json')
    d.validate_plan(source, plan)
    issues = []
    # Actual compiler checks use ordinary narration units, without loading models.
    from vibevoice_units import repair_units
    config = read(folder / 'baseline_config.json')
    for p in source['passages']:
        parent = {'text': p['text'], 'index': p['index'], 'identity': 'preview', 'heading': p['text'] if p['heading'] else None}
        units = repair_units(parent, target_words=75, max_words=100, boundary_policy='sentences_v4', max_chars=1000)
        directed = d.attach_units(units, parent, {'scene_direction': {'source': source, 'plan': plan}})
        for unit in directed:
            issues.extend(unit['scene_direction_compiled']['review'])
    status_path = folder / 'analysis_review_status.json'
    status = read(status_path) if status_path.exists() else {'status': 'not_run' if not plan['spans'] else 'model_proposals_require_review'}
    data = json.dumps({'source': source, 'plan': plan, 'issues': issues, 'status': status}, ensure_ascii=False).replace('<', chr(92)+'u003c').replace('&', chr(92)+'u0026')
    html = '''<!doctype html><meta charset="utf-8"><title>Chapter direction review</title>
<style>body{font:17px system-ui;max-width:950px;margin:35px auto;padding:0 18px;background:#f7f5ef;color:#262823}article{background:white;border:1px solid #ccc;padding:18px;margin:15px 0;border-radius:8px}blockquote{white-space:pre-wrap}input,select,button{font:inherit;padding:8px;margin:5px}small{display:block;color:#555}button{cursor:pointer}</style>
<h1>Chapter direction</h1><p>Review source evidence and audible delivery. Internal emotion does not dictate the voice. Unresolved notes render plain. Original text is preserved.</p>
<p id="summary"></p><button id="save">Save edited directions.json</button><p>The downloaded file replaces only this audition folder’s directions.json. It does not change an audiobook or approve any audio.</p><main id="rows"></main>
<script>const data=DATA;const plan=data.plan;const main=document.querySelector('#rows');
document.querySelector('#summary').textContent=plan.spans.length+' notes; '+data.issues.length+' compiler review items. '+(!plan.spans.length?'Local analysis has not run yet.':'');
const status=document.createElement('p');status.textContent=data.status.status+(data.status.detail?' - '+data.status.detail:'');document.querySelector('#summary').after(status);
for(const fact of plan.context){const item=document.createElement('article');const title=document.createElement('h2');title.textContent='Context proposal: '+fact.character;const note=document.createElement('p');note.textContent=fact.fact;const evidence=document.createElement('blockquote');evidence.textContent=fact.evidence.quote;item.append(title,note,evidence);main.append(item)}
for(const span of plan.spans){const card=document.createElement('article');const title=document.createElement('h2');title.textContent=span.speaker+' · '+span.kind;card.append(title);const quote=document.createElement('blockquote');quote.textContent=span.quote;card.append(quote);const notes=document.createElement('p');notes.textContent='Intention: '+span.intention+' | Internal emotion: '+span.emotion+' | Intensity: '+span.intensity+' | Confidence: '+span.confidence;card.append(notes);const evidence=document.createElement('small');evidence.textContent='Evidence: '+span.evidence.map(x=>x.quote).join(' / ');card.append(evidence);const warning=document.createElement('p');warning.textContent=[span.ambiguity,...data.issues.filter(x=>x.id===span.id).map(x=>x.reason)].filter(Boolean).join(' · ');card.append(warning);
const select=document.createElement('select');for(const label of ['model proposal','plain','calm','whisper','angry','laughing','sighs','laughs']){const o=document.createElement('option');o.value=o.textContent=label;select.append(o)}const prior=plan.overrides[span.id];select.value=prior?(prior.decision==='plain'?'plain':prior.delivery):'model proposal';const speaker=document.createElement('input');speaker.value=prior?.speaker||span.speaker;speaker.setAttribute('aria-label','Speaker');const note=document.createElement('input');note.placeholder='Reason for override';note.value=prior?.note||'';note.setAttribute('aria-label','Evidence or reason for override');
const update=()=>{if(select.value==='model proposal'){delete plan.overrides[span.id];return}plan.overrides[span.id]={decision:select.value==='plain'?'plain':'use',delivery:select.value,speaker:speaker.value,note:note.value}};select.onchange=speaker.oninput=note.oninput=update;card.append(select,speaker,note);main.append(card)}
document.querySelector('#save').onclick=()=>{for(const value of Object.values(plan.overrides)){if(!value.note.trim()||!value.speaker.trim()){alert('Add a speaker and reason to each override.');return}}const url=URL.createObjectURL(new Blob([JSON.stringify(plan,null,2)],{type:'application/json'}));const link=document.createElement('a');link.href=url;link.download='directions.json';link.click();setTimeout(()=>URL.revokeObjectURL(url),1000)};</script>'''.replace('DATA', data)
    (folder / 'review.html').write_text(html, encoding='utf-8')
    write(folder / 'review_items.json', issues)
    return {'annotations': len(plan['spans']), 'review_items': len(issues)}


def revalidate(folder, output):
    """Recheck saved proposals into a fresh, blocked review copy; never infer."""
    folder, output = Path(folder).resolve(), Path(output).resolve()
    source, previous = read(folder/'canonical.json'), read(folder/'directions.json')
    plan, report = analysis.revalidate_saved_plan(source, previous)
    output.mkdir(parents=True, exist_ok=False)
    shutil.copy2(folder/'canonical.json', output/'canonical.json')
    shutil.copy2(folder/'baseline_config.json', output/'baseline_config.json')
    shutil.copy2(folder/'directions.json', output/'original_directions.json')
    write(output/'directions.json', plan)
    write(output/'context_validation.json', report)
    write(output/'analysis_review_status.json', {
        'complete': False, 'semantic_approval': False, 'status': 'source_revalidated_semantic_review_required',
        'detail': 'Exact extracts and source warnings only; no model rerun or semantic approval. Original trial preserved.'})
    write(output/'revalidation_manifest.json', {
        'source_folder': str(folder), 'canonical_sha256': d.digest(source),
        'original_plan_sha256': d.digest(previous), 'candidate_plan_sha256': d.digest(plan),
        'context_policy': analysis.CONTEXT_POLICY, 'inference': False, 'production_changed': False})
    return {**review(output), 'quarantined_context': len(report['quarantined_context']),
            'output': str(output), 'semantic_approval': False}


def audition(folder):
    """Freeze same-unit, same-voice, same-decoding factorial requests. No TTS."""
    from vibevoice_units import repair_units
    folder = Path(folder)
    status_path = folder / 'analysis_review_status.json'
    if status_path.exists() and not read(status_path).get('complete'):
        raise ValueError('Incomplete diagnostic review cannot become an audition')
    source, plan = read(folder / 'canonical.json'), read(folder / 'directions.json')
    d.validate_plan(source, plan)
    config = read(folder / 'baseline_config.json')
    candidates = []
    for p in source['passages']:
        if p['heading']:
            continue
        parent = {'text': p['text'], 'index': p['index'], 'identity': 'audition'}
        units = repair_units(parent, target_words=75, max_words=100, boundary_policy='sentences_v4', max_chars=1000)
        for unit in d.attach_units(units, parent, {'scene_direction': {'source': source, 'plan': plan}}):
            compiled = unit['scene_direction_compiled']
            if len(unit['text']) <= 900:
                candidates.append((bool(compiled['insertions']), sum(unit['text'].count(c) for c in '\"\u201c\u201d'), unit))
    candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
    chosen = [row[2] for row in candidates[:2]]
    if not chosen:
        raise ValueError('No bounded dialogue audition units')
    settings = config['generation_settings']
    cases = []
    for case, unit in enumerate(chosen):
        for seed in (1729, 2718, 31415):
            for tags in ('plain', 'directed'):
                text = unit['text'] if tags == 'plain' else unit['scene_direction_compiled']['render_text']
                cases.append({'id': f'passage{case+1}_{tags}_{seed}', 'text': text,
                    'voice_ref': config['reference_wav'], 'reference_text': config['reference_text'],
                    'seed': seed, 'max_tokens': settings['max_frames'], 'text_chunk_size': 1000,
                    **{key: settings[key] for key in ('temperature','top_p','top_k')}})
    manifest = {'schema': 1, 'status': 'ready' if any(u['scene_direction_compiled']['insertions'] for u in chosen) else 'analysis_or_review_required_no_tag_contrast',
                'canonical_sha256': d.digest(source), 'plan_sha256': d.digest(plan),
                'reference_sha256': sha256_file(config['reference_wav']), 'cases': cases,
                'selected_units': chosen, 'seeds': [1729,2718,31415],
                'model_arms': ['Q3_K_experts_Q8_backbone', 'Q4_K_experts_Q8_backbone'],
                'matched_cpu_expert_layers': 16, 'context_length': settings['context_length'],
                'production_baseline_cpu_expert_layers': config.get('drama3_cpu_expert_layers', 0),
                'gpu_gate': 'parent_slot_required', 'rendered': False,
                'listening': 'Present one matched first-seed A/B pair initially; retain all repeats for internal checks.'}
    write(folder / 'audition_manifest.json', manifest)
    return {key: manifest[key] for key in ('status','matched_cpu_expert_layers','context_length','rendered')}


def quantization_manifest(source, config, selections):
    """Freeze a quantization-only comparison, independent of director annotations."""
    text = d.validate_source(source)
    if not isinstance(selections, list) or len(selections) != 2:
        raise ValueError('Select exactly two reviewed canonical excerpts')
    cases, ids = [], set()
    settings = config['generation_settings']
    for row in selections:
        if not isinstance(row, dict) or set(row) != {'id', 'start', 'end', 'review_note'}:
            raise ValueError('Each excerpt needs exact bounds and a source review note')
        start, end = row['start'], row['end']
        if (row['id'] not in ('passage1', 'passage2') or row['id'] in ids
                or type(start) is not int or type(end) is not int
                or not 0 <= start < end <= len(text) or end-start > 900
                or not isinstance(row['review_note'], str) or not row['review_note'].strip()):
            raise ValueError('Invalid reviewed excerpt')
        ids.add(row['id'])
        for seed in (1729, 2718, 31415):
            cases.append({'id': f"{row['id']}_plain_{seed}", 'text': text[start:end],
                'voice_ref': config['reference_wav'], 'reference_text': config['reference_text'],
                'seed': seed, 'max_tokens': settings['max_frames'], 'text_chunk_size': 1000,
                **{key: settings[key] for key in ('temperature', 'top_p', 'top_k')}})
    ordered = sorted(selections, key=lambda row: row['start'])
    if ordered[0]['end'] > ordered[1]['start']:
        raise ValueError('Quantization excerpts must be distinct and nonoverlapping')
    return {'schema': 1, 'experiment_axis': 'quantization_only', 'status': 'ready_fixed_text',
            'canonical_sha256': d.digest(source), 'selections': selections,
            'cases': cases, 'cue_condition': 'unchanged_source_no_added_cues',
            'annotation_dependency': False, 'seeds': [1729,2718,31415],
            'matched_cpu_expert_layers': 16, 'context_length': settings['context_length'],
            'production_baseline_cpu_expert_layers': config.get('drama3_cpu_expert_layers',0),
            'reference_sha256': sha256_file(config['reference_wav']),
            'source_review': 'agent_checked_exact_spans_and_complete_turns; not listening approval',
            'model_arms': ['Q3_K_experts_Q8_backbone', 'Q4_K_experts_Q8_backbone'],
            'gpu_gate': 'parent_slot_required', 'rendered': False}


def validate_quantization_manifest(source, config, manifest):
    expected = quantization_manifest(source, config, manifest.get('selections'))
    if manifest != expected:
        raise ValueError('Quantization contract changed: source, cues, seeds, reference or settings differ')
    return manifest


def bind(folder, target):
    """Explicit opt-in for a NEW existing-app job, never migration of saved audio."""
    folder, target = Path(folder), Path(target)
    status_path = folder / 'analysis_review_status.json'
    if status_path.exists() and not read(status_path).get('complete'):
        raise ValueError('Incomplete diagnostic review cannot be bound to a job')
    if not (target / 'state.json').is_file() or not (target / 'blocks.json').is_file():
        raise ValueError('Target must be an extracted app job')
    if (target / 'vibevoice_plan.json').exists() or (target / 'vibevoice_segments').exists():
        raise ValueError('Use a new job; saved narration cannot be redirected in place')
    if read(target / 'state.json').get('status') not in ('ready', 'review_required', 'canceled'):
        raise ValueError('Target must be paused and not queued/running')
    source, plan = read(folder / 'canonical.json'), read(folder / 'directions.json')
    d.validate_plan(source, plan)
    if not plan['spans']:
        raise ValueError('Analyze and review a chapter before opting in')
    # Final write_plan compares exact post-review spoken projection and refuses mismatch.
    sidecar = target / 'scene_direction.json'
    if sidecar.exists():
        raise ValueError('Existing direction sidecar retained; use another new job')
    with sidecar.open('x', encoding='utf-8') as handle:
        json.dump({'source': source, 'plan': plan}, handle, ensure_ascii=False, indent=2)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    p = sub.add_parser('chapters'); p.add_argument('job')
    p = sub.add_parser('prepare'); p.add_argument('job'); p.add_argument('output'); p.add_argument('--chapter', type=int, required=True)
    p = sub.add_parser('quantization-audition'); p.add_argument('folder'); p.add_argument('selections')
    p = sub.add_parser('revalidate'); p.add_argument('folder'); p.add_argument('output')
    for command in ('analyze','review','audition'):
        p = sub.add_parser(command); p.add_argument('folder')
        if command == 'analyze':
            p.add_argument('--gpu-slot-confirmed', action='store_true')
    p = sub.add_parser('bind'); p.add_argument('folder'); p.add_argument('new_job')
    args = parser.parse_args()
    if args.command == 'chapters':
        result = chapters(read(Path(args.job) / 'vibevoice_plan.json'))
    elif args.command == 'prepare':
        result = prepare(args.job, args.output, args.chapter)
    elif args.command == 'quantization-audition':
        folder = Path(args.folder)
        manifest = quantization_manifest(read(folder/'canonical.json'), read(folder/'baseline_config.json'), read(args.selections))
        write(folder/'quantization_manifest.json', manifest)
        result = {'status': manifest['status'], 'requests_per_quantization': len(manifest['cases']), 'rendered': False}
    elif args.command == 'analyze':
        folder = Path(args.folder)
        source, previous = read(folder / 'canonical.json'), read(folder / 'directions.json')
        # Never overwrite edited plans. Cache reuse permits resumption into a new copy.
        if previous['spans'] or previous['overrides']:
            raise ValueError('Existing analyzed/edited plan preserved; use a fresh chapter folder')
        with analysis.LocalDirector(args.gpu_slot_confirmed) as director:
            plan = analysis.analyze_source(source, folder / 'analysis_cache', director, print)
        write(folder / 'directions.json', plan)  # Only after confirmed unload.
        write(folder / 'analysis_review_status.json', {'complete': True, 'status': 'model_proposals_require_review'})
        result = review(folder)
    elif args.command == 'review':
        result = review(args.folder)
    elif args.command == 'revalidate':
        result = revalidate(args.folder, args.output)
    elif args.command == 'audition':
        result = audition(args.folder)
    else:
        bind(args.folder, args.new_job); result = {'bound': True, 'started': False}
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
