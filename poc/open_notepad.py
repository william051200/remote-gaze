"""Open Notepad on the devbox via Start, type some text, then mouse-close it.

All settings live in poc/config.ini under [notepad] and [timing].
Usage:
    python poc/open_notepad.py                       # uses poc/config.ini
    python poc/open_notepad.py --config other.ini

Notes on the Start key:
    [notepad] start_method = win        works only when Windows App is FULLSCREEN
    [notepad] start_method = alt-home   works in windowed Windows App too (RDP shortcut)
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

import devbox


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="poc/config.ini")
    args = parser.parse_args(argv)

    cfg = devbox.load_config(Path(args.config))
    _, rect = devbox.focus_session(cfg)

    # Click inside the session FIRST so the remote desktop captures keyboard
    # input. Without this, window-level focus isn't enough - Windows App
    # routes keys to the container chrome and the Start key never reaches
    # the devbox. Click coords are configured via [action] click_x/click_y.
    warmup_x, warmup_y = devbox.relative_to_absolute(rect, cfg.click_x, cfg.click_y)
    print(f"[info] warm-up click inside session at ({warmup_x},{warmup_y})")
    devbox.click_at(warmup_x, warmup_y)
    time.sleep(0.4)

    print(f"[info] opening remote Start via method={cfg.start_method!r}")
    if cfg.start_method == "win":
        print(
            "       NOTE: 'win' only reaches the devbox if Windows App is "
            "FULLSCREEN. Switch to start_method = alt-home in config.ini "
            "if Notepad opens on the laptop instead."
        )
    devbox.open_remote_start(cfg.start_method)
    time.sleep(cfg.start_wait)

    print(f"[info] typing app name {cfg.app_name!r}")
    devbox.type_text(cfg.app_name, interval=0.05)
    time.sleep(0.4)

    print("[info] pressing Enter to launch")
    devbox.press("enter")
    time.sleep(cfg.launch_wait)

    if cfg.write_text:
        time.sleep(cfg.write_wait)
        print(f"[info] typing into Notepad: {cfg.write_text!r}")
        devbox.type_text(cfg.write_text)
        time.sleep(0.4)

    if cfg.close_x >= 0 and cfg.close_y >= 0:
        time.sleep(cfg.close_wait)
        abs_x, abs_y = devbox.relative_to_absolute(rect, cfg.close_x, cfg.close_y)
        print(
            f"[info] mouse-click to close at relative "
            f"({cfg.close_x},{cfg.close_y}) -> absolute ({abs_x},{abs_y})"
        )
        devbox.click_at(abs_x, abs_y)
        time.sleep(0.6)
    else:
        print("[info] close skipped (close_x or close_y is negative in config)")

    saved = devbox.screenshot_region(rect, cfg.notepad_screenshot_path)
    print(f"[info] saved screenshot: {saved}")

    if devbox.screenshot_looks_blank(saved):
        print("[FAIL] screenshot is blank or single-color. Session locked / minimized / occluded?")
        return 4

    print("[PASS] opened Notepad, typed text, closed via mouse click")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
