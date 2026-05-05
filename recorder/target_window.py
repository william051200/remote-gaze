"""Target window adapter for Model B.

Wraps `gaze.session.find_session_window` / `get_window_rect` so the
recorder and player can:
  * locate the Microsoft Windows App session window by title substring
  * filter mouse events to those that fall inside that window
  * convert between absolute screen coords and window-relative coords
  * report metadata (title, size) into the saved recording
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

# Make repo root importable so `from gaze import session` works whether
# the recorder is launched as `py -m recorder` or as a script.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from gaze import session as gaze_session  # noqa: E402


class TargetWindow:
    """Resolves a session window by title substring; tracks its rect.

    Call `refresh()` whenever you want the latest rect (e.g. once at
    record start, and once at playback start). The recorder also calls
    `refresh()` once per click in case the user has dragged the window.
    """

    def __init__(self, title_contains: str):
        if not title_contains:
            raise ValueError("TargetWindow requires a non-empty title_contains")
        self.title_contains = title_contains
        self.hwnd: Optional[int] = None
        self.rect: Optional[tuple] = None  # (left, top, right, bottom)

    # ── lookup ────────────────────────────────────────────────────────

    def refresh(self) -> bool:
        """Re-locate the session window and refresh `hwnd` + `rect`.

        Returns True on success, False if no matching window is visible.
        """
        hwnd = gaze_session.find_session_window(self.title_contains)
        if hwnd is None:
            self.hwnd = None
            self.rect = None
            return False
        self.hwnd = hwnd
        self.rect = gaze_session.get_window_rect(hwnd)
        return True

    # ── geometry ──────────────────────────────────────────────────────

    @property
    def size(self) -> Optional[tuple]:
        if self.rect is None:
            return None
        l, t, r, b = self.rect
        return (max(0, r - l), max(0, b - t))

    @property
    def origin(self) -> Optional[tuple]:
        if self.rect is None:
            return None
        return (self.rect[0], self.rect[1])

    def contains(self, abs_x: int, abs_y: int) -> bool:
        if self.rect is None:
            return False
        l, t, r, b = self.rect
        return l <= abs_x < r and t <= abs_y < b

    def to_relative(self, abs_x: int, abs_y: int) -> tuple:
        """Convert (abs_x, abs_y) → (rel_x, rel_y) using current rect."""
        if self.rect is None:
            return (abs_x, abs_y)
        return (abs_x - self.rect[0], abs_y - self.rect[1])

    def to_absolute(self, rel_x: int, rel_y: int) -> tuple:
        if self.rect is None:
            return (rel_x, rel_y)
        return (self.rect[0] + rel_x, self.rect[1] + rel_y)

    def screenshot_region(self) -> Optional[tuple]:
        """`(x, y, w, h)` for `take_screenshot(region=...)`, or None."""
        if self.rect is None:
            return None
        l, t, r, b = self.rect
        return (l, t, max(0, r - l), max(0, b - t))

    # ── focus ─────────────────────────────────────────────────────────

    def focus(self) -> None:
        """Bring the session window to the foreground (real focus, not
        just SetForegroundWindow). No-op if `hwnd` is None."""
        if self.hwnd is None:
            return
        gaze_session.focus_window(self.hwnd)
