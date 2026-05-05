"""Smoke test: focus the Windows App session, click + type, screenshot.

All settings live in poc/config.ini.
Usage:
    python poc/rdp_click.py                       # uses poc/config.ini
    python poc/rdp_click.py --config other.ini
    python poc/rdp_click.py --no-launch           # skip best-effort launch
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

import devbox


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="poc/config.ini")
    parser.add_argument(
        "--no-launch",
        action="store_true",
        help="Skip launching Windows App even if launch_uri is set in config.",
    )
    args = parser.parse_args(argv)

    cfg = devbox.load_config(Path(args.config))

    if not args.no_launch:
        devbox.best_effort_launch(cfg.launch_uri)
        if cfg.launch_uri:
            time.sleep(2.0)

    _, rect = devbox.focus_session(cfg)

    abs_x, abs_y = devbox.relative_to_absolute(rect, cfg.click_x, cfg.click_y)
    print(f"[info] clicking at relative ({cfg.click_x},{cfg.click_y}) -> absolute ({abs_x},{abs_y})")
    devbox.click_at(abs_x, abs_y)
    if cfg.type_text:
        print(f"[info] typing {cfg.type_text!r}")
        devbox.type_text(cfg.type_text, interval=0.03)

    time.sleep(cfg.settle_delay)

    saved = devbox.screenshot_region(rect, cfg.screenshot_path)
    print(f"[info] saved screenshot: {saved}")

    if devbox.screenshot_looks_blank(saved):
        print("[FAIL] screenshot is blank or single-color. Session locked / minimized / occluded?")
        return 4

    print("[PASS] click + screenshot completed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
