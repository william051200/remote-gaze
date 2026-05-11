"""Per-monitor DPI awareness setup.

Must be imported BEFORE tkinter / pyautogui / PIL.ImageGrab. Without this,
Win32 ``EnumDisplayMonitors`` and Tk report scaled (logical) coordinates
while mouse events and ``ImageGrab`` operate in physical pixels, breaking
secondary monitors with different DPI scaling.

Importing this module has the side effect of calling the appropriate
Win32 API once. It is a no-op on non-Windows platforms.
"""

import sys


def enable() -> None:
    if sys.platform != "win32":
        return
    import ctypes
    user32 = ctypes.windll.user32
    # Per-Monitor V2 (Windows 10 1703+). The DPI context handle is a
    # sentinel pointer cast from a small negative integer.
    try:
        user32.SetProcessDpiAwarenessContext.argtypes = [ctypes.c_void_p]
        user32.SetProcessDpiAwarenessContext.restype = ctypes.c_int
        ctx = ctypes.c_void_p(-4 & 0xFFFFFFFFFFFFFFFF)  # PER_MONITOR_AWARE_V2
        if user32.SetProcessDpiAwarenessContext(ctx):
            return
    except Exception:
        pass
    # Per-Monitor (Windows 8.1+).
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
        return
    except Exception:
        pass
    # System DPI aware (Vista+).
    try:
        user32.SetProcessDPIAware()
    except Exception:
        pass


enable()
