"""Install a locally supplied, checksum-pinned Drama runtime pack only."""
import argparse, hashlib, json, os, shutil, tempfile, zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def install_pack(archive_path, destination, accepted=False):
    if not accepted:raise ValueError('Review runtime vendor notices and acknowledge --accept-runtime-terms first.')
    destination=Path(destination).resolve()
    if destination.exists():raise ValueError('Runtime target exists; it will not be replaced.')
    pack=json.loads((ROOT/'install/drama3-pack.json').read_text())['runtime']['archive']
    archive_path=Path(archive_path)
    with archive_path.open('rb') as f:checksum=hashlib.file_digest(f,'sha256').hexdigest()
    if archive_path.stat().st_size!=pack['bytes'] or checksum!=pack['sha256']:raise ValueError('Runtime archive checksum or size mismatch.')
    manifest=json.loads((ROOT/'install/drama-runtime-candidate.json').read_text())
    expected={manifest['executable']['name']:manifest['executable']['sha256']}
    expected.update({i['name']:i['sha256'] for i in manifest['cuda_dlls']})
    expected.update({'notices/'+k:v for k,v in manifest['notices'].items()})
    destination.parent.mkdir(parents=True,exist_ok=True)
    stage=Path(tempfile.mkdtemp(prefix='drama-stage-',dir=destination.parent)).resolve()
    try:
        with zipfile.ZipFile(archive_path) as archive:
            if sorted(archive.namelist())!=sorted([*expected,'runtime-provenance.json']):raise ValueError('Unexpected or duplicate archive entries.')
            for name,checksum in expected.items():
                data=archive.read(name)
                if hashlib.sha256(data).hexdigest()!=checksum:raise ValueError('Runtime member checksum mismatch: '+name)
                path=stage/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data)
            if json.loads(archive.read('runtime-provenance.json'))!=manifest:raise ValueError('Provenance does not match the reviewed runtime.')
            (stage/'runtime-provenance.json').write_text(json.dumps(manifest,indent=2))
        if destination.exists():raise ValueError('Runtime destination appeared during setup; left unchanged.')
        os.rename(stage,destination)
    finally:
        if stage.exists() and stage.parent==destination.parent and stage.name.startswith('drama-stage-'):shutil.rmtree(stage)
    return destination/'audiocpp_cli.exe'
if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('archive',type=Path);p.add_argument('destination',type=Path);p.add_argument('--accept-runtime-terms',action='store_true');a=p.parse_args();print(install_pack(a.archive,a.destination,a.accept_runtime_terms))
