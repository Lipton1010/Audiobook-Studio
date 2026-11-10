"""Build the reviewed optional Drama runtime archive. No weights or user files."""
import argparse, hashlib, json, zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def digest(path):
    with path.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()
def build(source, output):
    manifest=json.loads((ROOT/'install/drama-runtime-candidate.json').read_text())
    entries={manifest['executable']['name']:manifest['executable']['sha256']}
    entries.update({i['name']:i['sha256'] for i in manifest['cuda_dlls']})
    entries.update({'notices/'+k:v for k,v in manifest['notices'].items()})
    for name,expected in entries.items():
        path=source/name
        if not path.is_file() or digest(path)!=expected:raise ValueError('Missing or altered reviewed pack file: '+name)
    if output.exists():raise ValueError('Output already exists; retain it rather than overwriting.')
    output.parent.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(output,'x',compression=zipfile.ZIP_DEFLATED,compresslevel=6) as archive:
        for name in sorted(entries):archive.write(source/name,name)
        archive.writestr('runtime-provenance.json',json.dumps(manifest,indent=2))
    result={'filename':output.name,'bytes':output.stat().st_size,'sha256':digest(output),'source_revision':manifest['source_revision'],'contains_model_weights':False}
    output.with_suffix('.manifest.json').write_text(json.dumps(result,indent=2))
    return result
if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('source',type=Path);p.add_argument('output',type=Path);a=p.parse_args();print(json.dumps(build(a.source,a.output),indent=2))
