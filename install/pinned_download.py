"""Anonymous pinned downloads: resumable, checksum verified, no ambient credentials."""
import hashlib, os, re, urllib.request
from pathlib import Path

def download(url, target, sha256, size=None, opener=urllib.request.urlopen):
    if not url.startswith('https://'):raise ValueError('HTTPS download required')
    target=Path(target)
    if target.is_symlink():raise ValueError('Download destination must not be a symlink')
    def verified(path):
        if size is not None and path.stat().st_size!=size:return False
        with path.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()==sha256
    if target.exists():
        if verified(target):return target
        raise ValueError('Existing file differs; it was not replaced: '+str(target))
    target.parent.mkdir(parents=True,exist_ok=True)
    part=target.with_name(target.name+'.part')
    if part.is_symlink():raise ValueError('Partial download must not be a symlink')
    offset=part.stat().st_size if part.exists() else 0
    if size is not None and offset>size:raise ValueError('Partial download is larger than the pinned file')
    if size is not None and offset==size:
        if not verified(part):raise ValueError('Partial file checksum mismatch; remove it explicitly before retrying')
        os.rename(part,target);return target
    request=urllib.request.Request(url,headers={'Range':f'bytes={offset}-'} if offset else {})
    with opener(request,timeout=60) as response:
        if not response.geturl().startswith('https://'):raise ValueError('Insecure download redirect refused')
        status=response.status
        if status==206:
            match=re.fullmatch(r'bytes (\d+)-(\d+)/(\d+)',response.headers.get('Content-Range',''))
            if not match or int(match[1])!=offset or (size is not None and int(match[3])!=size):raise ValueError('Invalid resume range')
            mode='ab'
        elif status==200:
            mode='wb';offset=0
        else:raise ValueError(f'Download failed: HTTP {status}')
        with part.open(mode) as stream:
            total=offset
            while chunk:=response.read(1024*1024):
                total+=len(chunk)
                if total>(size if size is not None else 16*1024*1024):raise ValueError('Download exceeds expected size limit')
                stream.write(chunk)
    if not verified(part):raise ValueError('Download checksum or size mismatch; partial file retained for inspection')
    if target.exists():raise ValueError('Destination appeared during download; left unchanged')
    os.rename(part,target)
    return target
