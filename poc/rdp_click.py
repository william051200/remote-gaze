"""POC: drive a devbox UI from the laptop via the Windows App session window.

What this script does:
  1. (Best-effort) launch a Windows App connection via URI or msrdcw.exe.
  2. Find the Windows App session window by title substring.
  3. Focus it, click at coords RELATIVE to that window, type some text.
  4. Screenshot the window region and save it to disk.
  5. Print PASS / FAIL.

This script does NOT speak the RDP protocol. It treats the Windows App
session window as a regular top-level window on the laptop and drives its
pixels via standard Windows APIs.

Prerequisites:
  - Microsoft Windows App is installed and signed in.
  - The devbox session is reachable (or already open) in Windows App.
  - The session window stays VISIBLE (not minimized, not locked).
"""

from __future__ import annotations

import argparse
import configparser
import ctypes
import os
import subprocess
import sys
import time
from ctypes import wintypes
from pathlib import Path


# ---------------------------------------------------------------------------
# DPI awareness. MUST run before any screen / input / window-rect calls,
# otherwise EnumWindows / GetWindowRect / ImageGrab return scaled coords on
# high-DPI monitors while pyautogui / Pillow use physical pixels.
# Per-Monitor V2 = -4.
# ---------------------------------------------------------------------------
def _enable_dpi_awareness() -> None:
    try:
        ctypes.windll.user32.SetProcessDpiAwarenessContext(
            ctypes.c_void_p(-4)
        )
    except (AttributeError, OSError):
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except (AttributeError, OSError):
            ctypes.windll.user32.SetProcessDPIAware()


_enable_dpi_awareness()

# Imports that touch the screen must happen AFTER DPI setup.
import pyautogui  # noqa: E402
import win32con  # noqa: E402
import win32gui  # noqa: E402
from PIL import ImageGrab  # noqa: E402


# Per repo memory: HWNDs returned via ctypes get truncated to signed 32-bit
# on 64-bit Windows unless restype is set. pywin32 already returns proper
# HWNDs, but if we ever drop to ctypes for FindWindowW / WindowFromPoint we
# must apply this. Kept here as a reminder.
_user32 = ctypes.windll.user32
_user32.FindWindowW.restype = wintypes.HWND
_user32.GetForegroundWindow.restype = wintypes.HWND


# ---------------------------------------------------------------------------
# Window discovery
# ---------------------------------------------------------------------------
def find_session_window(title_substring: str) -> int | None:
    """Return HWND of the first visible top-level window whose title contains
    `title_substring` (case-insensitive). Returns None if not found.
    """
    needle = title_substring.lower()
    matches: list[tuple[int, str]] = []

    def _cb(hwnd: int, _: object) -> bool:
        if not win32gui.IsWindowVisible(hwnd):
            return True
        title = win32gui.GetWindowText(hwnd)
        if title and needle in title.lower():
            matches.append((hwnd, title))
        return True

    win32gui.EnumWindows(_cb, None)
    if not matches:
        return None
    # Prefer the largest window if multiple match (Windows App spawns helper
    # windows with the same title prefix).
    def _area(hwnd: int) -> int:
        l, t, r, b = win32gui.GetWindowRect(hwnd)
        return max(0, r - l) * max(0, b - t)

    matches.sort(key=lambda m: _area(m[0]), reverse=True)
    return matches[0][0]


def focus_window(hwnd: int) -> None:
    """Restore + bring a window to the foreground. Best-effort."""
    try:
        if win32gui.IsIconic(hwnd):
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        win32gui.SetForegroundWindow(hwnd)
    except Exception as exc:
        print(f"[warn] could not foreground window: {exc}")


def get_window_rect(hwnd: int) -> tuple[int, int, int, int]:
    return win32gui.GetWindowRect(hwnd)


# ---------------------------------------------------------------------------
# Best-effort launch of the Windows App connection
# ---------------------------------------------------------------------------
def best_effort_launch(launch_uri: str) -> None:
    if not launch_uri:
        print("[info] no launch_uri configured; assuming session is already open")
        return
    try:
        if launch_uri.lower().startswith(("ms-avd:", "ms-rd:", "http")):
            os.startfile(launch_uri)  # type: ignore[attr-defined]
            print(f"[info] launched URI: {launch_uri}")
        else:
            subprocess.Popen(launch_uri, shell=True)
            print(f"[info] launched: {launch_uri}")
    except Exception as exc:
        print(f"[warn] launch failed ({exc}); assuming session is already open")


