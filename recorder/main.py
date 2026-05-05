"""Entry point for the RemoteGaze Recorder application."""

import sys
from pathlib import Path

from .gui import RecorderGUI
from .config import RECORDINGS_DIR_NAME


def _enable_dpi_awareness() -> None:
    """Make the process per-monitor DPI aware on Windows.

    Without this, Win32 ``EnumDisplayMonitors`` and Tk report **scaled**
    (logical) coordinates while mouse events and ``ImageGrab`` operate in
    **physical** pixels. The mismatch makes secondary monitors with
    different DPI scaling produce wrong screenshot regions and off-by-N
    click coordinates. Must be called before any Tk window is created.
    """
    if sys.platform != "win32":
        return
    import ctypes
    user32 = ctypes.windll.user32
    # Try Per-Monitor V2 (Windows 10 1703+) first. The DPI context handle
    # is a sentinel pointer cast from a small negative integer; pass it as
    # a c_void_p built from the unsigned 64-bit two's-complement so ctypes
    # doesn't reject it.
    try:
        user32.SetProcessDpiAwarenessContext.argtypes = [ctypes.c_void_p]
        user32.SetProcessDpiAwarenessContext.restype = ctypes.c_int
        # DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = -4
        ctx = ctypes.c_void_p(-4 & 0xFFFFFFFFFFFFFFFF)
        if user32.SetProcessDpiAwarenessContext(ctx):
            return
    except Exception:
        pass
    # Per-Monitor (Windows 8.1+).
    try:
        # PROCESS_PER_MONITOR_DPI_AWARE = 2
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
        return
    except Exception:
        pass
    # System DPI aware (Vista+).
    try:
        user32.SetProcessDPIAware()
    except Exception:
        pass


def main():
    _enable_dpi_awareness()
    output_dir = Path(__file__).resolve().parent.parent / RECORDINGS_DIR_NAME
    output_dir.mkdir(exist_ok=True)
    app = RecorderGUI(output_dir=output_dir)
    app.run()


if __name__ == "__main__":
    main()
