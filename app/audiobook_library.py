"""Filesystem ownership rules for finished audiobooks."""

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import uuid


AUDIO_SUFFIXES = {'.m4b', '.mp3', '.wav'}


def visible_audio(path):
    path = Path(path)
    return path.is_file() and not path.name.startswith('.') and path.suffix.lower() in AUDIO_SUFFIXES


def contained(path, root):
    path, root = Path(path).resolve(), Path(root).resolve()
    if path == root or root not in path.parents:
        raise ValueError('Audiobook file is outside its owned folder.')
    return path


def owned_library_directory(state, library_root, states, job_dir=None):
    raw = state.get('audiobook_dir')
    if not raw:
        return None
    directory = contained(raw, library_root)
    for other in states:
        if other.get('id') != state['id'] and other.get('audiobook_dir'):
            if Path(other['audiobook_dir']).resolve() == directory:
                raise ValueError('This output folder is shared by another job. Its files have been preserved.')
    marker = directory / '.storybird-job.json'
    if not marker.exists():
        if job_dir is None:
            raise ValueError('This legacy output folder has no ownership record.')
        outputs = Path(job_dir) / 'output'
        audio = [p for p in directory.iterdir() if visible_audio(p)]
        if not audio:
            raise ValueError('This legacy folder has no matching finished audio.')
        for path in audio:
            original = outputs / path.name
            contained(path, directory)
            contained(original, outputs)
            if not original.is_file() or _digest(path) != _digest(original):
                raise ValueError('This legacy output folder contains files that do not match this job.')
        try:
            with marker.open('x', encoding='utf-8') as handle:
                json.dump({'job_id': state['id']}, handle)
        except FileExistsError:
            pass
    try:
        owner = json.loads(marker.read_text(encoding='utf-8')).get('job_id')
    except (OSError, ValueError, AttributeError) as exc:
        raise ValueError('This output folder has an unreadable ownership record.') from exc
    if owner != state['id']:
        raise ValueError('This output folder belongs to another job.')
    return directory


def _digest(path):
    with Path(path).open('rb') as handle:
        return hashlib.file_digest(handle, 'sha256').hexdigest()


def _safe_deletion_path(path, root):
    contained(path, root)
    current = Path(path)
    while True:
        info = current.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT:
            raise ValueError('Generated files behind a symbolic link or junction were preserved.')
        if current == root:
            return
        current = current.parent


def publish_finished_output(output_dir, library_root, state):
    """Publish a complete copy to a new folder, never overwriting earlier audio."""
    source, root = Path(output_dir), Path(library_root)
    files = sorted(p for p in source.iterdir() if visible_audio(p))
    if not files:
        raise ValueError('No finished audio is available to publish.')
    for path in files:
        contained(path, source)
    root.mkdir(parents=True, exist_ok=True)
    stage = root / f'.publishing-{uuid.uuid4().hex}'
    stage.mkdir()
    staged = []
    try:
        for path in files:
            destination = stage / path.name
            staged.append(destination)
            shutil.copy2(path, destination)
        marker = stage / '.storybird-job.json'
        staged.append(marker)
        marker.write_text(json.dumps({'job_id': state['id']}), encoding='utf-8')
        title = re.sub(r'[^\w -]', '', state.get('title', '')).strip()[:150] or state['id']
        counter = 1
        while True:
            name = title if counter == 1 else f'{title} ({counter})'
            target = root / name
            if target.exists():
                counter += 1
                continue
            try:
                # Windows rename refuses an existing destination directory.
                os.rename(stage, target)
                return target
            except FileExistsError:
                counter += 1
    finally:
        if stage.exists():
            for path in staged:
                path.unlink(missing_ok=True)
            stage.rmdir()


def delete_generated_files(job_dir, state, library_root, states):
    """Delete only generated audio/checkpoints; retain source, voices and records."""
    job_dir = Path(job_dir).resolve()
    roots = [job_dir / name for name in ('output', 'output_history', 'segments',
             'vibevoice_segments', 'vibevoice_rejected')]
    book_dir = owned_library_directory(state, library_root, states, job_dir=job_dir)
    if book_dir:
        roots.append(book_dir)
    candidates = []
    for root in roots:
        if not root.exists():
            continue
        if root != book_dir:
            contained(root, job_dir)
        for path in root.rglob('*'):
            # Check every path before deleting anything, including junctions.
            _safe_deletion_path(path, root)
            if not path.is_file():
                continue
            is_checkpoint = root.name in {'segments', 'vibevoice_segments'} and path.suffix.lower() == '.json'
            if path.suffix.lower() in AUDIO_SUFFIXES or is_checkpoint:
                candidates.append((path, root))
    removed_bytes = 0
    for index, (path, root) in enumerate(candidates):
        try:
            _safe_deletion_path(path, root)
            size = path.stat().st_size
            path.unlink()
            removed_bytes += size
        except (OSError, ValueError) as exc:
            raise OSError(f'Removed {index} of {len(candidates)} generated files. The remaining files were preserved; close any player using them and retry. {exc}') from exc
    return removed_bytes
