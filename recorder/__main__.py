"""Allow running with: py -m recorder"""

# Enable per-monitor DPI awareness BEFORE any other import. Importing
# tkinter / pyautogui can lock the process to "system DPI aware", which
# breaks coordinates on secondary monitors with different scaling.
import sys as _sys
if _sys.platform == "win32":
    import ctypes as _ctypes
    _u32 = _ctypes.windll.user32
    _set = False
    try:
        _u32.SetProcessDpiAwarenessContext.argtypes = [_ctypes.c_void_p]
        _u32.SetProcessDpiAwarenessContext.restype = _ctypes.c_int
        # DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = -4
        _set = bool(_u32.SetProcessDpiAwarenessContext(
            _ctypes.c_void_p(-4 & 0xFFFFFFFFFFFFFFFF)))
    except Exception:
        pass
    if not _set:
        try:
            _ctypes.windll.shcore.SetProcessDpiAwareness(2)
            _set = True
        except Exception:
            pass
    if not _set:
        try:
            _u32.SetProcessDPIAware()
        except Exception:
            pass

from .main import main

main()
