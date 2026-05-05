"""Screenshot helpers and file I/O utilities."""

import base64
import hashlib
import io
import sys
from pathlib import Path
from datetime import datetime

import pyautogui
from PIL import Image, ImageGrab

from .models import Recording
from .config import SCREENSHOT_HASH_LENGTH


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
