"""Opt-in, pinned Microsoft WebView2 prerequisite. Never installed on app launch."""
import argparse
import ctypes
import platform
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'app'))
sys.path.insert(0, str(ROOT / 'install'))
from webview_runtime import runtime_version
from pinned_download import download

URL = 'https://msedge.sf.dl.delivery.mp.microsoft.com/filestreamingservice/files/199041ce-790a-4bbc-9111-b81b4c926e9f/MicrosoftEdgeWebView2RuntimeInstallerX64.exe'
SHA256 = '1be9d2926954d99dd62653a22efe813160fe0c40f1e422b44e6aaf5473f68eec'
SIZE = 214990032
TERMS = 'https://developer.microsoft.com/en-us/microsoft-edge/webview2/#download-section'
PRIVACY = 'https://learn.microsoft.com/en-us/microsoft-edge/webview2/concepts/data-privacy'


def ensure_runtime(*, accept_terms=False, cache=None):
    if sys.platform != 'win32':
        return None
    import webview
    version = runtime_version(webview)
    if version:
        print('Existing WebView2 runtime: ' + version)
        return version
    if not accept_terms:
        raise RuntimeError('WebView2 is required for the native app. Review Microsoft terms at ' + TERMS +
                           ' (choose x64), then rerun setup with --accept-webview2-terms or install it yourself. '
                           '--yes is not consent. No WebView2 download was started.')
    if platform.machine().lower() not in ('amd64', 'x86_64') or ctypes.sizeof(ctypes.c_void_p) != 8:
        raise RuntimeError('This pinned installer supports Windows x64 only.')
    if ctypes.windll.shell32.IsUserAnAdmin():
        raise RuntimeError('Run setup without administrator privileges; automatic machine-wide installation is not requested.')
    target = Path(cache or ROOT / 'runtime' / 'downloads') / ('webview2-' + SHA256[:12] + '-x64.exe')
    installer = download(URL, target, SHA256, SIZE)
    # Exact reviewed signed Microsoft bytes; no moving latest alias or ambient credentials.
    result = subprocess.run([str(installer), '/silent', '/install'], timeout=600)
    if result.returncode != 0:
        raise RuntimeError(f'Microsoft WebView2 installer returned {result.returncode}; see Microsoft installer diagnostics.')
    version = runtime_version(webview)
    if not version:
        raise RuntimeError('WebView2 installation completed but the native loader still cannot find a runtime. Restart Windows or contact support.')
    print('Verified WebView2 runtime: ' + version)
    return version


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--accept-webview2-terms', action='store_true')
    parser.add_argument('--cache', type=Path)
    args = parser.parse_args()
    try:
        ensure_runtime(accept_terms=args.accept_webview2_terms, cache=args.cache)
    except Exception as exc:
        print('[FAIL] ' + str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
