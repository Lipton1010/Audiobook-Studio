"""
Storybird desktop launcher.

Runs in the BASE conda env (same one as server.py: stdlib + fitz + requests,
plus pywebview added by the installer). Starts server.py's HTTP server on a
background thread, then opens a native desktop window pointed at it, so the
app feels like a real program instead of "open your browser to localhost".

Shows a clear desktop-app error if pywebview or the OS WebView runtime is not
available. A desktop shortcut must not silently turn into a browser launch.
"""
import atexit
import json
import os
import socket
import sys
import threading
import time
import traceback
import urllib.request
from pathlib import Path

from managed_runtime import configure_managed_runtime

APP_DIR = Path(__file__).resolve().parent
LOG_PATH = APP_DIR.parent / "launcher_log.txt"
APP_MUTEX = "AudiobookStudio_1E05_4C9D_9B5D_204F12CD7183"
_app_mutex = None


def _redirect_detached_output():
    """pythonw has no console; keep startup warnings and traces in a log."""
    if sys.stdout is not None and sys.stderr is not None:
        return
    try:
        stream = open(LOG_PATH, "a", encoding="utf-8", buffering=1)
        sys.stdout = stream
        sys.stderr = stream
    except Exception:
        pass


configure_managed_runtime(APP_DIR.parent / "runtime")


def _hold_app_mutex():
    """Let the patch installer detect this app without scanning processes."""
    global _app_mutex
    if os.name != "nt" or _app_mutex:
        return
    try:
        import ctypes
        _app_mutex = ctypes.windll.kernel32.CreateMutexW(None, False, APP_MUTEX)
    except Exception as exc:
        _log(f"[launcher] Could not create app mutex: {exc}")
_redirect_detached_output()
sys.path.insert(0, str(APP_DIR))

from config import CFG  # noqa: E402
import server  # noqa: E402

WINDOW_TITLE = "Storybird"
ICON_PATH = APP_DIR / "icon.ico"
APP_USER_MODEL_ID = "Storybird.Desktop"
# Under the installer there is no console to read, so anything worth debugging
# has to land in a file the user can be asked for by name.

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
    """Close the owned Job Object so no narration worker survives exit."""
    with server._active_procs_lock:
        procs = list(server._active_procs.get("procs") or [])
    server._terminate_processes(procs)
    server._close_worker_job()


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


def _enable_webview_downloads(webview_module):
    """Enable EdgeChromium's native Save dialog before creating the window."""
    webview_module.settings["ALLOW_DOWNLOADS"] = True


def _set_windows_app_id():
    """Keep the running window grouped with the Storybird shortcut."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_USER_MODEL_ID)
    except Exception as e:
        _log(f"[launcher] Could not set AppUserModelID: {e}")


def _set_windows_window_icon(window):
    """pywebview's WinForms backend otherwise uses pythonw.exe's icon."""
    if sys.platform != "win32" or not ICON_PATH.exists():
        return
    try:
        if not window.events.shown.wait(20) or window.native is None:
            raise RuntimeError("native window was not ready")
        import clr
        clr.AddReference("System.Drawing")
        from System.Drawing import Icon
        window.native.Icon = Icon(str(ICON_PATH))
    except Exception as e:
        _log(f"[launcher] Could not set native window icon: {e}")


def _open_native_window(webview_module, url):
    """Create and run Storybird's pywebview window."""
    # pywebview 5.4 defaults this to False; its EdgeChromium backend otherwise
    # cancels every DownloadStarting event without feedback.
    _enable_webview_downloads(webview_module)
    _set_windows_app_id()
    window = webview_module.create_window(title=WINDOW_TITLE, url=url,
                                          width=1280, height=860, min_size=(900, 600))
    # pywebview 5.4 ignores icon= on Windows, but accepts it on GTK/QT.
    # The callback updates its WinForms form once that native window is shown.
    start_kwargs = {"icon": str(ICON_PATH)} if ICON_PATH.exists() else {}
    webview_module.start(_set_windows_window_icon, args=(window,), **start_kwargs)


def main():
    _hold_app_mutex()
    url = f"http://127.0.0.1:{CFG.port}"

    if _port_in_use(CFG.port):
        if _is_our_app(url):
            # Don't start a second server or reap the first one's workers; just
            # surface the instance that's already there.
            print(f"[launcher] Storybird is already running at {url}; "
                  "opening a window onto the existing instance.")
        else:
            _show_error(
                "Storybird could not start",
                f"Another program is already using port {CFG.port} on this "
                f"computer, so Storybird cannot start.\n\n"
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
                "Storybird could not start",
                "The app's server did not start.\n\n"
                "Please send this file to whoever set this up for you:\n"
                f"{LOG_PATH}\n\n"
                + detail.strip().splitlines()[-1][:300])
            return

    try:
        import webview
    except ImportError as e:
        _show_error(
            "Storybird desktop window is unavailable",
            "Storybird needs its pywebview desktop component, but it is not "
            "installed in the Python environment used by this shortcut.\n\n"
            "Run setup again, then reopen Storybird.\n\n"
            f"Details were written to:\n{LOG_PATH}")
        _log(f"[launcher] pywebview import failed: {e}")
        return

    try:
        _open_native_window(webview, url)
    except Exception as e:
        _log(f"[launcher] Native window failed: {e}")
        _show_error(
            "Storybird could not open its desktop window",
            "Storybird could not start its native desktop window.\n\n"
            "Install or repair Microsoft Edge WebView2, then reopen Storybird.\n\n"
            f"Details were written to:\n{LOG_PATH}")


if __name__ == "__main__":
    main()
