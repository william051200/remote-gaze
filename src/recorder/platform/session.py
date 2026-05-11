"""Shared helpers for the Windows-App pixel-driving POC scripts.

Importing this module enables Per-Monitor V2 DPI awareness as a side effect.
That MUST happen before any screen / input / window-rect call, otherwise
Windows scales coordinates differently for our different libraries (pyautogui
uses physical pixels, EnumWindows / GetWindowRect / Pillow.ImageGrab use
DPI-scaled pixels) and clicks land in the wrong place on high-DPI monitors.

Public API:
    Config            - typed view over config.ini
    load_config(path) - parse and validate a config file
    find_session_window(title_substring) -> hwnd or None
    focus_window(hwnd)
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

import configparser
import ctypes
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

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
# Config
# ---------------------------------------------------------------------------

Rect = tuple[int, int, int, int]


@dataclass(frozen=True)
class Config:
    """All knobs in one place, populated from config.ini."""

    # [connection]
    window_title_contains: str
    launch_uri: str

    # [action]  (rdp_click.py)
    click_x: int
    click_y: int
    type_text: str

    # [notepad]  (open_notepad.py)
    start_method: str  # "win" or "alt-home"
    app_name: str
    write_text: str
    close_x: int
    close_y: int

    # [timing]
    focus_delay: float
    settle_delay: float
    start_wait: float
    launch_wait: float
    write_wait: float
    close_wait: float

    # [output]
    screenshot_path: Path
    notepad_screenshot_path: Path


def load_config(path: Path) -> Config:
    if not path.exists():
        sys.exit(f"config file not found: {path}")
    cp = configparser.ConfigParser()
    cp.read(path, encoding="utf-8")

    # Ensure optional sections exist so .get(..., fallback=) works uniformly.
    for section in ("connection", "action", "notepad", "timing", "output"):
        if not cp.has_section(section):
            cp.add_section(section)

    try:
        return Config(
            window_title_contains=cp.get("connection", "window_title_contains").strip(),
            launch_uri=cp.get("connection", "launch_uri", fallback="").strip(),
            click_x=cp.getint("action", "click_x", fallback=200),
            click_y=cp.getint("action", "click_y", fallback=200),
            type_text=cp.get("action", "type_text", fallback=""),
            start_method=cp.get("notepad", "start_method", fallback="alt-home").strip(),
            app_name=cp.get("notepad", "app_name", fallback="notepad").strip(),
            write_text=cp.get("notepad", "write_text", fallback="hello world"),
            close_x=cp.getint("notepad", "close_x", fallback=1600),
            close_y=cp.getint("notepad", "close_y", fallback=200),
            focus_delay=cp.getfloat("timing", "focus_delay", fallback=1.0),
            settle_delay=cp.getfloat("timing", "settle_delay", fallback=1.5),
            start_wait=cp.getfloat("timing", "start_wait", fallback=0.8),
            launch_wait=cp.getfloat("timing", "launch_wait", fallback=2.5),
            write_wait=cp.getfloat("timing", "write_wait", fallback=0.5),
            close_wait=cp.getfloat("timing", "close_wait", fallback=1.0),
            screenshot_path=Path(cp.get("output", "screenshot_path", fallback="poc/out/screenshot.png")),
            notepad_screenshot_path=Path(
                cp.get("output", "notepad_screenshot_path", fallback="poc/out/notepad_after.png")
            ),
        )
    except (configparser.NoSectionError, configparser.NoOptionError, KeyError) as exc:
        sys.exit(f"config file {path} is missing required key: {exc}")


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
        if win32gui.IsIconic(hwnd):
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)

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
# Convenience: focus the configured session window or fail fast
# ---------------------------------------------------------------------------


class SessionError(SystemExit):
    """Raised (as SystemExit) when the session window can't be used."""


def focus_session(cfg: Config) -> tuple[int, Rect]:
    """Find, focus, and return (hwnd, rect) for the configured session window.

    Raises SessionError (which is a SystemExit subclass with an exit code)
    when the window can't be found or is too small.
    """
    print(f"[info] looking for window matching: {cfg.window_title_contains!r}")
    hwnd = find_session_window(cfg.window_title_contains)
    if hwnd is None:
        raise SessionError(
            f"[FAIL] no visible window title contains "
            f"{cfg.window_title_contains!r}. Open the session in Windows App and retry.",
        )

    title = win32gui.GetWindowText(hwnd)
    print(f"[info] found window hwnd={hwnd} title={title!r}")

    focus_window(hwnd)
    time.sleep(cfg.focus_delay)

    rect = get_window_rect(hwnd)
    print(f"[info] window rect (L,T,R,B) = {rect}")
    if rect[2] - rect[0] < 50 or rect[3] - rect[1] < 50:
        raise SessionError("[FAIL] window rect is tiny; is the session minimized?")

    return hwnd, rect


# Re-export for convenience
__all__ = [
    "Config",
    "Rect",
    "SessionError",
    "best_effort_launch",
    "click_at",
    "find_session_window",
    "focus_session",
    "focus_window",
    "get_window_rect",
    "hotkey",
    "is_foreground",
    "is_iconic",
    "load_config",
    "open_remote_start",
    "press",
    "relative_to_absolute",
    "screenshot_looks_blank",
    "screenshot_region",
    "type_text",
]


def _unused() -> None:
    # silence unused import warnings for re-exports we keep available
    _ = Iterable
