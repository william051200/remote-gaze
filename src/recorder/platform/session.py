"""Shared helpers for driving a Windows-App / RDP session by pixels.

Importing this module enables Per-Monitor V2 DPI awareness as a side effect.
That MUST happen before any screen / input / window-rect call, otherwise
Windows scales coordinates differently for our different libraries (pyautogui
uses physical pixels, EnumWindows / GetWindowRect / Pillow.ImageGrab use
DPI-scaled pixels) and clicks land in the wrong place on high-DPI monitors.

Public API:
    find_session_window(title_substring) -> hwnd or None
    focus_window(hwnd)
    is_iconic(hwnd) -> bool
    is_foreground(hwnd) -> bool
    get_window_rect(hwnd) -> (left, top, right, bottom)
    relative_to_absolute(rect, x, y) -> (abs_x, abs_y)
    click_at(abs_x, abs_y)
    type_text(text, *, interval=0.04)
    press(key)
    hotkey(*keys)
    open_remote_start(method)
    screenshot_region(rect, out_path) -> Path
    screenshot_looks_blank(path) -> bool
    best_effort_launch(uri_or_command)
"""

from __future__ import annotations

import ctypes
import os
import subprocess
import time
from pathlib import Path

# ---------------------------------------------------------------------------
# DPI awareness - MUST run before any screen / input / window-rect import.
# ---------------------------------------------------------------------------

_DPI_PER_MONITOR_V2 = ctypes.c_void_p(-4)


def _enable_dpi_awareness() -> None:
    user32 = ctypes.windll.user32
    try:
        user32.SetProcessDpiAwarenessContext(_DPI_PER_MONITOR_V2)
        return
    except (AttributeError, OSError):
        pass
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
        return
    except (AttributeError, OSError):
        pass
    try:
        user32.SetProcessDPIAware()
    except (AttributeError, OSError):
        pass


_enable_dpi_awareness()

# Imports that touch the screen / windows must come AFTER DPI setup.
import pyautogui  # noqa: E402
import win32con  # noqa: E402
import win32gui  # noqa: E402
from PIL import Image, ImageGrab  # noqa: E402

# pyautogui's "move to a corner aborts the script" guardrail interferes with
# clicks at the very edge of the Windows App window. Disable it for the POC.
pyautogui.FAILSAFE = False


# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

Rect = tuple[int, int, int, int]


# ---------------------------------------------------------------------------
# Window discovery
# ---------------------------------------------------------------------------


def find_session_window(title_substring: str) -> int | None:
    """Return the HWND of the largest visible top-level window whose title
    contains `title_substring` (case-insensitive). None if not found.

    Largest-wins because Windows App spawns small helper windows that share
    the same title prefix; the actual session window is the big one.
    """
    needle = title_substring.lower()
    matches: list[int] = []

    def _collect(hwnd: int, _: object) -> bool:
        if not win32gui.IsWindowVisible(hwnd):
            return True
        title = win32gui.GetWindowText(hwnd)
        if title and needle in title.lower():
            matches.append(hwnd)
        return True

    win32gui.EnumWindows(_collect, None)
    if not matches:
        return None

    def _area(hwnd: int) -> int:
        l, t, r, b = win32gui.GetWindowRect(hwnd)
        return max(0, r - l) * max(0, b - t)

    matches.sort(key=_area, reverse=True)
    return matches[0]


