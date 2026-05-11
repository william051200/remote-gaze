"""Passive event capture engine using pynput for global mouse/keyboard listening.

Events flow naturally to the OS / target app -- the listener observes them and
the worker thread takes a screenshot AFTER each event. To avoid screenshotting
every keystroke when the user is typing, consecutive printable characters are
buffered and emitted as a single ``type_text`` event when the buffer flushes.

Flush triggers: any non-printable key, any mouse click, idle timeout, recorder
stop. The screenshot for a ``type_text`` event is taken at flush time, which
naturally captures the post-typing UI state.

Event types written to the recording:
    * ``mouse_click`` -- single click (optionally with held ``modifiers``)
    * ``type_text``   -- buffered run of plain printable chars
    * ``key_press``   -- single non-printable key tap (Enter/Tab/F-keys/...)
    * ``hotkey``      -- modifier(s) + key chord (e.g. Ctrl+S, Alt+Tab)
"""

import queue
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

from pynput import keyboard, mouse

from .config import WORKER_JOIN_TIMEOUT
from . import config
from .models import RecordedEvent, Recording
from .utils import encode_screenshot, save_recording, take_screenshot

_MODIFIER_NAMES = {
    "ctrl", "ctrl_l", "ctrl_r",
    "alt", "alt_l", "alt_r", "alt_gr",
    "shift", "shift_l", "shift_r",
    "cmd", "cmd_l", "cmd_r",
}

# Modifiers that turn a keystroke into a "command" (hotkey) rather than
# typing. Shift is intentionally NOT here -- shift just selects the upper
# variant of a key (shift+[ = {), and pynput already delivers that resulting
# character via key.char, so it should be treated as plain typing.
_COMMAND_MODIFIER_NAMES = {
    "ctrl", "ctrl_l", "ctrl_r",
    "alt", "alt_l", "alt_r", "alt_gr",
    "cmd", "cmd_l", "cmd_r",
}

# Map raw pynput modifier names to the canonical names pyautogui understands.
# pyautogui uses "win" for the Windows/cmd key.
_MOD_CANON = {
    "ctrl": "ctrl", "ctrl_l": "ctrl", "ctrl_r": "ctrl",
    "alt": "alt", "alt_l": "alt", "alt_r": "alt", "alt_gr": "alt",
    "shift": "shift", "shift_l": "shift", "shift_r": "shift",
    "cmd": "win", "cmd_l": "win", "cmd_r": "win",
}

# Stable ordering of canonical modifiers -- gives consistent recordings and
# makes hotkey descriptions read naturally (Ctrl+Shift+Alt+Win+key).
_MOD_ORDER = {"ctrl": 0, "shift": 1, "alt": 2, "win": 3}


def _canon_mods(raw_mods) -> list:
    """Convert a set of raw pynput modifier names into a sorted list of
    canonical names with duplicates removed."""
    canon = {_MOD_CANON[m] for m in raw_mods if m in _MOD_CANON}
    return sorted(canon, key=lambda m: _MOD_ORDER.get(m, 99))


