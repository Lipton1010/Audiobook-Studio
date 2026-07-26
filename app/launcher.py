"""
Audiobook Studio desktop launcher.

Runs in the BASE conda env (same one as server.py: stdlib + fitz + requests,
plus pywebview added by the installer). Starts server.py's HTTP server on a
background thread, then opens a native desktop window pointed at it, so the
app feels like a real program instead of "open your browser to localhost".

Falls back to opening the system browser if pywebview or the OS WebView
runtime is not available (e.g. someone runs this on a machine where the
installer's webview step failed) rather than dying with no way to use the
app at all.
"""
import sys
import threading
import time
import webbrowser
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(APP_DIR))

from config import CFG  # noqa: E402
import server  # noqa: E402

WINDOW_TITLE = "Audiobook Studio"
ICON_PATH = APP_DIR / "icon.ico"


def _start_server_thread():
    t = threading.Thread(target=server.main, name="audiobook-server", daemon=True)
    t.start()
    return t


def _wait_for_server(url, timeout=20.0):
    """Poll the server instead of a fixed sleep, so a slow machine (or a first
    run that's importing torch for the first time) doesn't race the window
    opening before anything is listening."""
    import urllib.request
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            urllib.request.urlopen(url, timeout=1)
            return True
        except Exception:
            time.sleep(0.25)
    return False


def main():
    url = f"http://127.0.0.1:{CFG.port}"

    for msg in CFG.warnings():
        print(f"[launcher] WARNING: {msg}")

    _start_server_thread()
    server_up = _wait_for_server(url)
    if not server_up:
        print(f"[launcher] Server did not come up within timeout; opening {url} anyway.")

    try:
        import webview
    except ImportError:
        print("[launcher] pywebview not installed; falling back to system browser.")
        webbrowser.open(url)
        _block_forever()
        return

    try:
        window_kwargs = dict(title=WINDOW_TITLE, url=url, width=1280, height=860, min_size=(900, 600))
        webview.create_window(**window_kwargs)
        start_kwargs = {}
        if ICON_PATH.exists():
            # pywebview's pythonnet/EdgeChromium backend on Windows reads this
            # for the window/taskbar icon; harmless no-op on backends that
            # ignore it.
            start_kwargs["icon"] = str(ICON_PATH)
        webview.start(**start_kwargs)
    except Exception as e:
        # Most likely cause on Windows: the WebView2 runtime isn't installed.
        # It ships with Windows 10/11 by default, but some stripped-down or
        # older installs won't have it. Don't strand the user with no app.
        print(f"[launcher] Native window failed ({e}); falling back to system browser.")
        print("[launcher] If this keeps happening, install the WebView2 runtime:")
        print("  https://developer.microsoft.com/microsoft-edge/webview2/")
        webbrowser.open(url)
        _block_forever()


def _block_forever():
    # Keep the process alive so the background server thread keeps serving
    # after we fall back to a browser tab (no window to keep the process up).
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