# ---------------------------------------------------------------------------
# Action: click + type inside the session window
# ---------------------------------------------------------------------------
def click_and_type(
    rect: tuple[int, int, int, int],
    rel_x: int,
    rel_y: int,
    text: str,
) -> tuple[int, int]:
    abs_x = rect[0] + rel_x
    abs_y = rect[1] + rel_y
    pyautogui.moveTo(abs_x, abs_y, duration=0.15)
    pyautogui.click()
    if text:
        pyautogui.typewrite(text, interval=0.03)
    return abs_x, abs_y


# ---------------------------------------------------------------------------
# Screenshot the window region
# ---------------------------------------------------------------------------
def screenshot_region(rect: tuple[int, int, int, int], out_path: Path) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    # all_screens=True so multi-monitor setups don't return black for the
    # non-primary monitor (per repo memory).
    img = ImageGrab.grab(bbox=rect, all_screens=True)
    img.save(out_path)
    return out_path


def _looks_blank(path: Path) -> bool:
    """Heuristic: file is suspicious if <1KB or fully one color."""
    if path.stat().st_size < 1024:
        return True
    try:
        from PIL import Image

        with Image.open(path) as im:
            extrema = im.convert("RGB").getextrema()
            # extrema = ((minR,maxR),(minG,maxG),(minB,maxB))
            return all(lo == hi for lo, hi in extrema)
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def load_config(path: Path) -> configparser.ConfigParser:
    cfg = configparser.ConfigParser()
    if not path.exists():
        sys.exit(f"config file not found: {path}")
    cfg.read(path, encoding="utf-8")
    return cfg


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        default="poc/config.ini",
        help="Path to config.ini (copy from config.example.ini). "
        "Default: poc/config.ini",
    )
    parser.add_argument(
        "--no-launch",
        action="store_true",
        help="Skip best-effort launch even if launch_uri is configured.",
    )
    args = parser.parse_args(argv)

    cfg_path = Path(args.config)
    cfg = load_config(cfg_path)

    title_needle = cfg["connection"]["window_title_contains"].strip()
    launch_uri = cfg["connection"].get("launch_uri", "").strip()
    rel_x = cfg.getint("action", "click_x")
    rel_y = cfg.getint("action", "click_y")
    text = cfg["action"].get("type_text", "")
    focus_delay = cfg.getfloat("timing", "focus_delay")
    settle_delay = cfg.getfloat("timing", "settle_delay")
    out_path = Path(cfg["output"]["screenshot_path"])

    if not args.no_launch:
        best_effort_launch(launch_uri)
        if launch_uri:
            time.sleep(2.0)

    print(f"[info] looking for window matching: {title_needle!r}")
    hwnd = find_session_window(title_needle)
    if hwnd is None:
        print(
            "[FAIL] no visible window title contains "
            f"{title_needle!r}. Open the devbox session in Windows App and retry."
        )
        return 2

    title = win32gui.GetWindowText(hwnd)
    print(f"[info] found window hwnd={hwnd} title={title!r}")

    focus_window(hwnd)
    time.sleep(focus_delay)

    rect = get_window_rect(hwnd)
    print(f"[info] window rect (L,T,R,B) = {rect}")
    if rect[2] - rect[0] < 50 or rect[3] - rect[1] < 50:
        print("[FAIL] window rect is tiny; is the session minimized?")
        return 3

    abs_x, abs_y = click_and_type(rect, rel_x, rel_y, text)
    print(f"[info] clicked at absolute ({abs_x},{abs_y}); typed {text!r}")

    time.sleep(settle_delay)

    saved = screenshot_region(rect, out_path)
    print(f"[info] saved screenshot: {saved}")

    if _looks_blank(saved):
        print(
            "[FAIL] screenshot looks blank or single-color. "
            "Is the session locked / minimized / occluded?"
        )
        return 4

    print("[PASS] click + screenshot completed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
