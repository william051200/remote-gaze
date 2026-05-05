"""Devbox agent: tiny HTTP API the laptop uses to drive the devbox UI.

Endpoints (all require Authorization: Bearer <GAZE_TOKEN>):
  GET  /healthz                                   -> JSON
  POST /click       {x, y, button?, clicks?}      -> {"ok": true}
  POST /move        {x, y}                        -> {"ok": true}
  POST /type        {text, interval_ms?}          -> {"ok": true}
  POST /screenshot                                -> image/png

This process MUST run inside the interactive Windows session (i.e. launched
from a terminal in your logged-in Windows App session). A Windows service in
session 0 can serve HTTP but cannot see or click the desktop.

Usage on the devbox:
  set GAZE_TOKEN=some-long-secret
  python server.py --host 0.0.0.0 --port 8765
"""

from __future__ import annotations

import argparse
import ctypes
import io
import os
import socket
import sys

# DPI awareness MUST come before any screen / input call. Per-Monitor V2 = -4.
def _enable_dpi_awareness() -> None:
    try:
        ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
        return
    except (AttributeError, OSError):
        pass
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
        return
    except (AttributeError, OSError):
        pass
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except (AttributeError, OSError):
        pass


_enable_dpi_awareness()

import pyautogui  # noqa: E402
from fastapi import Depends, FastAPI, Header, HTTPException, Response  # noqa: E402
from PIL import ImageGrab  # noqa: E402
from pydantic import BaseModel, Field  # noqa: E402

pyautogui.FAILSAFE = False  # don't abort if mouse hits a screen corner

TOKEN = os.environ.get("GAZE_TOKEN", "").strip()
if not TOKEN:
    print(
        "[fatal] GAZE_TOKEN env var is empty. Set a long shared secret "
        "before starting the agent.",
        file=sys.stderr,
    )
    sys.exit(2)


def require_token(authorization: str | None = Header(default=None)) -> None:
    expected = f"Bearer {TOKEN}"
    if authorization != expected:
        raise HTTPException(status_code=401, detail="bad or missing token")


app = FastAPI(title="remote-gaze agent", version="0.1.0")


class ClickReq(BaseModel):
    x: int
    y: int
    button: str = Field(default="left", pattern="^(left|right|middle)$")
    clicks: int = Field(default=1, ge=1, le=5)


class MoveReq(BaseModel):
    x: int
    y: int


class TypeReq(BaseModel):
    text: str
    interval_ms: int = Field(default=30, ge=0, le=2000)


@app.get("/healthz", dependencies=[Depends(require_token)])
def healthz() -> dict:
    w, h = pyautogui.size()
    return {
        "ok": True,
        "host": socket.gethostname(),
        "user": os.environ.get("USERNAME", "?"),
        "screen": [w, h],
        "version": app.version,
    }


@app.post("/click", dependencies=[Depends(require_token)])
def click(req: ClickReq) -> dict:
    pyautogui.click(x=req.x, y=req.y, clicks=req.clicks, button=req.button)
    return {"ok": True}


@app.post("/move", dependencies=[Depends(require_token)])
def move(req: MoveReq) -> dict:
    pyautogui.moveTo(req.x, req.y, duration=0.1)
    return {"ok": True}


@app.post("/type", dependencies=[Depends(require_token)])
def type_text(req: TypeReq) -> dict:
    pyautogui.typewrite(req.text, interval=req.interval_ms / 1000.0)
    return {"ok": True}


@app.post("/screenshot", dependencies=[Depends(require_token)])
def screenshot() -> Response:
    # all_screens=True so multi-monitor devboxes don't return black for the
    # non-primary monitor (per repo memory).
    img = ImageGrab.grab(all_screens=True)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return Response(content=buf.getvalue(), media_type="image/png")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()

    import uvicorn

    print(f"[info] agent starting on {args.host}:{args.port}")
    print(f"[info] token length = {len(TOKEN)} (from GAZE_TOKEN)")
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
