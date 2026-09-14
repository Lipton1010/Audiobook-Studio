"""Provision isolated narration runtimes, or verify and register existing ones."""

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))
from app.managed_runtime import configure_managed_runtime

SOURCE_REVISION = '952326ddb264062466a888cf32a5b2f4e803e16e'
MODEL_ID = 'microsoft/VibeVoice-1.5B'
MODEL_REVISION = 'c00898d257e6b46004e3e2866a47534085fb685a'
TOKENIZER_REVISION = '8faed761d45a263340a0528343f099c05c9a4323'
QUALITY_REVISION = 'edaa852ec7e145841d8ffdb056a99866b5f0a478'


def run(command, **kwargs):
    return subprocess.run([str(x) for x in command], check=True, **kwargs)


def validate_models(model_dir, quality_model):
    model_dir, quality_model = Path(model_dir), Path(quality_model)
    index = model_dir / 'model.safetensors.index.json'
    if not index.is_file():
        raise ValueError(f'Model index missing: {index}')
    shards = set(json.loads(index.read_text(encoding='utf-8'))['weight_map'].values())
    for filename in ['config.json', 'preprocessor_config.json', *shards]:
        path = model_dir / filename
        if path.parent != model_dir or not path.is_file() or path.stat().st_size == 0:
            raise ValueError(f'Model file missing or invalid: {path}')
    config = json.loads((model_dir / 'config.json').read_text(encoding='utf-8'))
    if config.get('decoder_config', {}).get('hidden_size') != 1536:
        raise ValueError('Expected VibeVoice 1.5B TTS weights; check model selection.')
    for filename in ['model.bin', 'config.json', 'tokenizer.json']:
        path = quality_model / filename
        if not path.is_file() or path.stat().st_size == 0:
            raise ValueError(f'Quality model file missing: {path}')


