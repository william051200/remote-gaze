"""Playback engine — replays a recording step-by-step using pyautogui."""

import sys
import time
import threading
from pathlib import Path
from typing import Callable, Optional

import pyautogui

from ..data.models import Recording, RecordedEvent
from ..data.utils import load_recording
from ..config import PYAUTOGUI_PAUSE
from .. import config
from ..config.key_mappings import PYNPUT_TO_PYAUTOGUI
from .target_window import TargetWindow
from . import verification

# Win-key names (raw pynput names + pyautogui name) that should be routed
# through platform.session.open_remote_start("win") so they get the 80 ms hold
# Windows App's RDP needs to forward them to the remote session.
_WIN_KEY_NAMES = {"cmd", "cmd_l", "cmd_r", "winleft", "winright"}

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
                 on_complete: Optional[Callable[[str], None]] = None,
                 on_verification_fail: Optional[Callable[[RecordedEvent, str, object, object], None]] = None,
                 on_step_verified: Optional[Callable[[RecordedEvent, int, int, "Recording", object, object, Optional[str], bool], None]] = None):
        # callback(event, total_steps, recording)
        self.on_step = on_step
        # callback(status) where status ∈ {"completed","stopped","verification_failed"}
        self.on_complete = on_complete
        # callback(event, diff_text, expected_image, live_image) on
        # pre-action verification failure (called before halting).
        # diff_text is pre-formatted by the comparison helper so the UI
        # doesn't need to know which method ran (e.g. "3.21%" or
        # "60 / 324 bits").
        self.on_verification_fail = on_verification_fail
        # callback(event, idx, total, recording, expected_or_None,
        # live_or_None, diff_text_or_None, passed) fired AFTER each
        # verification attempt (success or fail) AND for events without
        # verification (with all None / passed=True). Lets the GUI cache
        # the pre-action images so step display + browse + fail-state
        # all share the same baseline as verification.
        self.on_step_verified = on_step_verified
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
        # Model B setup: if the recording is window-relative, find the
        # session window once at the start, focus it, and warm-up click
        # so Windows App routes keyboard input to the remote desktop.
        target: Optional[TargetWindow] = None
        if recording.window_relative and recording.window_title_contains:
            target = TargetWindow(recording.window_title_contains)
            if not target.refresh():
                print(
                    f"[player] target window matching "
                    f"{recording.window_title_contains!r} not found - "
                    f"playback aborted"
                )
                self._running = False
                if self.on_complete:
                    self.on_complete("stopped")
                return
            target.focus()
            time.sleep(0.3)
            # focus() may have called SW_RESTORE on a minimized window;
            # the rect we cached during refresh() is the pre-restore
            # off-screen rect (-32000, -32000, ...). Re-read it now that
            # the window is visible so the warm-up click and all
            # subsequent window-relative clicks land in the right spot.
            target.refresh()
            # Warm-up click in the center of the window so Windows App
            # gives the remote desktop keyboard focus. Without this, the
            # first Win-key/Alt-Home goes to the container chrome.
            cx = (target.rect[0] + target.rect[2]) // 2
            cy = (target.rect[1] + target.rect[3]) // 2
            _native_click(cx, cy, "left")
            time.sleep(0.4)
            # Warn if the window is a different size than at record time;
            # rel coords still apply, but UI elements may have shifted.
            if recording.window_size_at_record:
                rec_w, rec_h = recording.window_size_at_record
                cur_w, cur_h = target.size or (0, 0)
                if (rec_w, rec_h) != (cur_w, cur_h):
                    print(
                        f"[player] WARN session window is {cur_w}x{cur_h}, "
                        f"recording was {rec_w}x{rec_h}; click positions "
                        f"may not line up"
                    )

        # Model B's warm-up click can mutate the screen between record-
        # time and playback-time, so skip BEFORE-verification on the first
        # event for window-relative recordings.
        warmup_skipped_event_index = 0 if (target is not None) else -1
        # Final status reported via on_complete. Defaults to completed;
        # set to "stopped" on stop_flag, "verification_failed" on halt.
        status = "completed"

        try:
            for idx, event in enumerate(recording.events):
                if self._stop_flag.is_set():
                    status = "stopped"
                    break

                # Wait for the recorded delay
                if event.delay_from_previous > 0:
                    # Sleep in small increments so we can respond to stop quickly
                    remaining = event.delay_from_previous
                    while remaining > 0 and not self._stop_flag.is_set():
                        time.sleep(min(remaining, config.PLAYBACK_SLEEP_INCREMENT))
                        remaining -= config.PLAYBACK_SLEEP_INCREMENT

                if self._stop_flag.is_set():
                    status = "stopped"
                    break

                # ── BEFORE-action verification ─────────────────────────
                cap_state = {"expected": None, "live": None,
                             "diff_text": None, "passed": True}

                def _capture_cb(_ev, expected, live, diff_text, passed,
                                state=cap_state):
                    state["expected"] = expected
                    state["live"] = live
                    state["diff_text"] = diff_text
                    state["passed"] = passed

                if verification.should_verify(
                    event, recording, warmup_skipped_event_index, idx,
                ):
                    halted = verification.verify_before_event(
                        event, recording, target,
                        self._stop_flag, self.on_verification_fail,
                        on_capture=_capture_cb,
                    )
                    if halted:
                        # Verification failed and policy is halt.
                        # on_step_verified still fires so the GUI caches
                        # the captures alongside the fail banner.
                        if self.on_step_verified:
                            try:
                                self.on_step_verified(
                                    event, idx, total, recording,
                                    cap_state["expected"], cap_state["live"],
                                    cap_state["diff_text"], cap_state["passed"],
                                )
                            except Exception:
                                pass
                        status = "verification_failed"
                        break
                    if self._stop_flag.is_set():
                        status = "stopped"
                        break

                if self.on_step_verified:
                    try:
                        self.on_step_verified(
                            event, idx, total, recording,
                            cap_state["expected"], cap_state["live"],
                            cap_state["diff_text"], cap_state["passed"],
                        )
                    except Exception:
                        pass

                self._execute_event(event, target)

                # Stable-capture in the GUI's _on_playback_step now waits
                # for the screen to settle, so no explicit sleep here.

                if self.on_step:
                    try:
                        self.on_step(event, total, recording)
                    except Exception:
                        pass
        finally:
            self._running = False
            if self.on_complete:
                self.on_complete(status)

    def _verify_before(self, event: RecordedEvent, recording: Recording,
                       target: Optional[TargetWindow]) -> bool:
        """Deprecated thin wrapper kept for backward compatibility.

        The verification logic now lives in
        :mod:`recorder.engine.verification`. Callers should prefer
        ``verification.verify_before_event`` directly.
        """
        return verification.verify_before_event(
            event, recording, target, self._stop_flag, self.on_verification_fail,
        )

    @staticmethod
    def _map_key(key_name: str) -> str:
        """Map a pynput key name to a pyautogui-compatible name."""
        return _PYNPUT_TO_PYAUTOGUI.get(key_name, key_name)

    @staticmethod
    def _execute_event(event: RecordedEvent, target: Optional[TargetWindow] = None) -> None:
        if event.type == "mouse_click":
            button = event.button or "left"
            if event.x is None or event.y is None:
                return
            # Model B: stored coords are window-relative. Refresh the
            # rect so a window dragged between record and playback (or
            # mid-playback) still gets clicks in the right spot.
            click_x, click_y = event.x, event.y
            if target is not None:
                target.refresh()
                click_x, click_y = target.to_absolute(event.x, event.y)
            mods = [EventPlayer._map_key(m) for m in (event.modifiers or [])]
            try:
                for m in mods:
                    pyautogui.keyDown(m)
                if sys.platform == "win32":
                    _native_click(click_x, click_y, button)
                else:
                    pyautogui.click(click_x, click_y, button=button)
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
            # Win-key needs an 80ms hold to be forwarded by Windows App
            # to the remote session. Plain pyautogui.press is too fast.
            if event.key in _WIN_KEY_NAMES:
                try:
                    from ..platform import session as gaze_session
                    gaze_session.open_remote_start("win")
                except Exception:
                    pyautogui.press("winleft")
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
