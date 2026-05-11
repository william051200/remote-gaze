"""Screenshot helpers and file I/O utilities."""

import base64
import hashlib
import io
import sys
import time
from pathlib import Path
from datetime import datetime
from typing import Optional

import pyautogui
from PIL import Image, ImageGrab

from .models import Recording
from ..config import SCREENSHOT_HASH_LENGTH


def take_screenshot(region: tuple | None = None) -> Image.Image:
    """Capture a screenshot.

    ``region`` is ``(x, y, w, h)`` in virtual-screen coordinates. When
    omitted, the full primary screen is captured.

    On Windows we go straight to ``PIL.ImageGrab.grab`` with
    ``all_screens=True`` because ``pyautogui.screenshot(region=...)`` does
    not forward that flag and therefore returns black pixels for any
    region outside the primary monitor.
    """
    if sys.platform == "win32":
        if region is not None:
            x, y, w, h = region
            bbox = (int(x), int(y), int(x + w), int(y + h))
            return ImageGrab.grab(bbox=bbox, all_screens=True)
        return ImageGrab.grab(all_screens=True)
    if region is not None:
        return pyautogui.screenshot(region=region)
    return pyautogui.screenshot()


def take_stable_screenshot(
    region: Optional[tuple] = None,
    *,
    poll_interval: float = 0.05,
    max_wait: float = 0.8,
    phash_distance: int = 8,
) -> Image.Image:
    """Capture a screenshot once the screen has stopped animating.

    Repeatedly calls :func:`take_screenshot` and compares each new
    capture to the previous one via a 324-bit perceptual hash
    (``hash_size=18``). Returns the latest capture as soon as two
    consecutive captures are within ``phash_distance`` Hamming-distance
    bits of each other, or once ``max_wait`` seconds have elapsed.

    This makes the recorder and player capture *steady-state* pixels
    instead of mid-animation frames, eliminating a major source of
    spurious diffs when comparing recorded vs replayed screens.

    If ``imagehash`` cannot be imported, falls back to a single
    ``take_screenshot`` so capture still works in minimal environments.
    """
    try:
        import imagehash  # type: ignore
    except Exception:
        return take_screenshot(region=region)

    deadline = time.monotonic() + max(0.0, max_wait)
    prev_img = take_screenshot(region=region)
    prev_hash = imagehash.phash(prev_img, hash_size=18)
    while time.monotonic() < deadline:
        time.sleep(max(0.0, poll_interval))
        cur_img = take_screenshot(region=region)
        try:
            cur_hash = imagehash.phash(cur_img, hash_size=18)
            if (cur_hash - prev_hash) <= phash_distance:
                return cur_img
        except Exception:
            return cur_img
        prev_img, prev_hash = cur_img, cur_hash
    return prev_img


def _image_to_png_bytes(image: Image.Image) -> bytes:
    """Convert a PIL Image to raw PNG bytes."""
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return buf.getvalue()


def image_to_base64(image: Image.Image) -> str:
    """Encode a PIL Image to a base64 string (PNG format)."""
    return base64.b64encode(_image_to_png_bytes(image)).decode("ascii")


def base64_to_image(b64_str: str) -> Image.Image:
    """Decode a base64 string back to a PIL Image."""
    data = base64.b64decode(b64_str)
    return Image.open(io.BytesIO(data))


def encode_screenshot(image: Image.Image) -> tuple[str, str]:
    """Encode screenshot to (hash_key, base64_data). Hash is the dedup key."""
    raw = _image_to_png_bytes(image)
    hash_key = hashlib.sha256(raw).hexdigest()[:SCREENSHOT_HASH_LENGTH]
    b64 = base64.b64encode(raw).decode("ascii")
    return hash_key, b64


def save_recording(recording: Recording, output_dir: Path) -> Path:
    """Save recording JSON file."""
    output_dir.mkdir(parents=True, exist_ok=True)
    filepath = output_dir / f"{recording.name}.json"
    filepath.write_text(recording.to_json(), encoding="utf-8")
    return filepath


def load_recording(json_path: Path) -> Recording:
    """Load a recording from a JSON file."""
    return Recording.from_json(json_path.read_text(encoding="utf-8"))


def compare_screenshots(*args, **kwargs):
    """Backward-compatibility shim.

    The implementation now lives in
    :mod:`recorder.engine.verification`. New code should import directly
    from there; this re-export keeps older imports working.
    """
    # Lazy import to avoid a circular dep (engine.verification imports
    # base64_to_image / take_screenshot from this module).
    from ..engine.verification import compare_screenshots as _impl
    return _impl(*args, **kwargs)