def verify(python, model_dir, cache_dir, quality_python, quality_model):
    validate_models(model_dir, quality_model)
    env = dict(os.environ, HF_HOME=str(cache_dir), HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1')
    code = (
        'import sys,torch,transformers,numpy,scipy,soundfile,pyloudnorm;'
        'from vibevoice.modular.modeling_vibevoice_inference import VibeVoiceForConditionalGenerationInference;'
        'from vibevoice.processor.vibevoice_processor import VibeVoiceProcessor;'
        'assert transformers.__version__=="4.51.3", "Expected transformers 4.51.3";'
        'p=VibeVoiceProcessor.from_pretrained(sys.argv[1],revision=sys.argv[2],local_files_only=True);'
        'assert p._parse_script("Speaker 0: The test is complete.")[0][1].strip()=="The test is complete.";'
        'print("VibeVoice imports, cached tokenizer, and input parser verified.")'
    )
    run([python, '-c', code, model_dir, TOKENIZER_REVISION], env=env, timeout=120)
    run([quality_python, '-c', 'from faster_whisper import WhisperModel; print("CPU quality checker imports verified.")'], timeout=60)


def register(config_path, values):
    config_path = Path(config_path)
    data = json.loads(config_path.read_text(encoding='utf-8')) if config_path.exists() else {}
    if not isinstance(data, dict):
        raise ValueError('Existing app config must be a JSON object; it was not modified.')
    data.update({key: str(Path(value).resolve()) for key, value in values.items()})
    config_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = config_path.with_name(config_path.name + f'.tmp{os.getpid()}')
    temporary.write_text(json.dumps(data, indent=2) + '\n', encoding='utf-8')
    os.replace(temporary, config_path)


def create_environment(conda, prefix, kind):
    prefix = Path(prefix).resolve()
    python = prefix / ('python.exe' if os.name == 'nt' else 'bin/python')
    marker = prefix / '.storybird-runtime.json'
    identity = {'kind': kind, 'python': '3.11'}
    staging = prefix.with_name(prefix.name + '.storybird-provisioning.json')

    def staged_by_us():
        try:
            return json.loads(staging.read_text(encoding='utf-8')) == {
                **identity, 'prefix': str(prefix)}
        except (OSError, json.JSONDecodeError):
            return False

    def marker_matches():
        try:
            return marker.is_file() and json.loads(marker.read_text(encoding='utf-8')) == identity
        except (OSError, json.JSONDecodeError):
            return False

    if python.exists() and marker_matches() and not staging.exists():
        return python

    if prefix.exists() and any(prefix.iterdir()):
        if not staged_by_us():
            raise ValueError(f'Refusing to modify an unowned environment: {prefix}. Use --configure-existing.')
        # A staging claim is written before conda starts. It is the proof that
        # this exact incomplete prefix belongs to this application, never a
        # user's unrelated environment.
        shutil.rmtree(prefix)
    prefix.parent.mkdir(parents=True, exist_ok=True)
    staging.write_text(json.dumps({**identity, 'prefix': str(prefix)}), encoding='utf-8')
    try:
        run([conda, 'create', '--yes', '--prefix', prefix, 'python=3.11', '--override-channels', '--channel', 'conda-forge'])
        if not python.exists():
            raise ValueError(f'Conda did not create the expected interpreter: {python}')
        marker.write_text(json.dumps(identity), encoding='utf-8')
    except Exception:
        # Preserve the staging record so a later run can safely clean only the
        # app-owned partial prefix.
        raise
    staging.unlink(missing_ok=True)
    return python


def download_models(model_dir, cache_dir, quality_model):
    from huggingface_hub import snapshot_download
    snapshot_download(MODEL_ID, revision=MODEL_REVISION, local_dir=str(model_dir),
                      cache_dir=str(Path(cache_dir) / 'hub'), allow_patterns=['*.json', '*.safetensors'])
    snapshot_download('Qwen/Qwen2.5-1.5B', revision=TOKENIZER_REVISION,
                      cache_dir=str(Path(cache_dir) / 'hub'), allow_patterns=['*.json', '*.txt', '*.model'])
    snapshot_download('Systran/faster-whisper-large-v3', revision=QUALITY_REVISION,
                      local_dir=str(quality_model), cache_dir=str(Path(cache_dir) / 'hub'),
                      allow_patterns=['model.bin', '*.json', 'vocabulary.*'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--install', action='store_true', help='Download and install into new, dedicated runtimes.')
    mode.add_argument('--configure-existing', action='store_true', help='Verify supplied runtimes and record their paths.')
    mode.add_argument('--check-only', action='store_true', help='Verify paths and imports without writing configuration.')
    mode.add_argument('--download-models', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--runtime-root', type=Path, default=REPO / 'runtime')
    parser.add_argument('--conda')
    parser.add_argument('--python', type=Path)
    parser.add_argument('--model-dir', type=Path)
    parser.add_argument('--cache-dir', type=Path)
    parser.add_argument('--quality-python', type=Path)
    parser.add_argument('--quality-model', type=Path)
    parser.add_argument('--config', type=Path, default=REPO / 'app/config.json')
    args = parser.parse_args()
    runtime = args.runtime_root.resolve()
    model = args.model_dir or runtime / 'models/VibeVoice-1.5B'
    cache = args.cache_dir or runtime / 'cache/huggingface'
    quality_model = args.quality_model or runtime / 'models/faster-whisper-large-v3'
    if args.download_models:
        download_models(model, cache, quality_model)
        return
    python, quality_python = args.python, args.quality_python
    if args.install:
        if python or quality_python:
            parser.error('--install creates its own environments; use --configure-existing for supplied interpreters.')
        conda = args.conda or shutil.which('conda')
        if not conda:
            candidate = runtime / 'miniconda3/Scripts/conda.exe'
            conda = str(candidate) if candidate.is_file() else None
        if not conda:
            raise ValueError('Conda was not found. Supply --conda with the installed conda executable.')
        configure_managed_runtime(runtime, create_dirs=True)
        python = create_environment(conda, runtime / 'vibevoice', 'vibevoice')
        quality_python = create_environment(conda, runtime / 'quality', 'quality')
        run([python, '-m', 'pip', 'install', 'torch==2.6.0+cu124', 'torchaudio==2.6.0+cu124',
             '--index-url', 'https://download.pytorch.org/whl/cu124'])
        run([python, '-m', 'pip', 'install', '-r', REPO / 'install/requirements-vibevoice.txt'])
        run([python, '-m', 'pip', 'install', '--no-deps',
             f'https://github.com/vibevoice-community/VibeVoice/archive/{SOURCE_REVISION}.zip'])
        run([quality_python, '-m', 'pip', 'install', '-r', REPO / 'install/requirements-narration-quality.txt'])
        run([python, __file__, '--download-models', '--model-dir', model,
             '--cache-dir', cache, '--quality-model', quality_model])
    if not python or not quality_python:
        parser.error('--python and --quality-python are required for existing runtimes.')
    verify(python, model, cache, quality_python, quality_model)
    if not args.check_only:
        register(args.config, {'vibevoice_python': python, 'vibevoice_model_dir': model,
                 'vibevoice_cache_dir': cache, 'vibevoice_quality_python': quality_python,
                 'vibevoice_quality_model': quality_model})
        print(f'Runtime paths recorded in {args.config}. Existing jobs and other environments are unchanged.')


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        print(f'VibeVoice setup failed: {exc}', file=sys.stderr)
        sys.exit(1)
