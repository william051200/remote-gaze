"""Playback engine — replays a recording step-by-step using pyautogui."""

import sys
import time
import threading
from pathlib import Path
from typing import Callable, Optional

import pyautogui

from .models import Recording, RecordedEvent
from .utils import load_recording
from .config import PYAUTOGUI_PAUSE
from . import config
from .key_mappings import PYNPUT_TO_PYAUTOGUI

# Disable pyautogui fail-safe pause for smoother playback
pyautogui.PAUSE = PYAUTOGUI_PAUSE

# Mapping from pynput key names to pyautogui key names
_PYNPUT_TO_PYAUTOGUI = PYNPUT_TO_PYAUTOGUI


# Win32 mouse_event flags. Using these directly (rather than pyautogui's
# wrapper) lets us click correctly on secondary monitors. pyautogui's click
# normalizes coordinates to 0-65535 of the **primary** monitor, so a click
# aimed at a non-primary display silently lands on the primary one.
_MOUSEEVENTF_LEFTDOWN = 0x0002
_MOUSEEVENTF_LEFTUP = 0x0004
_MOUSEEVENTF_RIGHTDOWN = 0x0008
_MOUSEEVENTF_RIGHTUP = 0x0010
_MOUSEEVENTF_MIDDLEDOWN = 0x0020
_MOUSEEVENTF_MIDDLEUP = 0x0040

_MOUSE_BUTTON_FLAGS = {
    "left":   (_MOUSEEVENTF_LEFTDOWN, _MOUSEEVENTF_LEFTUP),
    "right":  (_MOUSEEVENTF_RIGHTDOWN, _MOUSEEVENTF_RIGHTUP),
    "middle": (_MOUSEEVENTF_MIDDLEDOWN, _MOUSEEVENTF_MIDDLEUP),
}


def _native_click(x: int, y: int, button: str) -> None:
    """Click at absolute virtual-screen coords ``(x, y)`` on Windows.

    Uses ``SetCursorPos`` (which spans the virtual desktop correctly) plus
    ``mouse_event`` **without** ``MOUSEEVENTF_ABSOLUTE`` so the click fires
    at the cursor's actual position, regardless of which monitor it sits
    on.
    """
    import ctypes
    user32 = ctypes.windll.user32
    user32.SetCursorPos(int(x), int(y))
    down, up = _MOUSE_BUTTON_FLAGS.get(button, _MOUSE_BUTTON_FLAGS["left"])
    user32.mouse_event(down, 0, 0, 0, 0)
    user32.mouse_event(up, 0, 0, 0, 0)


class EventPlayer:
    def __init__(self, on_step: Optional[Callable[[RecordedEvent, int, "Recording"], None]] = None,
                 on_complete: Optional[Callable[[], None]] = None):
        self.on_step = on_step  # callback(event, total_steps, recording)
        self.on_complete = on_complete
        self._thread: Optional[threading.Thread] = None
        self._stop_flag = threading.Event()
        self._running = False

    @property
    def is_running(self) -> bool:
        return self._running

    def play(self, json_path: Path) -> None:
        """Start playback in a background thread."""
        if self._running:
            return

        recording = load_recording(json_path)
        self._stop_flag.clear()
        self._running = True
        self._thread = threading.Thread(
            target=self._playback_loop, args=(recording,), daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        """Request playback to stop."""
        self._stop_flag.set()

    def _playback_loop(self, recording: Recording) -> None:
        total = len(recording.events)
        try:
            for event in recording.events:
                if self._stop_flag.is_set():
                    break

                # Wait for the recorded delay
                if event.delay_from_previous > 0:
                    # Sleep in small increments so we can respond to stop quickly
                    remaining = event.delay_from_previous
                    while remaining > 0 and not self._stop_flag.is_set():
                        time.sleep(min(remaining, config.PLAYBACK_SLEEP_INCREMENT))
                        remaining -= config.PLAYBACK_SLEEP_INCREMENT

                if self._stop_flag.is_set():
                    break

                self._execute_event(event)

                # Match the recorder's settle-then-screenshot timing so the
                # GUI's "current" snapshot lines up with the "expected" one.
                if config.POST_INJECT_SETTLE_SECONDS > 0:
                    time.sleep(config.POST_INJECT_SETTLE_SECONDS)

                if self.on_step:
                    try:
                        self.on_step(event, total, recording)
                    except Exception:
                        pass
        finally:
            self._running = False
            if self.on_complete:
                self.on_complete()

    @staticmethod
    def _map_key(key_name: str) -> str:
        """Map a pynput key name to a pyautogui-compatible name."""
        return _PYNPUT_TO_PYAUTOGUI.get(key_name, key_name)

    @staticmethod
    def _execute_event(event: RecordedEvent) -> None:
        if event.type == "mouse_click":
            button = event.button or "left"
            if event.x is None or event.y is None:
                return
            mods = [EventPlayer._map_key(m) for m in (event.modifiers or [])]
            try:
                for m in mods:
                    pyautogui.keyDown(m)
                if sys.platform == "win32":
                    _native_click(event.x, event.y, button)
                else:
                    pyautogui.click(event.x, event.y, button=button)
            finally:
                for m in reversed(mods):
                    try:
                        pyautogui.keyUp(m)
                    except Exception:
                        pass

        elif event.type == "type_text":
            if not event.text:
                return
            try:
                pyautogui.write(event.text)
            except Exception:
                pass

        elif event.type == "key_press":
            if not event.key:
                return
            try:
                pyautogui.press(EventPlayer._map_key(event.key))
            except Exception:
                pass

        elif event.type == "hotkey":
            if not event.key:
                return
            mods = list(event.modifiers or [])
            key = event.key
            # Legacy: control codes \x01..\x1a captured from Ctrl+letter
            # before the recorder learned to decode them.
            if (isinstance(key, str) and len(key) == 1
                    and "\x01" <= key <= "\x1a"):
                key = chr(ord(key) + ord("a") - 1)
            # Legacy recordings may have captured shift+symbol (e.g.
            # ``hotkey(shift, '{')``) -- those can't be replayed via
            # pyautogui.hotkey because '{' isn't a recognized key name. The
            # OS already resolved shift+[ to '{' at record time, so just
            # type the resulting char.
            if mods == ["shift"] and key not in pyautogui.KEYBOARD_KEYS:
                try:
                    pyautogui.write(key)
                except Exception:
                    pass
                return
            try:
                mapped_mods = [EventPlayer._map_key(m) for m in mods]
                pyautogui.hotkey(*mapped_mods, EventPlayer._map_key(key))
            except Exception:
                pass

        elif event.type == "key_release":
            # Legacy recordings only -- new schema folds press+release together.
            # Tolerated as a no-op so old JSONs still play without crashing.
            return
