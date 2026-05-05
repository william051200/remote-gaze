"""POC step 2: open Notepad on the devbox by sending Start-menu keys.

Sequence:
  1. Find + focus the Windows App session window.
  2. Press the Start-menu key (Win, or Alt+Home as fallback).
  3. Type the app name (default "notepad").
  4. Press Enter.
  5. Wait, screenshot the session region, save to disk.

Important about the Windows / Start key:
  Windows App (and mstsc) only forwards the Win key to the remote session
  when the client is FULLSCREEN. In a windowed session the laptop OS
  captures Win and opens the LOCAL Start menu. Two ways around this:
    * Put Windows App in fullscreen before running this script, OR
    * Use --start-method alt-home (RDP shortcut for "open remote Start").

Run:
  python poc\\open_notepad.py --config poc\\config.ini
  python poc\\open_notepad.py --config poc\\config.ini --start-method alt-home
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

# rdp_click runs DPI setup at import; keep this import first.
from rdp_click import (
    find_session_window,
    focus_window,
    get_window_rect,
    load_config,
    screenshot_region,
    _looks_blank,
)

import pyautogui

pyautogui.FAILSAFE = False


def open_start(method: str) -> None:
    if method == "win":
        # 'winleft' is pyautogui's name for the left Windows key.
        pyautogui.press("winleft")
    elif method == "alt-home":
        pyautogui.hotkey("alt", "home")
    else:
        raise ValueError(f"unknown start method: {method}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="poc/config.ini")
    parser.add_argument(
        "--start-method",
        choices=["win", "alt-home"],
        default="win",
        help="How to open the remote Start menu. Use 'alt-home' if Windows "
        "App is windowed (Win key would otherwise hit the laptop instead).",
    )
    parser.add_argument(
        "--app-name",
        default="notepad",
        help="Text to type into Start search after opening it.",
    )
    parser.add_argument(
        "--write-text",
        default="hello world",
        help="Text to type into the launched app. Set to empty string to skip.",
    )
    parser.add_argument(
        "--start-wait",
        type=float,
        default=0.8,
        help="Seconds to wait after opening the Start menu before typing.",
    )
    parser.add_argument(
        "--launch-wait",
        type=float,
        default=2.5,
        help="Seconds to wait after Enter before screenshotting (let the app open).",
    )
    parser.add_argument(
        "--write-wait",
        type=float,
        default=0.5,
        help="Seconds to wait after the launched app appears before typing into it.",
    )
    parser.add_argument(
        "--close",
        action="store_true",
        help="After typing, close Notepad with the mouse (maximize first for "
        "predictable X-button location, then click X, then click 'Don't save').",
    )
    parser.add_argument(
        "--close-x-from-right",
        type=int,
        default=24,
        help="Pixels from the RIGHT edge of the session window where the "
        "Notepad close (X) button sits when maximized. Tune if Windows App "
        "has different chrome.",
    )
    parser.add_argument(
        "--close-y-from-top",
        type=int,
        default=80,
        help="Pixels from the TOP of the session window down to the Notepad "
        "close (X) button. Account for Windows App's title bar (often ~40px) "
        "plus Notepad's title bar (~40px).",
    )
    parser.add_argument(
        "--dont-save-x",
        type=int,
        default=None,
        help="Absolute screen X for the 'Don't save' button on the unsaved "
        "changes dialog. If unset, defaults to session-window-center + 60.",
    )
    parser.add_argument(
        "--dont-save-y",
        type=int,
        default=None,
        help="Absolute screen Y for the 'Don't save' button. If unset, "
        "defaults to session-window-center.",
    )
    parser.add_argument(
        "--out",
        default=None,
        help="Where to save the post-launch screenshot. "
        "Defaults to <config screenshot dir>/notepad_after.png.",
    )
    args = parser.parse_args(argv)

    cfg = load_config(Path(args.config))
    title_needle = cfg["connection"]["window_title_contains"].strip()
    focus_delay = cfg.getfloat("timing", "focus_delay")

    if args.out:
        out_path = Path(args.out)
    else:
        cfg_shot = Path(cfg["output"]["screenshot_path"])
        out_path = cfg_shot.with_name("notepad_after.png")

    print(f"[info] looking for window matching: {title_needle!r}")
    hwnd = find_session_window(title_needle)
    if hwnd is None:
        print(f"[FAIL] no visible window title contains {title_needle!r}.")
        return 2

    focus_window(hwnd)
    time.sleep(focus_delay)
    rect = get_window_rect(hwnd)
    print(f"[info] focused hwnd={hwnd} rect={rect}")
    if rect[2] - rect[0] < 50 or rect[3] - rect[1] < 50:
        print("[FAIL] window rect tiny; is the session minimized?")
        return 3

    print(f"[info] opening Start via method={args.start_method!r}")
    if args.start_method == "win":
        print(
            "       NOTE: this only reaches the devbox if Windows App is "
            "FULLSCREEN. If Notepad opens on the laptop instead, rerun "
            "with --start-method alt-home."
        )
    open_start(args.start_method)
    time.sleep(args.start_wait)

    print(f"[info] typing {args.app_name!r}")
    pyautogui.typewrite(args.app_name, interval=0.05)
    time.sleep(0.4)

    print("[info] pressing Enter")
    pyautogui.press("enter")
    time.sleep(args.launch_wait)

    if args.write_text:
        time.sleep(args.write_wait)
        print(f"[info] typing into launched app: {args.write_text!r}")
        pyautogui.typewrite(args.write_text, interval=0.04)
        time.sleep(0.4)

    if args.close:
        # Maximize the active remote window so the close (X) button sits at
        # a predictable top-right corner of the Windows App client area.
        # Win+Up only forwards in fullscreen Windows App; Alt+Space then 'x'
        # is the windowed-friendly equivalent (Maximize from the system menu).
        print("[info] maximize Notepad via Alt+Space, x")
        pyautogui.hotkey("alt", "space")
        time.sleep(0.3)
        pyautogui.press("x")
        time.sleep(0.6)

        # Re-read rect in case maximizing nudged anything.
        rect = get_window_rect(hwnd)
        close_x = rect[2] - args.close_x_from_right
        close_y = rect[1] + args.close_y_from_top
        print(f"[info] mouse-clicking Notepad X at ({close_x},{close_y})")
        pyautogui.moveTo(close_x, close_y, duration=0.15)
        pyautogui.click()
        time.sleep(0.8)

        # Notepad will pop a "Save changes?" dialog because we typed text.
        # Click "Don't save" to discard.
        if args.dont_save_x is not None and args.dont_save_y is not None:
            ds_x, ds_y = args.dont_save_x, args.dont_save_y
        else:
            ds_x = (rect[0] + rect[2]) // 2 + 60
            ds_y = (rect[1] + rect[3]) // 2
        print(f"[info] mouse-clicking 'Don't save' near ({ds_x},{ds_y})")
        pyautogui.moveTo(ds_x, ds_y, duration=0.15)
        pyautogui.click()
        time.sleep(0.6)

    saved = screenshot_region(rect, out_path)
    print(f"[info] saved screenshot: {saved}")

    if _looks_blank(saved):
        print(
            "[FAIL] screenshot is blank or single-color. "
            "Is the session locked / minimized / occluded?"
        )
        return 4

    print(
        "[PASS] sent Win/Alt+Home + 'notepad' + Enter. "
        "Open the screenshot and confirm Notepad is visible on the devbox."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
