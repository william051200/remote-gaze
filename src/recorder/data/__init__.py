"""Recording data layer: dataclasses + screenshot/file I/O helpers."""

from .models import RecordedEvent, Recording  # noqa: F401
from .utils import (  # noqa: F401
    take_screenshot,
    image_to_base64,
    base64_to_image,
    encode_screenshot,
    save_recording,
    load_recording,
    compare_screenshots,
)
