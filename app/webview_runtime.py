"""Dependency-light WebView2 presence probe; never starts a server or job."""
from pathlib import Path

def runtime_version(webview_module):
    """Ask Microsoft's loader, without starting a window or trusting registry hints."""
    import ctypes
    architecture = "win-x64" if ctypes.sizeof(ctypes.c_void_p) == 8 else "win-x86"
    loader_path = (Path(webview_module.__file__).resolve().parent / "lib" /
                   "runtimes" / architecture / "native" / "WebView2Loader.dll")
    loader = ctypes.WinDLL(str(loader_path))
    query = loader.GetAvailableCoreWebView2BrowserVersionString
    query.argtypes = [ctypes.c_wchar_p, ctypes.POINTER(ctypes.c_void_p)]
    query.restype = ctypes.c_long
    value = ctypes.c_void_p()
    free = ctypes.windll.ole32.CoTaskMemFree
    free.argtypes = [ctypes.c_void_p]
    free.restype = None
    try:
        result = query(None, ctypes.byref(value))
        return ctypes.wstring_at(value) if result >= 0 and value.value else None
    finally:
        if value.value:
            free(value)