def _restore_if_minimized(hwnd: int, *, timeout: float = 1.5) -> bool:
    """Force-restore ``hwnd`` if it is minimized.

    Returns True when the window is no longer iconic (or wasn't iconic
    to begin with). UWP/AppContainer windows like the "Windows App"
    session host don't always honour a single ``ShowWindow(SW_RESTORE)``
    -- they're hosted by ApplicationFrameHost.exe and the restore can be
    swallowed if the window manager is busy. We retry with
    ``ShowWindowAsync`` and ``SwitchToThisWindow`` and poll
    ``IsIconic`` + ``GetWindowRect`` until the parking rect
    ``(-32000, -32000)`` goes away.
    """
    try:
        if not win32gui.IsIconic(hwnd):
            return True
    except Exception:
        return False

    user32 = ctypes.windll.user32
    deadline = time.monotonic() + max(0.0, timeout)
    attempt = 0
    methods = ["ShowWindow(SW_RESTORE)", "ShowWindowAsync(SW_RESTORE)",
               "ShowWindowAsync(SW_SHOWNORMAL)", "SwitchToThisWindow"]
    while time.monotonic() < deadline:
        method = methods[min(attempt, len(methods) - 1)]
        try:
            if attempt == 0:
                win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
            elif attempt == 1:
                user32.ShowWindowAsync(hwnd, win32con.SW_RESTORE)
            elif attempt == 2:
                user32.ShowWindowAsync(hwnd, win32con.SW_SHOWNORMAL)
            else:
                # SwitchToThisWindow with fAltTab=True acts like an
                # Alt-Tab to the window; the shell honours it even when
                # ShowWindow is being ignored by ApplicationFrameHost.
                user32.SwitchToThisWindow(hwnd, True)
        except Exception as exc:
            print(f"[restore] {method} raised: {exc}")

        attempt += 1
        end_attempt = min(deadline, time.monotonic() + 0.4)
        while time.monotonic() < end_attempt:
            time.sleep(0.05)
            try:
                if not win32gui.IsIconic(hwnd):
                    l, t, r, b = win32gui.GetWindowRect(hwnd)
                    if l > -10000 and t > -10000 and (r - l) > 0 and (b - t) > 0:
                        print(f"[restore] hwnd {hwnd} on-screen via {method} "
                              f"rect=({l},{t},{r},{b})")
                        return True
            except Exception:
                pass

    try:
        still_iconic = win32gui.IsIconic(hwnd)
    except Exception:
        still_iconic = True
    print(f"[restore] FAILED to un-minimize hwnd {hwnd} after {timeout:.1f}s "
          f"(iconic={still_iconic})")
    return not still_iconic


def focus_window(hwnd: int) -> None:
    """Restore (if minimized) and bring `hwnd` to the true foreground.

    Plain `SetForegroundWindow` is blocked by Windows when the caller
    isn't already the foreground process - it silently fails and any
    subsequent keystrokes go to whatever WAS focused (usually the
    console). We work around this two ways:

      1. Tap Alt to satisfy Windows' "user input was just received"
         heuristic, which temporarily lifts the SetForegroundWindow lock.
      2. AttachThreadInput so our thread shares the foreground thread's
         input queue, then call SetForegroundWindow + BringWindowToTop +
         SetFocus, then detach.

    After this, `GetForegroundWindow() == hwnd` should hold.
    """
    try:
        # Robust restore for UWP/AppContainer windows -- a single
        # SW_RESTORE is unreliable for ApplicationFrameHost-hosted
        # windows like "Windows App".
        _restore_if_minimized(hwnd)

        # 1) Alt-tap to bypass the SetForegroundWindow restriction.
        try:
            pyautogui.keyDown("alt")
            pyautogui.keyUp("alt")
        except Exception:
            pass

        # 2) AttachThreadInput trick.
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        fg_hwnd = user32.GetForegroundWindow()
        fg_thread = user32.GetWindowThreadProcessId(fg_hwnd, None)
        target_thread = user32.GetWindowThreadProcessId(hwnd, None)
        cur_thread = kernel32.GetCurrentThreadId()

        attached_fg = False
        attached_target = False
        try:
            if fg_thread and fg_thread != cur_thread:
                attached_fg = bool(user32.AttachThreadInput(cur_thread, fg_thread, True))
            if target_thread and target_thread != cur_thread:
                attached_target = bool(user32.AttachThreadInput(cur_thread, target_thread, True))

            user32.BringWindowToTop(hwnd)
            user32.SetForegroundWindow(hwnd)
            user32.SetFocus(hwnd)
        finally:
            if attached_fg:
                user32.AttachThreadInput(cur_thread, fg_thread, False)
            if attached_target:
                user32.AttachThreadInput(cur_thread, target_thread, False)

        time.sleep(0.15)
        actual = user32.GetForegroundWindow()
        if actual != hwnd:
            print(
                f"[warn] foreground is {actual}, expected {hwnd}; "
                f"keystrokes may go to the wrong window"
            )
    except Exception as exc:
        print(f"[warn] could not foreground window: {exc}")


def get_window_rect(hwnd: int) -> Rect:
    return win32gui.GetWindowRect(hwnd)


def is_iconic(hwnd: int) -> bool:
    """True when the window is currently minimized."""
    try:
        return bool(win32gui.IsIconic(hwnd))
    except Exception:
        return False


