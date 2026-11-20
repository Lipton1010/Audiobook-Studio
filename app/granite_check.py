import array
import base64
import io
import json
from pathlib import Path
import shutil
import subprocess
import urllib.request
import wave

MODEL = 'ibm/granite5-speech:2b'
REVISION = 'ollama-q8_0'
BASE = 'http://127.0.0.1:11434/api/'
def ffmpeg_path():
    return shutil.which('ffmpeg') or (str(p) if (p:=Path('C:/ProgramData/chocolatey/bin/ffmpeg.exe')).is_file() else None)
RATE = 16000

def request(path, payload=None):
    data = None if payload is None else json.dumps(payload).encode()
    req = urllib.request.Request(BASE+path, data=data, headers={'Content-Type':'application/json'})
    with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req, timeout=90 if data else 5) as response:
        return json.load(response)

def setup_error():
    if not ffmpeg_path():
        return 'Granite Speech needs FFmpeg on PATH.'
    try:
        if MODEL not in {r['name'] for r in request('tags')['models']}:
            return f'Install the local checker with ollama pull {MODEL}.'
    except (OSError, ValueError, KeyError):
        return 'Granite Speech cannot reach local Ollama. Start Ollama, then retry.'
    return None

def chunks(raw):
    pcm = array.array('h'); pcm.frombytes(raw)
    start = 0
    while len(pcm)-start > 27*RATE:
        candidates=range(start+22*RATE,start+27*RATE,RATE//10)
        end=min(candidates,key=lambda i:sum(abs(x) for x in pcm[i-800:i+800]))
        yield pcm[start:end].tobytes()
        start=end
    if start < len(pcm): yield pcm[start:].tobytes()

def close():
    try:
        request('generate',dict(model=MODEL,keep_alive=0))
    except (OSError,ValueError):
        print('Could not confirm Granite unloaded; check ollama ps before another GPU workload.',flush=True)

def load():
    issue=setup_error()
    ffmpeg=ffmpeg_path()
    if issue: raise RuntimeError(issue)
    if any(row.get('name') != MODEL for row in request('ps').get('models', [])):
        raise RuntimeError('Granite check requires a free GPU. Stop the other local Ollama model before checking.')
    def transcribe(batch):
        results=[]
        for row in batch:
            raw=subprocess.run([ffmpeg,'-v','error','-nostdin','-i',str(row['audio']),'-ac','1','-ar',str(RATE),'-f','s16le','pipe:1'],check=True,capture_output=True,timeout=90).stdout
            if not raw: raise RuntimeError('Granite received empty audio')
            parts=[]
            for pcm in chunks(raw):
                fp=io.BytesIO()
                with wave.open(fp,'wb') as out:
                    out.setparams((1,2,RATE,0,'NONE','not compressed'));out.writeframes(pcm)
                encoded=base64.b64encode(fp.getvalue()).decode()
                # Never give the expected book wording to the recognizer.
                msg=dict(role='user',content='Transcribe the speech verbatim.',images=[encoded])
                result=request('chat',dict(model=MODEL,stream=False,keep_alive='3m',messages=[msg],options=dict(temperature=0,num_predict=512,num_ctx=4096)))
                text=result.get('message',{}).get('content','').strip()
                if not text or result.get('done_reason')=='length': raise RuntimeError('Granite output incomplete; retain the audio for review.')
                parts.append(text)
            results.append(' '.join(parts))
        return results
    return transcribe
