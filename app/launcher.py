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
import json
import socket
import sys
import threading
import time
import traceback
import urllib.request
import webbrowser
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(APP_DIR))

from config import CFG  # noqa: E402
import server  # noqa: E402

WINDOW_TITLE = "Audiobook Studio"
ICON_PATH = APP_DIR / "icon.ico"
# Under the installer there is no console to read, so anything worth debugging
# has to land in a file the user can be asked for by name.
LOG_PATH = APP_DIR.parent / "launcher_log.txt"

_server_error = {"trace": None}


def _log(msg):
    print(msg)
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(time.strftime("%Y-%m-%d %H:%M:%S ") + msg + "\n")
    except Exception:
        pass


def _show_error(title, msg):
    """Put a failure in front of the user instead of leaving them with a blank
    window. Falls back to stdout where MessageBox is unavailable."""
    _log(f"[launcher] {title}: {msg}")
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, msg, title, 0x10)
    except Exception:
        print(f"\n*** {title} ***\n{msg}\n")


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


def _is_our_app(url, timeout=1.0):
    """True only if AUDIOBOOK STUDIO is answering on this port.

    A successful TCP connect proves something is listening, not that it is us.
    Any unrelated dev server, printer utility or corporate agent can hold 8765,
    and the old check accepted all of them: the window then opened onto a
    stranger's page, or a blank one, with no explanation. Ask for an endpoint
    only this app serves and check the shape of the reply."""
    try:
        with urllib.request.urlopen(url + "/api/jobs", timeout=timeout) as r:
            body = json.loads(r.read().decode("utf-8", "replace"))
        return isinstance(body, dict) and "jobs" in body
    except Exception:
        return False


def _start_server_thread():
    def _run():
        try:
            server.main()
        except Exception:
            # Previously this died silently inside the thread and the launcher
            # went on to open a URL that would never answer.
            _server_error["trace"] = traceback.format_exc()
            _log("[launcher] SERVER THREAD DIED:\n" + _server_error["trace"])

    t = threading.Thread(target=_run, name="audiobook-server", daemon=True)
    t.start()
    return t


def _wait_for_server(url, timeout=20.0):
    """Poll the server instead of a fixed sleep, so a slow machine (or a first
    run that's importing torch for the first time) doesn't race the window
    opening before anything is listening. Gives up early if the server thread
    has already crashed, rather than burning the full timeout."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if _server_error["trace"]:
            return False
        if _is_our_app(url):
            return True
        time.sleep(0.25)
    return False


def main():
    url = f"http://127.0.0.1:{CFG.port}"

    if _port_in_use(CFG.port):
        if _is_our_app(url):
            # Don't start a second server or reap the first one's workers; just
            # surface the instance that's already there.
            print(f"[launcher] Audiobook Studio is already running at {url}; "
                  "opening a window onto the existing instance.")
        else:
            _show_error(
                "Audiobook Studio could not start",
                f"Another program is already using port {CFG.port} on this "
                f"computer, so Audiobook Studio cannot start.\n\n"
                f"Close whatever else is using it and try again, or pick a "
                f"different port by setting \"port\" in app\\config.json.\n\n"
                f"Details were written to:\n{LOG_PATH}")
            return
    else:
        # server.main() prints these itself; don't double up.
        atexit.register(_kill_orphan_workers)
        _start_server_thread()
        if not _wait_for_server(url):
            detail = _server_error["trace"] or (
                "The server did not respond within 20 seconds and did not "
                "report an error.")
            _show_error(
                "Audiobook Studio could not start",
                "The app's server did not start.\n\n"
                "Please send this file to whoever set this up for you:\n"
                f"{LOG_PATH}\n\n"
                + detail.strip().splitlines()[-1][:300])
            return

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