def is_foreground(hwnd: int) -> bool:
    """True when the given HWND owns the foreground input focus."""
    try:
        user32 = ctypes.windll.user32
        user32.GetForegroundWindow.restype = ctypes.c_void_p
        fg = user32.GetForegroundWindow()
        return fg is not None and int(fg) == int(hwnd)
    except Exception:
        return False


def relative_to_absolute(rect: Rect, rel_x: int, rel_y: int) -> tuple[int, int]:
    """Convert (x, y) relative to a window's top-left into absolute screen coords."""
    return rect[0] + rel_x, rect[1] + rel_y


# ---------------------------------------------------------------------------
# Input
# ---------------------------------------------------------------------------


def click_at(abs_x: int, abs_y: int) -> None:
    """Move the mouse to absolute (x, y) and left-click."""
    pyautogui.moveTo(abs_x, abs_y, duration=0.15)
    pyautogui.click()


def type_text(text: str, *, interval: float = 0.04) -> None:
    pyautogui.typewrite(text, interval=interval)


def press(key: str) -> None:
    pyautogui.press(key)


def hotkey(*keys: str) -> None:
    pyautogui.hotkey(*keys)


def open_remote_start(method: str) -> None:
    """Open the remote Start menu via the Windows App session.

    Methods:
      win       - the Windows key. Only forwards to the remote session when
                  Windows App is FULLSCREEN; in windowed mode the laptop OS
                  captures it and opens the local Start menu.
      alt-home  - the RDP/Windows App built-in shortcut for "open remote
                  Start". Works in windowed mode.
    """
    if method == "win":
        # Hold the key briefly - some RDP clients drop a too-fast tap.
        pyautogui.keyDown("winleft")
        time.sleep(0.08)
        pyautogui.keyUp("winleft")
    elif method == "alt-home":
        pyautogui.keyDown("alt")
        pyautogui.keyDown("home")
        time.sleep(0.08)
        pyautogui.keyUp("home")
        pyautogui.keyUp("alt")
    else:
        raise ValueError(f"unknown start method: {method!r}")


# ---------------------------------------------------------------------------
# Best-effort launch of the Windows App connection
# ---------------------------------------------------------------------------

_URI_PREFIXES: tuple[str, ...] = ("ms-avd:", "ms-rd:", "http")


def best_effort_launch(uri_or_command: str) -> None:
    """Try to launch the Windows App connection; never raise.

    A URI like `ms-avd:connect?...` is opened with the OS handler. Anything
    else is run as a shell command. Failure just logs a warning - the script
    continues assuming the user opened the session manually.
    """
    if not uri_or_command:
        print("[info] no launch_uri configured; assuming session is already open")
        return
    try:
        if uri_or_command.lower().startswith(_URI_PREFIXES):
            os.startfile(uri_or_command)  # type: ignore[attr-defined]
            print(f"[info] launched URI: {uri_or_command}")
        else:
            subprocess.Popen(uri_or_command, shell=True)
            print(f"[info] launched: {uri_or_command}")
    except Exception as exc:
        print(f"[warn] launch failed ({exc}); assuming session is already open")


# ---------------------------------------------------------------------------
# Screenshot
# ---------------------------------------------------------------------------


def screenshot_region(rect: Rect, out_path: Path) -> Path:
    """Save a PNG screenshot of the given screen rect.

    Uses `all_screens=True` so multi-monitor setups don't silently return
    black for non-primary monitors.
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)
    img = ImageGrab.grab(bbox=rect, all_screens=True)
    img.save(out_path)
    return out_path


def screenshot_looks_blank(path: Path) -> bool:
    """Heuristic check: file is suspicious if <1KB or fully one color."""
    if path.stat().st_size < 1024:
        return True
    try:
        with Image.open(path) as im:
            extrema = im.convert("RGB").getextrema()
            return all(lo == hi for lo, hi in extrema)
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Re-exports
# ---------------------------------------------------------------------------

__all__ = [
    "Rect",
    "best_effort_launch",
    "click_at",
    "find_session_window",
    "focus_window",
    "get_window_rect",
    "hotkey",
    "is_foreground",
    "is_iconic",
    "open_remote_start",
    "press",
    "relative_to_absolute",
    "screenshot_looks_blank",
    "screenshot_region",
    "type_text",
]
