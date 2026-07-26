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
import atexit
import socket
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


def _kill_orphan_workers():
    """Kill narration subprocesses on the way out.

    server.py spawns narrate_worker.py with Popen, and Windows does NOT kill
    children when the parent dies. server.mark_interrupted_jobs() reaps them on
    the NEXT launch, which was tolerable when this was a console app: closing a
    console is a deliberate act. A window with an X in the corner gets closed
    casually, mid-narration, and until the next launch the orphan keeps a
    Chatterbox model resident and the GPU pegged with nothing to show for it.

    Kill the live handles first (fast, no dependency on the pid file being
    current), then sweep every job's worker_pids.txt for anything missed.
    """
    for p in list(server._active_procs.get("procs") or []):
        try:
            if p.poll() is None:
                p.kill()
        except Exception:
            pass
    try:
        for job_dir in server.JOBS_DIR.iterdir():
            if job_dir.is_dir():
                server._reap_worker_pids(job_dir)
    except Exception:
        pass


def _port_in_use(port):
    """True if something is already listening on the app's port. Without this
    check a second launch raises WinError 10048 inside the server thread, and
    the window then silently attaches to the FIRST instance's server, which
    looks like it worked until two windows start fighting over one job queue."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


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

    already_running = _port_in_use(CFG.port)
    if already_running:
        # Don't start a second server or reap the first one's workers; just
        # surface the instance that's already there.
        print(f"[launcher] Audiobook Studio is already running at {url}; "
              "opening a window onto the existing instance.")
    else:
        # server.main() prints these itself; don't double up.
        atexit.register(_kill_orphan_workers)
        _start_server_thread()
        if not _wait_for_server(url):
            print(f"[launcher] Server did not come up within timeout; opening {url} anyway.")

    try:
        import webview
    except ImportError:
        print("[launcher] pywebview not installed; falling back to system browser.")
        print("  Install it in the base env with:  pip install pywebview==5.4")
        webbrowser.open(url)
        _block_forever()
        return

    try:
        webview.create_window(title=WINDOW_TITLE, url=url,
                              width=1280, height=860, min_size=(900, 600))
        # NOTE: webview.start(icon=...) is accepted but IGNORED on Windows --
        # pywebview 5.4 documents it as GTK/QT only, so the window shows the
        # default Python icon. Passing it anyway is harmless and becomes
        # correct if that ever changes; the Start Menu shortcut carries
        # app/icon.ico regardless, which is what the user actually sees.
        start_kwargs = {}
        if ICON_PATH.exists():
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
    print("\n  Audiobook Studio is running in your browser.")
    print("  Leave this window open while you use it. Close it (or press Ctrl+C)")
    print("  when you're done.\n")
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
