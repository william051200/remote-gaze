"""Capture & playback engines."""

from .capture import EventRecorder  # noqa: F401
from .playback import EventPlayer  # noqa: F401
from .target_window import TargetWindow  # noqa: F401
from .verification import (  # noqa: F401
    compare_screenshots,
    verify_before_event,
    should_verify,
    make_diff_image,
)
