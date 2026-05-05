"""Step-wise connectivity check from laptop -> devbox agent.

Tells you EXACTLY which layer is broken:
  1. DNS    \u2014 can we resolve devbox_host?
  2. TCP    \u2014 can we open a socket to devbox_port?
  3. AUTH   \u2014 does the token work?
  4. AGENT  \u2014 does /healthz return sane info?

Run:
  python check_connectivity.py --config ../config.ini
"""

from __future__ import annotations

import argparse
import configparser
import socket
import sys
from pathlib import Path

import requests


def _hint(title: str, lines: list[str]) -> None:
    print(f"\n  HINT: {title}")
    for ln in lines:
        print(f"    - {ln}")


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

    print(f"[1/4] DNS resolve {host} ...")
    try:
        ip = socket.gethostbyname(host)
        print(f"      ok -> {ip}")
    except socket.gaierror as exc:
        print(f"      FAIL: {exc}")
        _hint(
            "DNS resolution failed",
            [
                "Check the hostname spelling in config.ini",
                "If the devbox name is only resolvable on the corp network, connect to VPN",
                "Try the devbox IP directly instead of hostname",
            ],
        )
        return 10

    print(f"[2/4] TCP connect {ip}:{port} ...")
    try:
        with socket.create_connection((ip, port), timeout=timeout):
            pass
        print("      ok")
    except (TimeoutError, ConnectionRefusedError, OSError) as exc:
        print(f"      FAIL: {exc}")
        _hint(
            "TCP connection failed (this is the most common blocker)",
            [
                "Is the agent running on the devbox? RDP in via Windows App and start it.",
                f"On the devbox: netstat -an | findstr {port}  (should show LISTENING)",
                "Check Windows Defender Firewall on the devbox - allow inbound TCP for the chosen port",
                "Microsoft Dev Box / Cloud PC may block inbound by default (NSG / network policy). Confirm with your admin",
                "Try running the agent on a different port (e.g., 443, 8443) in case the chosen one is blocked",
            ],
        )
        return 11

    url = f"http://{host}:{port}/healthz"
    print(f"[3/4] HTTP GET {url} (with token) ...")
    try:
        r = requests.get(
            url,
            headers={"Authorization": f"Bearer {token}"},
            timeout=timeout,
        )
    except requests.RequestException as exc:
        print(f"      FAIL: {exc}")
        return 12

    if r.status_code == 401:
        print(f"      FAIL: 401 Unauthorized")
        _hint(
            "Token mismatch",
            [
                "config.ini token must match GAZE_TOKEN env var on the devbox",
                "On the devbox: echo %GAZE_TOKEN%   (cmd) or  $env:GAZE_TOKEN   (powershell)",
            ],
        )
        return 13
    if r.status_code != 200:
        print(f"      FAIL: HTTP {r.status_code} - {r.text[:200]}")
        return 14

    print(f"      ok ({r.status_code})")
    print("[4/4] healthz payload:")
    try:
        payload = r.json()
    except ValueError:
        print(f"      FAIL: response not JSON: {r.text[:200]}")
        return 15
    for k, v in payload.items():
        print(f"      {k}: {v}")

    print("\nPASS: laptop can reach the devbox agent. Proceed to demo.py.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