class EventRecorder:
    """Passive recorder. See module docstring for the capture model."""

    def __init__(
        self,
        output_base_dir: Path,
        on_event: Optional[Callable[[RecordedEvent], None]] = None,
        ignore_window_hwnd: Optional[int] = None,
        ignore_keys: Optional[set] = None,
        monitor: Optional["Monitor"] = None,
        target_window: Optional["TargetWindow"] = None,
    ):
        self.output_base_dir = output_base_dir
        self.on_event = on_event
        self.ignore_window_hwnd = ignore_window_hwnd
        # Key names (per ``_key_to_str``) that should be silently ignored
        # by the recorder -- typically the stop hotkey (e.g. ``f6``) so it
        # doesn't appear in the recording or trigger key-repeat noise.
        self.ignore_keys: set = set(ignore_keys or ())
        # Optional monitor scoping: when set, screenshots are cropped to
        # this monitor's region and clicks outside it are ignored.
        self.monitor = monitor
        # Optional Model B target: when set, mouse coords are stored
        # relative to this window, screenshots are cropped to it, and
        # clicks outside it are dropped. Mutually exclusive with monitor
        # scoping (target_window wins if both are set).
        self.target_window = target_window

        self.recording: Optional[Recording] = None
        self._start_time: float = 0.0
        self._last_event_time: float = 0.0
        self._step_counter: int = 0

        self._mouse_listener: Optional[mouse.Listener] = None
        self._keyboard_listener: Optional[keyboard.Listener] = None

        self._event_queue: queue.Queue = queue.Queue()
        self._worker_thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self._running = False

        # Currently-held raw pynput modifier names. Used to (a) decide whether
        # printable keystrokes should be batched as plain typing or folded into
        # a hotkey, and (b) attach modifiers to clicks/hotkeys that consume them.
        self._mods_down: set = set()
        # Subset of _mods_down that has NOT yet been consumed by a subsequent
        # key/click. If a modifier is released while still in this set, it was
        # a bare tap (e.g. Windows key alone -> open Start menu) and we emit a
        # key_press event for it on release.
        self._mods_unused: set = set()

        # Text-buffering state, mutated only by the worker thread.
        self._text_buffer: list = []
        self._text_step: int = 0
        self._text_timestamp: float = 0.0
        self._text_delay: float = 0.0
        self._idle_timer: Optional[threading.Timer] = None

    # ── public API ────────────────────────────────────────────────────

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def event_count(self) -> int:
        with self._lock:
            return len(self.recording.events) if self.recording else 0

    def start(self, name: Optional[str] = None) -> None:
        if self._running:
            return

        if not name:
            name = f"recording_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        self.recording = Recording(name=name)
        if self.monitor is not None:
            self.recording.monitor = self.monitor.to_dict()
        # Model B: lock onto the target window NOW so all events use the
        # same rect. If we can't find it, fall back to legacy mode for
        # this session and warn via stdout.
        if self.target_window is not None:
            if self.target_window.refresh():
                self.recording.window_relative = True
                self.recording.window_title_contains = self.target_window.title_contains
                w, h = self.target_window.size or (0, 0)
                self.recording.window_size_at_record = [w, h]
            else:
                print(
                    f"[recorder] target window matching "
                    f"{self.target_window.title_contains!r} not found - "
                    f"recording absolute screen coords instead"
                )
        self._start_time = time.time()
        self._last_event_time = self._start_time
        self._step_counter = 0
        self._running = True
        self._mods_down.clear()
        self._mods_unused.clear()
        self._text_buffer.clear()

        self._event_queue = queue.Queue()
        self._worker_thread = threading.Thread(target=self._event_worker, daemon=True)
        self._worker_thread.start()

        self._mouse_listener = mouse.Listener(on_click=self._on_mouse_click)
        self._keyboard_listener = keyboard.Listener(
            on_press=self._on_key_press,
            on_release=self._on_key_release,
        )
        self._mouse_listener.start()
        self._keyboard_listener.start()

    def stop(self) -> Optional[Path]:
        """Stop recording and save. Returns path to the saved recording JSON."""
        if not self._running:
            return None

        self._running = False

        if self._mouse_listener:
            self._mouse_listener.stop()
        if self._keyboard_listener:
            self._keyboard_listener.stop()
        self._cancel_idle_timer()

        # Flush any pending typed-text buffer before draining the queue.
        self._event_queue.put(("flush_text", None))
        self._event_queue.put((None, None))  # sentinel
        if self._worker_thread:
            self._worker_thread.join(timeout=WORKER_JOIN_TIMEOUT)

        if self.recording:
            self.recording.events.sort(key=lambda e: e.step)
            return save_recording(self.recording, self.output_base_dir)
        return None

    # ── listener callbacks (pynput hook threads) ──────────────────────

    def _on_mouse_click(self, x: int, y: int, button: mouse.Button, pressed: bool) -> None:
        if not pressed or not self._running:
            return
        if self._is_own_window_click(int(x), int(y)):
            return
        if not self._point_in_monitor(int(x), int(y)):
            return
        # Model B: drop clicks outside the target window, refresh the
        # rect on every click so dragging the window mid-recording still
        # works, and store coords as window-relative.
        rec_x, rec_y = int(x), int(y)
        if self.target_window is not None and self.recording is not None \
                and self.recording.window_relative:
            self.target_window.refresh()
            if not self.target_window.contains(int(x), int(y)):
                return
            rec_x, rec_y = self.target_window.to_relative(int(x), int(y))
        # Any mouse click ends a typing run.
        self._event_queue.put(("flush_text", None))
        payload = {"x": rec_x, "y": rec_y, "button": button.name}
        mods = _canon_mods(self._mods_down)
        if mods:
            payload["modifiers"] = mods
        # Whatever modifiers were held are now "used" by this click.
        self._mods_unused.clear()
        self._event_queue.put(("mouse_click", payload))

    def _on_key_press(self, key) -> None:
        if not self._running:
            return

        name = self._key_to_str(key)
        if name in self.ignore_keys:
            return

        if name in _MODIFIER_NAMES:
            # Track modifier state. The next key/click may consume it; if it
            # is released without being consumed (bare tap), we'll emit a
            # key_press for it in _on_key_release. Ignore key-repeat: a
            # modifier that is already down stays "unused" until something
            # consumes it.
            if name not in self._mods_down:
                self._mods_down.add(name)
                self._mods_unused.add(name)
                self._event_queue.put(("flush_text", None))
            return

        char = self._printable_char(key)
        # Only Ctrl/Alt/Win turn a keystroke into a hotkey. Shift on its own
        # just produces an upper-variant printable char (shift+[ = {), which
        # pynput already delivers via key.char and we should batch as typing.
        cmd_mods_held = any(m in _COMMAND_MODIFIER_NAMES for m in self._mods_down)

        if char is not None and not cmd_mods_held:
            # Plain typing -- batch. Shift was used (it produced this char) but
            # only as a "shift" hint, no need to record it as modifier.
            self._mods_unused.discard("shift")
            self._mods_unused.discard("shift_l")
            self._mods_unused.discard("shift_r")
            self._event_queue.put(("text_char", {"char": char}))
            return

        # Non-printable, or printable + Ctrl/Alt/Win. Either way, end any
        # ongoing typing run and emit the discrete event.
        self._event_queue.put(("flush_text", None))

        if self._mods_down:
            # Any mod (including bare shift) makes this a chord. Examples:
            # Shift+Tab, Shift+F2, Ctrl+S, Alt+F4, Win+R.
            mods = _canon_mods(self._mods_down)
            chord_key = char if char is not None else name
            # Ctrl-modified printables surface as control codes (\x01..\x1a).
            # Decode them back to the alphabetic letter so the player can
            # replay e.g. ctrl+a rather than ctrl+'\x01' (which pyautogui
            # rejects).
            if (isinstance(chord_key, str) and len(chord_key) == 1
                    and "\x01" <= chord_key <= "\x1a"):
                chord_key = chr(ord(chord_key) + ord("a") - 1)
            self._event_queue.put((
                "hotkey",
                {"key": chord_key, "modifiers": mods},
            ))
        else:
            self._event_queue.put(("key_press", {"key": name}))

        # Whatever modifiers were held have now been consumed.
        self._mods_unused.clear()

    def _on_key_release(self, key) -> None:
        if not self._running:
            return

        name = self._key_to_str(key)
        if name in self.ignore_keys:
            return

        if name in _MODIFIER_NAMES:
            self._mods_down.discard(name)
            if name in self._mods_unused:
                # Bare modifier tap (press+release with nothing in between).
                # Examples: Windows key alone -> Start menu, Alt alone ->
                # focus menu bar. Emit a key_press so playback fires the same
                # tap. We emit the canonical name so the player can map it
                # cleanly to pyautogui (e.g. cmd_l -> winleft).
                self._mods_unused.discard(name)
                self._event_queue.put(("flush_text", None))
                self._event_queue.put(("key_press", {"key": name}))

    # ── worker (sequential, owns screenshots) ─────────────────────────

    def _event_worker(self) -> None:
        while True:
            kind, payload = self._event_queue.get()
            if kind is None:
                self._flush_text_buffer()
                break
            try:
                if kind == "flush_text":
                    self._flush_text_buffer()
                elif kind == "text_char":
                    self._handle_text_char(payload["char"])
                elif kind == "mouse_click":
                    self._handle_mouse_click(payload)
                elif kind == "key_press":
                    self._handle_key_press(payload)
                elif kind == "hotkey":
                    self._handle_hotkey(payload)
            except Exception:
                pass

    def _handle_text_char(self, char: str) -> None:
        if not self._text_buffer:
            step, timestamp, delay = self._allocate_step()
            self._text_step = step
            self._text_timestamp = timestamp
            self._text_delay = delay

        self._text_buffer.append(char)

        # Reset the idle-flush timer.
        self._cancel_idle_timer()
        self._idle_timer = threading.Timer(
            config.TEXT_BUFFER_IDLE_FLUSH_SECONDS,
            lambda: self._event_queue.put(("flush_text", None)),
        )
        self._idle_timer.daemon = True
        self._idle_timer.start()

    def _flush_text_buffer(self) -> None:
        self._cancel_idle_timer()
        if not self._text_buffer:
            return
        text = "".join(self._text_buffer)
        self._text_buffer.clear()

        # Brief pause so the OS finishes painting the typed chars before we
        # snapshot the screen.
        time.sleep(config.POST_INJECT_SETTLE_SECONDS)
        screenshot = self._capture_screenshot()

        self._append_event(RecordedEvent(
            step=self._text_step,
            type="type_text",
            timestamp=round(self._text_timestamp, 3),
            delay_from_previous=round(self._text_delay, 3),
            screenshot=screenshot,
            text=text,
        ))

    def _handle_mouse_click(self, p: dict) -> None:
        step, timestamp, delay = self._allocate_step()
        # Settle so any modifier-down + click effect has time to paint before
        # we snapshot.
        time.sleep(config.POST_INJECT_SETTLE_SECONDS)
        screenshot = self._capture_screenshot()
        self._append_event(RecordedEvent(
            step=step, type="mouse_click",
            timestamp=round(timestamp, 3),
            delay_from_previous=round(delay, 3),
            screenshot=screenshot,
            x=p["x"], y=p["y"], button=p["button"],
            modifiers=p.get("modifiers"),
        ))

    def _handle_key_press(self, p: dict) -> None:
        step, timestamp, delay = self._allocate_step()
        time.sleep(config.POST_INJECT_SETTLE_SECONDS)
        screenshot = self._capture_screenshot()
        self._append_event(RecordedEvent(
            step=step, type="key_press",
            timestamp=round(timestamp, 3),
            delay_from_previous=round(delay, 3),
            screenshot=screenshot,
            key=p["key"],
        ))

    def _handle_hotkey(self, p: dict) -> None:
        step, timestamp, delay = self._allocate_step()
        time.sleep(config.POST_INJECT_SETTLE_SECONDS)
        screenshot = self._capture_screenshot()
        self._append_event(RecordedEvent(
            step=step, type="hotkey",
            timestamp=round(timestamp, 3),
            delay_from_previous=round(delay, 3),
            screenshot=screenshot,
            key=p["key"],
            modifiers=p.get("modifiers"),
        ))

    # ── helpers ───────────────────────────────────────────────────────

    def _allocate_step(self) -> tuple:
        with self._lock:
            now = time.time()
            timestamp = now - self._start_time
            delay = now - self._last_event_time
            self._last_event_time = now
            self._step_counter += 1
            return self._step_counter, timestamp, delay

    def _capture_screenshot(self) -> str:
        try:
            region = None
            # Target window crops win over monitor crop when both are set.
            if self.target_window is not None and self.target_window.rect is not None:
                region = self.target_window.screenshot_region()
            elif self.monitor is not None:
                region = (self.monitor.x, self.monitor.y,
                          self.monitor.width, self.monitor.height)
            screenshot = take_screenshot(region=region)
            hash_key, b64 = encode_screenshot(screenshot)
            with self._lock:
                if self.recording and hash_key not in self.recording.screenshots:
                    self.recording.screenshots[hash_key] = b64
            return hash_key
        except Exception:
            return ""

    def _append_event(self, event: RecordedEvent) -> None:
        with self._lock:
            if self.recording:
                self.recording.events.append(event)
        if self.on_event:
            try:
                self.on_event(event)
            except Exception:
                pass

    def _cancel_idle_timer(self) -> None:
        timer = self._idle_timer
        if timer is not None:
            timer.cancel()
            self._idle_timer = None

    def _point_in_monitor(self, x: int, y: int) -> bool:
        """True if the click should be recorded given the monitor scope.

        Returns True when no monitor is configured (legacy behavior) or
        when (x, y) falls within the configured monitor's bounds.
        """
        m = self.monitor
        if m is None:
            return True
        return (m.x <= x < m.x + m.width
                and m.y <= y < m.y + m.height)

    def _is_own_window_click(self, x: int, y: int) -> bool:
        if self.ignore_window_hwnd is None:
            return False
        try:
            import ctypes
            from ctypes import wintypes
            user32 = ctypes.windll.user32
            # Set restypes so HWNDs aren't truncated to 32-bit on 64-bit Windows.
            user32.WindowFromPoint.restype = wintypes.HWND
            user32.WindowFromPoint.argtypes = [wintypes.POINT]
            user32.GetAncestor.restype = wintypes.HWND
            user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
            hwnd = user32.WindowFromPoint(wintypes.POINT(int(x), int(y)))
            root_hwnd = user32.GetAncestor(hwnd, 2)  # GA_ROOT
            return bool(root_hwnd) and root_hwnd == self.ignore_window_hwnd
        except Exception:
            return False

    @staticmethod
    def _key_to_str(key) -> str:
        if isinstance(key, keyboard.KeyCode):
            return key.char if key.char else str(key)
        if isinstance(key, keyboard.Key):
            return key.name
        return str(key)

    @staticmethod
    def _printable_char(key) -> Optional[str]:
        if isinstance(key, keyboard.KeyCode) and key.char:
            ch = key.char
            # Ctrl-modified chars surface as control codes (\x01..\x1a);
            # those are not "printable" for buffering.
            if len(ch) == 1 and ch.isprintable():
                return ch
        return None
