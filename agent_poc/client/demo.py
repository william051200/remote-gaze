"""End-to-end demo: laptop -> agent -> devbox UI.

  1. screenshot the devbox       -> out/before.png
  2. click at configured (x, y)  on the devbox
  3. type configured text        on the devbox
  4. wait settle_seconds
  5. screenshot the devbox       -> out/after.png

Run:
  python demo.py --config ../config.ini
"""

from __future__ import annotations

import argparse
import configparser
import sys
import time
from pathlib import Path

import requests


def _post(session, url, token, json_body, timeout):
    r = session.post(
        url,
        headers={"Authorization": f"Bearer {token}"},
        json=json_body,
        timeout=timeout,
    )
    r.raise_for_status()
    return r


def _save_screenshot(session, base_url, token, out_path: Path, timeout: float):
    r = session.post(
        f"{base_url}/screenshot",
        headers={"Authorization": f"Bearer {token}"},
        timeout=timeout,
    )
    r.raise_for_status()
    if r.headers.get("content-type", "").lower() != "image/png":
        raise RuntimeError(f"unexpected content-type: {r.headers.get('content-type')}")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(r.content)
    return out_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="../config.ini")
    args = parser.parse_args()

    cfg_path = Path(args.config)
    if not cfg_path.exists():
        print(f"[fatal] config not found: {cfg_path}")
        return 2
    cfg = configparser.ConfigParser()
    cfg.read(cfg_path, encoding="utf-8")

    host = cfg["connection"]["devbox_host"].strip()
    port = cfg.getint("connection", "devbox_port")
    token = cfg["connection"]["token"].strip()
    timeout = cfg.getfloat("timing", "http_timeout_seconds")
    settle = cfg.getfloat("timing", "settle_seconds")
    cx = cfg.getint("action", "click_x")
    cy = cfg.getint("action", "click_y")
    text = cfg["action"].get("type_text", "")

    base = f"http://{host}:{port}"
    out_dir = Path(__file__).resolve().parent / "out"

    s = requests.Session()
    try:
        before = _save_screenshot(s, base, token, out_dir / "before.png", timeout)
        print(f"[info] saved {before}")

        _post(s, f"{base}/click", token, {"x": cx, "y": cy}, timeout)
        print(f"[info] clicked ({cx},{cy}) on devbox")

        if text:
            _post(s, f"{base}/type", token, {"text": text}, timeout)
            print(f"[info] typed {text!r}")

        time.sleep(settle)

        after = _save_screenshot(s, base, token, out_dir / "after.png", timeout)
        print(f"[info] saved {after}")
    except requests.HTTPError as exc:
        print(f"[FAIL] HTTP {exc.response.status_code}: {exc.response.text[:300]}")
        return 3
    except requests.RequestException as exc:
        print(f"[FAIL] request error: {exc}")
        return 4

    if before.stat().st_size < 1024 or after.stat().st_size < 1024:
        print("[FAIL] one of the screenshots is suspiciously small")
        return 5

    print("\nPASS: open before.png and after.png to verify the click + typed text on the devbox.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
