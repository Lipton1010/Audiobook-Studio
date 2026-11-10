"""Explicit Drama pack provisioning. No changes to existing jobs or narrator defaults."""
import argparse, hashlib, json, shutil, subprocess, sys, tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'app'))
from model_hardware import inventory, describe, require_generation_capacity
from pinned_download import download
from install_drama_runtime_pack import install_pack
from bootstrap_drama3 import register
import drama3

def check_setup_capacity(machine):
    """Setup does not load either model; generation rechecks free memory later."""
    gpu=machine.get('selected_gpu')
    if not gpu or gpu.get('compute_capability')!='8.9':raise RuntimeError('This pack requires a verified Ada NVIDIA GPU (CUDA capability 8.9).')
    if gpu.get('total_gib',0)<20 or (machine.get('ram_gib') or 0)<30:raise RuntimeError('This pack currently targets at least 20 GiB total VRAM and approximately 32 GB installed RAM; these are admission estimates, not compatibility guarantees.')
    if (machine.get('free_ram_gib') or 0)<4:raise RuntimeError('Setup requires at least 4 GiB currently free RAM for archive/dependency installation.')
    if gpu.get('free_gib',0)<20 or machine['free_ram_gib']<22:print('Models will not be loaded during setup. Generation remains paused until 20 GiB VRAM and 22 GiB host RAM are free.')

def provision(runtime_root, archive=None, existing_model=None, checker_python=None, checker_model=None):
    if bool(checker_python)!=bool(checker_model):raise ValueError("Supply both existing checker paths or neither.")
    root=Path(runtime_root).resolve();check=root
    while not check.exists():check=check.parent
    machine=inventory(check);print(describe(machine));check_setup_capacity(machine)
    if shutil.disk_usage(check).free<50*1024**3:raise ValueError('Keep 50 GiB free for optional models, runtimes and download cache (estimate).')
    manifest=json.loads((ROOT/'install/drama3-pack.json').read_text());runtime=manifest['runtime']
    if not archive and not runtime.get('download_url') and not (root/'drama3-native').exists():raise ValueError('The reviewed runtime release URL is not published yet. Select the verified local runtime ZIP, or wait for the prerelease.')
    target=root/'drama3-native'
    if target.exists():
        reviewed=json.loads((ROOT/'install/drama-runtime-candidate.json').read_text())
        pins={reviewed['executable']['name']:reviewed['executable']['sha256']}
        pins.update({i['name']:i['sha256'] for i in reviewed['cuda_dlls']})
        pins.update({'notices/'+k:v for k,v in reviewed['notices'].items()})
        for name,checksum in pins.items():
            path=target/name
            if not path.is_file() or drama3.sha256_file(path)!=checksum:raise ValueError('Existing runtime differs; left unchanged. Configure it separately.')
    cache=root/'downloads'
    if archive is None and not target.exists():
        pin=runtime['archive'];archive=download(runtime['download_url'],cache/pin['filename'],pin['sha256'],pin['bytes'])
    executable=(target/'audiocpp_cli.exe') if target.exists() else install_pack(archive,target,accepted=True)
    model=manifest['model'];base=f"https://huggingface.co/{model['repo']}/resolve/{model['revision']}/"
    model_dir=root/'models/drama3';model_path=Path(existing_model).resolve() if existing_model else model_dir/model['filename']
    if existing_model:
        if not model_path.is_file() or model_path.stat().st_size!=model['bytes'] or drama3.sha256_file(model_path)!=model['sha256']:raise ValueError('Supplied Drama model is not the pinned artifact')
    else:download(base+model['filename'],model_path,model['sha256'],model['bytes'])
    for name,checksum in manifest['notices'].items():download(base+name,model_dir/name,checksum)
    with tempfile.TemporaryDirectory(prefix='drama-checker-',dir=root) as temp:
        config=Path(temp)/'paths.json'
        command=[sys.executable,str(ROOT/'install/bootstrap_parakeet.py'),'--accept-model-terms','--runtime-root',str(root),'--config',str(config)]
        if checker_python:
            command+=['--configure-existing','--python',str(checker_python),'--model-dir',str(checker_model)]
        elif (root/'parakeet').exists():
            command+=['--configure-existing','--python',str(root/'parakeet/python.exe'),'--model-dir',str(root/'models/parakeet-tdt-0.6b-v3')]
        else:command+=['--install']
        subprocess.run(command,check=True)
        checker=json.loads(config.read_text())
    settings={'drama3_executable':str(executable),'drama3_model':str(model_path),'drama3_cuda_bin':str(target),'parakeet_python':checker['parakeet_python'],'parakeet_model':checker['parakeet_model'],'drama3_cpu_expert_layers':12}
    drama3.assets(settings,verify=True)
    return settings

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--runtime-root',type=Path,default=ROOT/'runtime');p.add_argument('--runtime-archive',type=Path);p.add_argument('--existing-model',type=Path);p.add_argument('--checker-python',type=Path);p.add_argument('--checker-model',type=Path);p.add_argument('--config',type=Path,default=ROOT/'app/config.json');p.add_argument('--accept-model-terms',action='store_true');p.add_argument('--accept-runtime-terms',action='store_true');a=p.parse_args()
    if not(a.accept_model_terms and a.accept_runtime_terms):p.error('Review Fish Audio, NVIDIA Parakeet CC-BY-4.0 and runtime/vendor notices; explicit model and runtime acknowledgments are required.')
    if a.config.exists():json.loads(a.config.read_text(encoding='utf-8'))
    settings=provision(a.runtime_root,a.runtime_archive,a.existing_model,a.checker_python,a.checker_model);register(a.config,settings)
    print('Drama runtime paths saved. Existing jobs and narrator defaults are unchanged.')
if __name__=='__main__':main()
