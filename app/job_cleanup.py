"""Preview completed-job working files; remove only an explicitly confirmed preview.

Completion may create a preview automatically. It never grants deletion approval.
Models, sources, voices, final exports, JSON receipts and the main job log are excluded.
"""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time
import uuid

from audiobook_library import _safe_deletion_path, visible_audio

ROOTS = ('segments', 'vibevoice_segments', 'vibevoice_rejected', 'drama3_runs')
POLICY = 'completed_working_files_v1'


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def write(path, value):
    temporary = path.with_name(path.name + '.tmp-' + uuid.uuid4().hex)
    try:
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def allocation(path, info):
    if os.name != 'nt':
        return getattr(info, 'st_blocks', (info.st_size + 511) // 512) * 512
    import ctypes
    from ctypes import wintypes
    class StandardInfo(ctypes.Structure):
        _fields_ = [('allocated', ctypes.c_longlong), ('end', ctypes.c_longlong),
                    ('links', wintypes.DWORD), ('pending', ctypes.c_ubyte), ('directory', ctypes.c_ubyte)]
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
                                  wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.GetFileInformationByHandleEx.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.CreateFileW(str(path), 0x80, 7, None, 3, 0x00200000, None)
    if handle == wintypes.HANDLE(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        value = StandardInfo()
        if not kernel.GetFileInformationByHandleEx(handle, 1, ctypes.byref(value), ctypes.sizeof(value)):
            raise ctypes.WinError(ctypes.get_last_error())
        return value.allocated
    finally:
        kernel.CloseHandle(handle)


def validate_audio(path, ffmpeg):
    if not ffmpeg:
        raise ValueError('FFmpeg is required to validate the finished audiobook before cleanup.')
    result = subprocess.run([str(ffmpeg), '-nostdin', '-v', 'error', '-xerror', '-threads', '1', '-i', str(path),
                             '-map', '0:a:0', '-progress', 'pipe:1', '-f', 'null', '-'],
                            capture_output=True, text=True, timeout=300)
    times = [int(line.split('=', 1)[1]) for line in result.stdout.splitlines()
             if line.startswith('out_time_us=') and line.split('=', 1)[1].lstrip('-').isdigit()]
    if result.returncode or max(times, default=0) <= 0:
        raise ValueError('Finished audio did not pass a complete decode; working files were preserved.')
    return max(times) / 1_000_000


def _protected(job, state):
    paths = set()
    def visit(value):
        if isinstance(value, dict):
            for child in value.values(): visit(child)
        elif isinstance(value, list):
            for child in value: visit(child)
        elif isinstance(value, str):
            path = Path(value)
            if path.is_absolute():
                try:
                    if path.is_file(): paths.add(path.resolve())
                except OSError:
                    pass
    visit(state)
    for name in ('vibevoice_config.json', 'drama3_reference_request.json'):
        if (job / name).exists(): visit(read(job / name))
    return paths, {(p.stat().st_dev, p.stat().st_ino) for p in paths}


def preview(job, state, ffmpeg, *, verifier=None):
    """Read-only plan. A completed status alone is insufficient to permit cleanup."""
    job = Path(job)
    if state.get('status') != 'done':
        raise ValueError('Cleanup is only available for completed jobs.')
    if (job / 'narration_review.json').exists():
        review = read(job / 'narration_review.json')
        if review.get('passages', [review]):
            raise ValueError('Narration review must be resolved before cleanup.')
    output = job / 'output'
    _safe_deletion_path(output, job)
    finals = sorted(p for p in output.iterdir() if visible_audio(p))
    if not finals:
        raise ValueError('No finished audiobook exists; working files were preserved.')
    library = Path(state['audiobook_dir']) if state.get('audiobook_dir') else None
    if library:
        if read(library / '.storybird-job.json').get('job_id') != state.get('id'):
            raise ValueError('Finished library ownership does not match this job.')
        if {p.name for p in library.iterdir() if visible_audio(p)} != {p.name for p in finals}:
            raise ValueError('Finished library copy is incomplete; working files were preserved.')
    validated = []
    for path in finals:
        _safe_deletion_path(path, job)
        seconds = (verifier or validate_audio)(path, ffmpeg)
        info = path.stat(); fingerprint = digest(path)
        if library and digest(library / path.name) != fingerprint:
            raise ValueError('Finished library copy differs; working files were preserved.')
        validated.append({'path': str(path), 'bytes': info.st_size, 'mtime_ns': info.st_mtime_ns,
                          'sha256': fingerprint, 'decoded_seconds': seconds})
    protected, protected_ids = _protected(job, state)
    entries = []
    for name in ROOTS:
        root = job / name
        if not root.exists(): continue
        _safe_deletion_path(root, job)
        for folder, dirs, files in os.walk(root, followlinks=False):
            for directory in dirs:
                _safe_deletion_path(Path(folder) / directory, job)
            for filename in files:
                path = Path(folder) / filename
                is_audio = path.suffix.lower() == '.wav'
                is_native_log = name == 'drama3_runs' and filename == 'native.log'
                if not (is_audio or is_native_log): continue
                _safe_deletion_path(path, job)
                info = path.stat(); identity = (info.st_dev, info.st_ino)
                if path.resolve() in protected or identity in protected_ids:
                    continue
                if is_audio and any(word in filename.lower() for word in ('voice', 'reference', 'original')):
                    continue
                entries.append({'relative': str(path.relative_to(job)), 'bytes': info.st_size,
                                'allocated_bytes': allocation(path, info), 'links': info.st_nlink,
                                'identity': list(identity), 'mtime_ns': info.st_mtime_ns, 'sha256': digest(path),
                                'reason': 'completed native diagnostic log' if is_native_log else 'completed render working audio'})
    entries.sort(key=lambda row: row['relative'])
    proof = {'policy': POLICY, 'job_id': state.get('id'), 'finals': validated, 'files': entries}
    token = hashlib.sha256(json.dumps(proof, sort_keys=True).encode()).hexdigest()
    return {**proof, 'token': token, 'created_at': time.time(), 'files_count': len(entries),
            'bytes': sum(row['bytes'] for row in entries),
            'reclaimable_allocated_bytes': sum(row['allocated_bytes'] for row in entries if row['links'] == 1),
            'manual_confirmation_required': True, 'automatic_deletion': False,
            'retained': 'Originals, models, voices/references, final audio, extraction, JSON plans/receipts, reviews and main job log.',
            'consequence': 'Removing working audio prevents clip-level repair/resume from that audio; new rendering will be needed.'}


def remove_preview(job, state, token, ffmpeg, *, confirmed=False):
    if confirmed is not True or not token:
        raise ValueError('Review a fresh cleanup preview and explicitly confirm it first.')
    job = Path(job)
    plan = preview(job, state, ffmpeg)
    if token != plan['token']:
        raise ValueError('Files or finished audio changed. Review a new cleanup preview; nothing was removed.')
    # Validate the entire set before removing its first file.
    for row in plan['files']:
        path = job / row['relative']
        _safe_deletion_path(path, job)
        info = path.stat()
        if [info.st_dev, info.st_ino] != row['identity'] or info.st_mtime_ns != row['mtime_ns']:
            raise ValueError('Working files changed; nothing was removed.')
    ledger = {'policy': POLICY, 'preview_token': token, 'started_at': time.time(),
              'approved_files': plan['files'], 'removed': [], 'complete': False}
    ledger_dir = job / 'cleanup_history'
    ledger_dir.mkdir(exist_ok=True)
    ledger_path = ledger_dir / (uuid.uuid4().hex + '.json')
    write(ledger_path, ledger)  # Persist consent/scope before the first unlink.
    try:
        for row in plan['files']:
            path = job / row['relative']
            _safe_deletion_path(path, job)
            path.unlink()
            ledger['removed'].append(row)
        ledger['complete'] = True
        return sum(row['bytes'] for row in ledger['removed'])
    finally:
        ledger['finished_at'] = time.time()
        write(ledger_path, ledger)
