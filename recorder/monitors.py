"""Monitor enumeration helper.

Lists physical displays via Win32 ``EnumDisplayMonitors`` /
``GetMonitorInfoW`` (no extra dependency). On non-Windows platforms a single
fallback entry covering the primary screen is returned so the rest of the
app can keep working.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass


@dataclass(frozen=True)
class Monitor:
    index: int          # 0-based; 0 is primary if a primary exists
    name: str           # device name, e.g. "\\.\DISPLAY1"
    x: int              # virtual-screen x of top-left
    y: int              # virtual-screen y of top-left
    width: int
    height: int
    is_primary: bool

    @property
    def label(self) -> str:
        tag = " (Primary)" if self.is_primary else ""
        return f"{self.index + 1}: {self.width}×{self.height}{tag}"

    def to_dict(self) -> dict:
        return {
            "index": self.index,
            "name": self.name,
            "x": self.x,
            "y": self.y,
            "width": self.width,
            "height": self.height,
            "is_primary": self.is_primary,
        }


def list_monitors() -> list[Monitor]:
    """Return the list of monitors, primary first (index 0)."""
    if sys.platform == "win32":
        try:
            mons = _enum_windows_monitors()
            if mons:
                return mons
        except Exception:
            pass
    return [_fallback_monitor()]


def _fallback_monitor() -> Monitor:
    try:
        # tk import is local so the module stays importable headless.
        import tkinter as tk
        root = tk.Tk()
        root.withdraw()
        w = root.winfo_screenwidth()
        h = root.winfo_screenheight()
        root.destroy()
    except Exception:
        w, h = 1920, 1080
    return Monitor(index=0, name="DISPLAY1",
                   x=0, y=0, width=w, height=h, is_primary=True)


# ── Windows implementation ───────────────────────────────────────────

def _enum_windows_monitors() -> list[Monitor]:
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32

    class RECT(ctypes.Structure):
        _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                    ("right", ctypes.c_long), ("bottom", ctypes.c_long)]

    class MONITORINFOEXW(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.DWORD),
            ("rcMonitor", RECT),
            ("rcWork", RECT),
            ("dwFlags", wintypes.DWORD),
            ("szDevice", wintypes.WCHAR * 32),
        ]

    MONITORENUMPROC = ctypes.WINFUNCTYPE(
        ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p,
        ctypes.POINTER(RECT), ctypes.c_double,
    )

    user32.GetMonitorInfoW.restype = ctypes.c_int
    user32.GetMonitorInfoW.argtypes = [ctypes.c_void_p,
                                        ctypes.POINTER(MONITORINFOEXW)]

    collected: list[Monitor] = []

    MONITORINFOF_PRIMARY = 1

    def _cb(hMon, hDC, lprc, lparam):
        info = MONITORINFOEXW()
        info.cbSize = ctypes.sizeof(MONITORINFOEXW)
        if user32.GetMonitorInfoW(hMon, ctypes.byref(info)):
            r = info.rcMonitor
            collected.append({
                "name": info.szDevice,
                "x": int(r.left),
                "y": int(r.top),
                "width": int(r.right - r.left),
                "height": int(r.bottom - r.top),
                "is_primary": bool(info.dwFlags & MONITORINFOF_PRIMARY),
            })
        return 1

    if not user32.EnumDisplayMonitors(0, 0, MONITORENUMPROC(_cb), 0):
        return []

    # Sort: primary first, then by (y, x) for stable ordering.
    collected.sort(key=lambda m: (0 if m["is_primary"] else 1,
                                  m["y"], m["x"]))
    return [
        Monitor(index=i, name=m["name"], x=m["x"], y=m["y"],
                width=m["width"], height=m["height"],
                is_primary=m["is_primary"])
        for i, m in enumerate(collected)
    ]
