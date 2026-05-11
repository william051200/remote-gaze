"""Borderless, click-through, screenshot-excluded screen-edge overlay.

Used to give the user a clear visual cue when a recording or playback session
is active. The overlay:

* spans the entire virtual screen (all monitors),
* draws a hollow colored rectangle hugging the screen edges,
* is fully click-through (does not steal focus or block input), and
* is excluded from screen-capture APIs so it does **not** appear in the
  recorder's or player's screenshots.

Windows-only. On other platforms the overlay degrades gracefully by simply
showing a topmost transparent window without click-through / capture
exclusion (which is acceptable since the rest of this project is also
Windows-only).
"""

from __future__ import annotations

import sys
import tkinter as tk
from typing import Optional

# Color used as the transparent fill. Any pixel painted in this exact color
# becomes click-through "hole" via Tk's -transparentcolor attribute. Magenta
# is a safe pick: nothing else in the overlay uses it.
_TRANSPARENT_FILL = "#ff00ff"

_BORDER_THICKNESS = 6


class BorderOverlay:
    """A colored rectangle drawn around the screen edge.

    Parameters
    ----------
    master:
        Parent Tk widget (usually the application root). Required so the
        Toplevel is tied to the same Tcl interpreter / event loop.
    color:
        Border color. Any Tk color name or ``#rrggbb`` string.
    thickness:
        Border thickness in pixels.
    """

    def __init__(self, master: tk.Misc, color: str,
                 thickness: int = _BORDER_THICKNESS) -> None:
        self._master = master
        self._color = color
        self._thickness = thickness
        self._top: Optional[tk.Toplevel] = None
        self._canvas: Optional[tk.Canvas] = None
        self._visible = False
        # Cached bounds the overlay was last built for; if the next show()
        # asks for a different region we rebuild the geometry/canvas.
        self._bounds: Optional[tuple[int, int, int, int]] = None

    # ── public API ────────────────────────────────────────────────────

    def show(self, monitor=None) -> None:
        bounds = self._resolve_bounds(monitor)
        if self._top is None:
            self._build(bounds)
        elif bounds != self._bounds:
            # Monitor changed -- rebuild the overlay so it covers the new
            # region with correctly-positioned border bars.
            self._teardown_geometry()
            self._build(bounds)
        assert self._top is not None
        self._top.deiconify()
        self._top.lift()
        try:
            self._top.attributes("-topmost", True)
        except tk.TclError:
            pass
        self._visible = True

    def hide(self) -> None:
        if not self._visible or self._top is None:
            return
        try:
            self._top.withdraw()
        except tk.TclError:
            pass
        self._visible = False

    def destroy(self) -> None:
        self._visible = False
        if self._top is not None:
            try:
                self._top.destroy()
            except tk.TclError:
                pass
            self._top = None
            self._canvas = None

    # ── internals ─────────────────────────────────────────────────────

    def _build(self, bounds: tuple[int, int, int, int]) -> None:
        top = tk.Toplevel(self._master)
        top.overrideredirect(True)
        top.withdraw()  # keep hidden until show()

        # Always on top, no taskbar entry.
        try:
            top.attributes("-topmost", True)
        except tk.TclError:
            pass
        try:
            top.attributes("-toolwindow", True)
        except tk.TclError:
            pass

        # Make the configured fill color transparent (= click-through hole).
        try:
            top.attributes("-transparentcolor", _TRANSPARENT_FILL)
        except tk.TclError:
            # Non-Windows or unsupported Tk build: overlay will be opaque.
            pass

        x, y, w, h = bounds
        top.geometry(f"{w}x{h}+{x}+{y}")

        canvas = tk.Canvas(
            top, width=w, height=h,
            bg=_TRANSPARENT_FILL,
            highlightthickness=0, borderwidth=0,
        )
        canvas.pack(fill="both", expand=True)

        # Draw four solid bars hugging each screen edge. This is simpler
        # than a hollow rectangle outline because Canvas's `outline` is
        # centered on the edge (half drawn off-screen).
        t = self._thickness
        c = self._color
        canvas.create_rectangle(0, 0, w, t,
                                fill=c, outline=c)            # top
        canvas.create_rectangle(0, h - t, w, h,
                                fill=c, outline=c)            # bottom
        canvas.create_rectangle(0, 0, t, h,
                                fill=c, outline=c)            # left
        canvas.create_rectangle(w - t, 0, w, h,
                                fill=c, outline=c)            # right

        self._top = top
        self._canvas = canvas
        self._bounds = bounds

        # Now that the Toplevel exists, apply Win32 tweaks: click-through
        # extended style and exclude-from-capture display affinity.
        top.update_idletasks()
        self._apply_win32_tweaks()

    def _teardown_geometry(self) -> None:
        if self._top is not None:
            try:
                self._top.destroy()
            except tk.TclError:
                pass
        self._top = None
        self._canvas = None
        self._bounds = None
        self._visible = False

    def _resolve_bounds(self, monitor) -> tuple[int, int, int, int]:
        """Return (x, y, w, h) for the requested monitor, or full virtual
        screen when ``monitor`` is None."""
        if monitor is not None:
            return (int(monitor.x), int(monitor.y),
                    int(monitor.width), int(monitor.height))
        return self._virtual_screen_bounds()

    def _virtual_screen_bounds(self) -> tuple[int, int, int, int]:
        """Return (x, y, width, height) covering all monitors."""
        if sys.platform == "win32":
            try:
                import ctypes
                user32 = ctypes.windll.user32
                # SM_XVIRTUALSCREEN = 76, SM_YVIRTUALSCREEN = 77,
                # SM_CXVIRTUALSCREEN = 78, SM_CYVIRTUALSCREEN = 79
                x = user32.GetSystemMetrics(76)
                y = user32.GetSystemMetrics(77)
                w = user32.GetSystemMetrics(78)
                h = user32.GetSystemMetrics(79)
                if w > 0 and h > 0:
                    return x, y, w, h
            except Exception:
                pass
        # Fallback: primary monitor only.
        return (0, 0,
                self._master.winfo_screenwidth(),
                self._master.winfo_screenheight())

    def _apply_win32_tweaks(self) -> None:
        """Make the overlay click-through and exclude it from screen capture."""
        if sys.platform != "win32" or self._top is None:
            return
        try:
            import ctypes
            from ctypes import wintypes

            hwnd_str = self._top.wm_frame()
            if not hwnd_str:
                return
            hwnd = int(hwnd_str, 16)

            user32 = ctypes.windll.user32

            GWL_EXSTYLE = -20
            WS_EX_LAYERED = 0x00080000
            WS_EX_TRANSPARENT = 0x00000020
            WS_EX_TOOLWINDOW = 0x00000080
            WS_EX_NOACTIVATE = 0x08000000

            # Use GetWindowLongPtrW / SetWindowLongPtrW on 64-bit Windows so
            # we don't truncate. Fall back to the 32-bit variants if the
            # PtrW symbols are missing (older Windows).
            get_long = getattr(user32, "GetWindowLongPtrW", None) \
                or user32.GetWindowLongW
            set_long = getattr(user32, "SetWindowLongPtrW", None) \
                or user32.SetWindowLongW
            get_long.restype = ctypes.c_ssize_t
            get_long.argtypes = [wintypes.HWND, ctypes.c_int]
            set_long.restype = ctypes.c_ssize_t
            set_long.argtypes = [wintypes.HWND, ctypes.c_int,
                                 ctypes.c_ssize_t]

            ex_style = get_long(hwnd, GWL_EXSTYLE)
            ex_style |= (WS_EX_LAYERED | WS_EX_TRANSPARENT
                         | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE)
            set_long(hwnd, GWL_EXSTYLE, ex_style)

            # Exclude from screen capture (Windows 10 2004+; harmless no-op
            # on older versions, returns 0).
            WDA_EXCLUDEFROMCAPTURE = 0x00000011
            try:
                user32.SetWindowDisplayAffinity(
                    wintypes.HWND(hwnd), WDA_EXCLUDEFROMCAPTURE,
                )
            except Exception:
                pass
        except Exception:
            # Click-through / capture-exclusion are best-effort. If they
            # fail the overlay still works visually.
            pass
