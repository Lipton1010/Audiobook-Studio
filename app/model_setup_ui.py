"""Launch optional model setup only from an explicit same-origin local UI action."""
import ipaddress
import os
from pathlib import Path
import subprocess
import sys
import threading

_LOCK = threading.Lock()
_PROCESS = None

def authorized(headers, client_ip, port):
    try:
        if not ipaddress.ip_address(client_ip).is_loopback:
            return False
    except ValueError:
        return False
    if headers.get('X-Storybird-Action') != 'model-setup':
        return False
    host = headers.get('Host', '')
    if host not in {f'localhost:{port}', f'127.0.0.1:{port}', f'[::1]:{port}'}:
        return False
    origin = headers.get('Origin')
    return not origin or origin == 'http://' + host

def launch(repo):
    global _PROCESS
    if os.name != 'nt':
        raise RuntimeError('Optional runtime setup currently supports Windows only.')
    script = Path(repo) / 'install/model_setup.py'
    if not script.is_file():
        raise RuntimeError('Optional model setup is missing. Reinstall the current application package.')
    with _LOCK:
        if _PROCESS is not None and _PROCESS.poll() is None:
            return False
        _PROCESS = subprocess.Popen([sys.executable, str(script)], cwd=str(repo),
                                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    return True
