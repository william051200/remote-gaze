"""Tkinter GUI control panel for the recorder/player.

Warm light theme inspired by Notion's design system.
Design reference: https://github.com/VoltAgent/awesome-design-md
"""

import os
import tkinter as tk
from tkinter import filedialog, messagebox
from pathlib import Path
from typing import Optional

from PIL import Image, ImageTk
from pynput import keyboard as kb

from ..data.models import RecordedEvent, Recording
from ..engine.capture import EventRecorder
from ..engine.playback import EventPlayer
from ..engine.verification import compare_screenshots, make_diff_image
from .overlay import BorderOverlay
from ..platform.monitors import Monitor
from ..data.utils import base64_to_image, take_stable_screenshot, load_recording
from ..config.theme import COLORS
from .. import config as _cfg_module
from ..config import (
    WINDOW_TITLE,
    STOP_HOTKEY,
    TARGET_WINDOW_TITLE_CONTAINS,
)
from ..engine.target_window import TargetWindow
from . import layout as _layout, widgets as _widgets

try:
    import win32gui as _win32gui
except Exception:
    _win32gui = None


class RecorderGUI:
    """Main application window for recording and replaying UI interactions."""

    def __init__(self, output_dir: Path):
        self.output_dir = output_dir
        self.last_recording_path: Optional[Path] = None
        self._closing = False
        self._expected_photo: Optional[ImageTk.PhotoImage] = None
        self._current_photo: Optional[ImageTk.PhotoImage] = None
        self._browse_recording: Optional[Recording] = None
        self._browse_index: int = 0
        self._playback_snapshots: list[Optional[Image.Image]] = []
        self._playback_diff_texts: list[Optional[str]] = []
        # Pre-action live captures (from verification) keyed by event idx.
        # Same baseline as verification → CURRENT panel and labels stay
        # consistent between live playback, browse, and fail-state.
        self._playback_live_pres: list[Optional[Image.Image]] = []
        # When True, _refresh_current_view re-renders the verification-
        # fail view in place instead of falling through to browse.
        self._in_fail_state: bool = False
        # Cached fail-state context (so toggle re-renders correctly).
        self._fail_event: Optional[RecordedEvent] = None
        self._fail_expected: Optional[Image.Image] = None
        self._fail_live: Optional[Image.Image] = None
        self._fail_diff_text: Optional[str] = None

        # Target-window focus watcher state.
        self._watch_after_id: Optional[str] = None
        self._watch_focus_loss_streak: int = 0
        self._active_target_window: Optional[TargetWindow] = None

        self.root = tk.Tk()
        self.root.title(WINDOW_TITLE)
        self.root.configure(bg=COLORS["bg"])
        self.root.resizable(False, False)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        self.root.update_idletasks()
        hwnd = self._get_hwnd()

        self.recorder = EventRecorder(
            output_base_dir=self.output_dir,
            on_event=self._on_recording_event,
            ignore_window_hwnd=hwnd,
            ignore_keys={STOP_HOTKEY.name},
            target_window=(
                TargetWindow(TARGET_WINDOW_TITLE_CONTAINS)
                if TARGET_WINDOW_TITLE_CONTAINS else None
            ),
        )
        self.player = EventPlayer(
            on_step=self._on_playback_step,
            on_complete=self._on_playback_complete,
            on_verification_fail=self._on_verification_fail,
            on_step_verified=self._on_step_verified,
        )

        _layout.build_ui(self)
        self._update_button_states()
        self._setup_global_hotkey()
        _widgets.center_window(self.root)

        # Screen-edge overlays — visible during recording / playback so the
        # user has a clear cue that capture or injection is active. They are
        # click-through and excluded from screen captures.
        self._record_overlay = BorderOverlay(self.root, color="red")
        self._playback_overlay = BorderOverlay(self.root, color="#1e90ff")

    # ── Window helpers ────────────────────────────────────────────────

    def _get_hwnd(self) -> Optional[int]:
        """Get the native top-level window handle (for self-click filtering).

        Tk's ``wm_frame()`` returns the top-level HWND on Windows as a hex
        string. We avoid ``FindWindowW`` because, without explicitly setting
        ``restype``, ctypes truncates HWNDs to a signed 32-bit int on 64-bit
        Windows, producing a wrong handle and breaking the self-click filter.
        """
        try:
            frame = self.root.wm_frame()
            return int(frame, 16) if frame else None
        except Exception:
            return None

    def _setup_global_hotkey(self) -> None:
        """Listen for F6 to stop recording/playback while UI is minimized."""
        def _on_hotkey(key):
            try:
                if key == STOP_HOTKEY:
                    if self.recorder.is_running:
                        self.root.after(0, self._stop_recording)
                    elif self.player.is_running:
                        self.root.after(0, self._stop_playback_and_restore)
            except Exception:
                pass

        self._hotkey_listener = kb.Listener(on_press=_on_hotkey)
        self._hotkey_listener.daemon = True
        self._hotkey_listener.start()

    # ── Mode & button state management ────────────────────────────────

    def _set_mode(self, status: str, info: str = "",
                  step_text: Optional[str] = None) -> None:
        """Update the UI mode: status label, info bar, and button states."""
        self.status_var.set(status)
        self.info_var.set(info)
        if step_text is not None:
            self.step_var.set(step_text)
        self._update_button_states()

    def _update_button_states(self) -> None:
        recording = self.recorder.is_running
        playing = self.player.is_running
        idle = not recording and not playing

        self.start_btn.config(state="normal" if idle else "disabled")
        self.stop_btn.config(state="normal" if recording else "disabled")
        self.play_btn.config(state="normal" if idle else "disabled")
        replay_ok = (
            idle
            and self.last_recording_path is not None
            and self.last_recording_path.exists()
        )
        if hasattr(self, "replay_btn"):
            self.replay_btn.config(state="normal" if replay_ok else "disabled")
        self.stop_play_btn.config(state="normal" if playing else "disabled")
        self.browse_btn.config(state="normal" if idle else "disabled")
        if hasattr(self, "settings_btn"):
            self.settings_btn.config(state="normal" if idle else "disabled")
        if hasattr(self, "capture_combo"):
            self.capture_combo.config(state="readonly" if idle else "disabled")
        self._update_nav_buttons()

    def _selected_monitor(self) -> Optional[Monitor]:
        """The monitor implied by the current capture choice.

        Monitor mode → that monitor. Window mode (or unresolved) →
        primary monitor as a sensible fallback for overlay placement
        and playback cropping.
        """
        if not getattr(self, "_monitors", None):
            return None
        kind, value = self._resolve_capture_choice()
        if kind == "monitor" and value is not None:
            return value
        return self._monitors[0]

    def _monitor_for_recording(self, recording: Optional[Recording]) -> Optional[Monitor]:
        """Pick the live ``Monitor`` matching the one the recording was
        captured on. Returns None if the recording has no monitor metadata
        or if no live monitor matches its bounds."""
        if recording is None or not getattr(recording, "monitor", None):
            return None
        meta = recording.monitor
        for m in self._monitors:
            if (m.x == meta.get("x") and m.y == meta.get("y")
                    and m.width == meta.get("width")
                    and m.height == meta.get("height")):
                return m
        # Fall back to a name match if geometry shifted slightly.
        for m in self._monitors:
            if m.name == meta.get("name"):
                return m
        return None

    def _playback_region(self, recording: Optional[Recording]) -> Optional[tuple]:
        """Region to crop the playback "current" screenshot to so it lines
        up with the Expected panel.

        Uses the recording's monitor metadata when available, falling back
        to the currently-selected monitor. Returns None for legacy
        recordings without metadata when no monitor is selected.
        """
        if recording is not None and getattr(recording, "monitor", None):
            meta = recording.monitor
            return (int(meta["x"]), int(meta["y"]),
                    int(meta["width"]), int(meta["height"]))
        m = self._selected_monitor()
        if m is not None:
            return (m.x, m.y, m.width, m.height)
        return None

    def _update_nav_buttons(self) -> None:
        rec = self._browse_recording
        if rec:
            at_start = self._browse_index <= 0
            at_end = self._browse_index >= len(rec.events) - 1
            self.prev_btn.config(state="disabled" if at_start else "normal")
            self.next_btn.config(state="disabled" if at_end else "normal")
        else:
            self.prev_btn.config(state="disabled")
            self.next_btn.config(state="disabled")

    # ── Capture target helpers (unified Monitor + Window picker) ──────

    _MONITOR_PREFIX = "🖥 "
    _WINDOW_PREFIX = "🪟 "

    def _monitor_label(self, m: Monitor) -> str:
        tag = " (Primary)" if m.is_primary else ""
        return f"{self._MONITOR_PREFIX}Monitor {m.index + 1}: {m.width}×{m.height}{tag}"

    def _settings_target_label(self) -> Optional[str]:
        title = (_cfg_module.TARGET_WINDOW_TITLE_CONTAINS or "").strip()
        if not title:
            return None
        return f"{self._WINDOW_PREFIX}(from settings: {title!r})"

    def _enumerate_visible_windows(self) -> list[tuple[int, str]]:
        """Return [(hwnd, title)] for visible top-level windows with a
        non-empty title. Skips our own window."""
        if _win32gui is None:
            return []
        own_hwnd = self._get_hwnd()
        out: list[tuple[int, str]] = []

        def _collect(hwnd, _):
            try:
                if not _win32gui.IsWindowVisible(hwnd):
                    return True
                title = _win32gui.GetWindowText(hwnd)
                if not title:
                    return True
                if own_hwnd and int(hwnd) == int(own_hwnd):
                    return True
                out.append((int(hwnd), title))
            except Exception:
                pass
            return True

        try:
            _win32gui.EnumWindows(_collect, None)
        except Exception:
            return []
        out.sort(key=lambda h_t: h_t[1].lower())
        return out

    def _refresh_capture_choices(self, *, initial: bool = False) -> None:
        """Rebuild the unified Capture combobox values."""
        current = self.capture_var.get()
        choices: list[str] = [self._monitor_label(m) for m in self._monitors]
        settings_label = self._settings_target_label()
        if settings_label:
            choices.append(settings_label)
        for _hwnd, title in self._enumerate_visible_windows():
            label = f"{self._WINDOW_PREFIX}{title}"
            if label not in choices:
                choices.append(label)
        self.capture_combo["values"] = choices

        def _default_index() -> int:
            # Prefer the configured target window; otherwise primary monitor.
            if settings_label and settings_label in choices:
                return choices.index(settings_label)
            return 0

        if initial:
            self.capture_combo.current(_default_index())
            return
        if current and current in choices:
            self.capture_combo.set(current)
        elif current:
            # Previous selection vanished (window closed); fall back.
            self.capture_combo.current(_default_index())

    def _resolve_capture_choice(self) -> tuple[str, object]:
        """Translate the dropdown selection into a tagged value.

        Returns one of:
          ("monitor", Monitor)        — whole-monitor capture
          ("window",  TargetWindow)   — Model B window-relative capture
          ("monitor", primary)        — fallback when nothing matches
        """
        selection = (self.capture_var.get() or "").strip()
        primary = self._monitors[0] if self._monitors else None

        # Monitor entries.
        for m in self._monitors:
            if selection == self._monitor_label(m):
                return ("monitor", m)

        # Window entries.
        if selection.startswith(self._WINDOW_PREFIX):
            label_body = selection[len(self._WINDOW_PREFIX):]
            settings_label_body = None
            settings_full = self._settings_target_label()
            if settings_full:
                settings_label_body = settings_full[len(self._WINDOW_PREFIX):]
            if settings_label_body and label_body == settings_label_body:
                title = (_cfg_module.TARGET_WINDOW_TITLE_CONTAINS or "").strip()
            else:
                title = label_body
            if title:
                try:
                    return ("window", TargetWindow(title))
                except ValueError:
                    pass

        return ("monitor", primary)

    # ── Recording actions ─────────────────────────────────────────────

    def _start_recording(self) -> None:
        self._hide_fail_banner()
        name = self.name_var.get().strip() or None
        self._browse_recording = None
        self._playback_snapshots = []
        self._playback_diff_texts = []
        self._playback_live_pres = []
        self._clear_fail_state()

        kind, value = self._resolve_capture_choice()
        monitor: Optional[Monitor] = None
        target: Optional[TargetWindow] = None

        if kind == "window" and isinstance(value, TargetWindow):
            target = value
            launch_uri = (_cfg_module.TARGET_WINDOW_AUTO_LAUNCH_URI or "").strip()
            if launch_uri:
                try:
                    from ..platform import session as _gaze
                    _gaze.best_effort_launch(launch_uri)
                except Exception as exc:
                    print(f"[warn] auto-launch failed: {exc}")
            # Retry resolution for ~5s in case launch is still spinning up.
            import time as _time
            deadline = _time.monotonic() + 5.0
            while _time.monotonic() < deadline:
                if target.refresh():
                    break
                _time.sleep(0.25)
            if target.hwnd is None:
                messagebox.showerror(
                    "Target window not found",
                    f"Could not find a visible window matching "
                    f"{target.title_contains!r}.\n\n"
                    f"Open the app first or pick a different capture target.",
                )
                return
            try:
                target.focus()
            except Exception as exc:
                print(f"[warn] target focus failed: {exc}")
            # Overlay still needs a monitor — pick the one the window
            # currently sits on (best-effort: primary).
            monitor = self._monitors[0] if self._monitors else None
        else:
            monitor = value if isinstance(value, Monitor) else (
                self._monitors[0] if self._monitors else None
            )

        # Re-bind the recorder per run so monitor and Model B modes can
        # be toggled without restarting the app.
        self.recorder.target_window = target
        self.recorder.monitor = monitor if target is None else None
        self._active_target_window = target

        self.recorder.start(name=name)
        self._set_mode("● Recording", step_text="Steps: 0")
        self.event_info_var.set("")
        _widgets.draw_placeholder(self.expected_canvas, "Recording in progress...")
        _widgets.draw_placeholder(self.current_canvas, "Recording in progress...")
        self.root.iconify()
        self._record_overlay.show(monitor=monitor)

        if target is not None:
            self._watch_focus_loss_streak = 0
            self._schedule_target_watch()

    def _stop_recording(self, *, reason: Optional[str] = None) -> None:
        self._cancel_target_watch()
        try:
            json_path = self.recorder.stop()
        except Exception as exc:
            json_path = None
            self._record_overlay.hide()
            self.root.deiconify()
            self._set_mode("Idle")
            messagebox.showerror("Recording Failed",
                                 f"Recorder stop failed:\n{exc}")
            return
        self._record_overlay.hide()
        self.root.deiconify()
        self._active_target_window = None
        if reason:
            self._set_mode("Idle", info=f"Recording stopped: {reason}")
        else:
            self._set_mode("Idle")
        _widgets.draw_placeholder(self.expected_canvas, "No recording loaded")
        _widgets.draw_placeholder(self.current_canvas, "Not playing")

        if json_path:
            self.last_recording_path = json_path
            self.name_var.set(json_path.stem)
            suffix = f" ({reason})" if reason else ""
            self.info_var.set(f"Saved: {json_path.name}{suffix}")
            messagebox.showinfo(
                "Recording Saved",
                f"Recording saved to:\n{json_path}"
                + (f"\n\nStop reason: {reason}" if reason else ""),
            )

    # ── Target window watcher ─────────────────────────────────────────

    _WATCH_INTERVAL_MS = 400

    def _schedule_target_watch(self) -> None:
        if self._closing:
            return
        if not self.recorder.is_running:
            return
        self._watch_after_id = self.root.after(
            self._WATCH_INTERVAL_MS, self._watch_target_window
        )

    def _cancel_target_watch(self) -> None:
        if self._watch_after_id is not None:
            try:
                self.root.after_cancel(self._watch_after_id)
            except Exception:
                pass
            self._watch_after_id = None
        self._watch_focus_loss_streak = 0

    def _watch_target_window(self) -> None:
        """Tk after-loop tick: stop recording on minimize / focus loss /
        window close. Focus loss requires two consecutive ticks to absorb
        transient overlays raised by the Windows App."""
        self._watch_after_id = None
        target = self._active_target_window
        if target is None or not self.recorder.is_running:
            return

        try:
            if not target.still_valid():
                self._stop_recording(reason="target window closed")
                return

            if (_cfg_module.TARGET_WINDOW_STOP_ON_MINIMIZE
                    and target.is_minimized()):
                self._stop_recording(reason="target window minimized")
                return

            if _cfg_module.TARGET_WINDOW_STOP_ON_FOCUS_LOSS:
                if target.is_focused():
                    self._watch_focus_loss_streak = 0
                else:
                    self._watch_focus_loss_streak += 1
                    if self._watch_focus_loss_streak >= 2:
                        self._stop_recording(reason="target window lost focus")
                        return
        except Exception as exc:
            # Don't kill the watcher on a transient error.
            print(f"[warn] target watcher tick failed: {exc}")

        self._schedule_target_watch()

    def _on_recording_event(self, event: RecordedEvent) -> None:
        if self._closing:
            return
        self.root.after(0, lambda: self._update_recording_step(event))

    def _update_recording_step(self, event: RecordedEvent) -> None:
        self.step_var.set(f"Steps: {event.step}")
        self.event_info_var.set(event.type.replace("_", " "))
        self.desc_var.set(self._describe_event(event))

    # ── Playback actions ──────────────────────────────────────────────

    def _play_recording(self) -> None:
        self._hide_fail_banner()
        json_path = filedialog.askopenfilename(
            title="Select Recording",
            initialdir=str(self.output_dir),
            filetypes=[("JSON files", "*.json")],
        )
        if not json_path:
            return
        self._start_playback(Path(json_path))

    def _replay_recording(self) -> None:
        """Re-run the most recently loaded recording without prompting."""
        path = self.last_recording_path
        if path is None or not path.exists():
            messagebox.showinfo(
                "No Recording",
                "Load a recording with ▶ Play or 📋 Browse first.",
            )
            return
        self._hide_fail_banner()
        self._start_playback(path)

    def _start_playback(self, json_path: Path) -> None:
        """Shared playback startup: load recording, start player, show overlay."""
        self._browse_recording = load_recording(json_path)
        self._browse_index = 0
        self._playback_snapshots = []
        self._playback_diff_texts = []
        self._playback_live_pres = []
        self._clear_fail_state()
        self.last_recording_path = json_path

        # Ensure the target app window is visible and on-screen before
        # playback starts. Two paths trigger this:
        #   1) The recording is window-relative -- it carries the title
        #      it was recorded against; that title is the source of truth.
        #   2) The recording is in monitor mode but the user has
        #      configured a TARGET_WINDOW_TITLE_CONTAINS in Settings --
        #      we still want the app foregrounded and un-minimized
        #      because most recorded clicks were aimed at that app.
        rec = self._browse_recording
        title_to_ensure = None
        if rec.window_relative and rec.window_title_contains:
            title_to_ensure = rec.window_title_contains
        else:
            cfg_title = (_cfg_module.TARGET_WINDOW_TITLE_CONTAINS or "").strip()
            if cfg_title:
                title_to_ensure = cfg_title
        if title_to_ensure:
            if not self._ensure_target_window(title_to_ensure):
                return

        self.player.play(json_path)
        self._set_mode("▶ Playing", step_text="Step: 0 / ?")
        _widgets.draw_placeholder(self.current_canvas, "Starting playback...")
        if _cfg_module.MINIMIZE_DURING_PLAYBACK:
            self.root.iconify()
        # Show the playback overlay over the monitor that the recording was
        # captured on (when known); otherwise default to the currently
        # selected monitor.
        monitor = self._monitor_for_recording(self._browse_recording) \
            or self._selected_monitor()
        self._playback_overlay.show(monitor=monitor)

    def _ensure_target_window(self, title_contains: str) -> bool:
        """Resolve the playback target window, auto-launching if needed.

        Returns True when a matching window was found within the wait
        window. On failure, shows a GUI error so the user knows why
        playback didn't start (the playback worker only logs to stdout).

        If the window is found but minimized, restore it so the cached
        rect (and any later screenshots) reflect its real on-screen
        geometry. ``find_session_window`` happily returns minimized
        windows, but ``GetWindowRect`` then reports the off-screen
        ``(-32000, -32000, ...)`` parking rect, which would send every
        replayed click into the void.
        """
        try:
            target = TargetWindow(title_contains)
        except ValueError:
            return False

        def _ready() -> bool:
            if not target.refresh():
                return False
            if target.is_minimized():
                try:
                    target.focus()  # SW_RESTORE + foreground
                except Exception as exc:
                    print(f"[warn] target restore failed: {exc}")
                # Give the OS a beat to apply SW_RESTORE before re-reading the rect.
                import time as _t
                _t.sleep(0.2)
                target.refresh()
            return target.hwnd is not None

        if _ready():
            return True

        launch_uri = (_cfg_module.TARGET_WINDOW_AUTO_LAUNCH_URI or "").strip()
        if launch_uri:
            try:
                from ..platform import session as _gaze
                _gaze.best_effort_launch(launch_uri)
            except Exception as exc:
                print(f"[warn] auto-launch failed: {exc}")

        import time as _time
        deadline = _time.monotonic() + 5.0
        while _time.monotonic() < deadline:
            if _ready():
                return True
            _time.sleep(0.25)

        messagebox.showerror(
            "Target window not found",
            f"Could not find a visible window matching "
            f"{title_contains!r}.\n\n"
            f"Open the app first or set an auto-launch URI/command in "
            f"Settings, then try Play again.",
        )
        return False

    def _stop_playback(self) -> None:
        self.player.stop()
        self._playback_overlay.hide()

    def _stop_playback_and_restore(self) -> None:
        """Stop playback (e.g. via F6 hotkey) and enter browse mode."""
        self.player.stop()
        self._playback_overlay.hide()
        self.root.deiconify()
        self._set_mode(
            "Browsing",
            info="Playback stopped — use ◀ Prev / Next ▶ to review steps",
        )
        if self._browse_recording and self._browse_recording.events:
            self._show_browse_step()

    def _on_step_verified(self, event: RecordedEvent, idx: int, total: int,
                          recording: Recording, expected, live,
                          diff_text: Optional[str], passed: bool) -> None:
        """Cache + display the pre-action verification baseline.

        Fired by the player after every verification attempt (success or
        fail) AND for events without verification (with all-None args).
        Keeps the EXPECTED + CURRENT panels and the diff label aligned
        with what verification actually compared, so toggling overlays
        or scrubbing browse never silently changes the baseline.
        """
        if self._closing:
            return

        # Pad the per-step caches so [idx] indexing is safe regardless
        # of insertion order.
        while len(self._playback_live_pres) <= idx:
            self._playback_live_pres.append(None)
        while len(self._playback_diff_texts) <= idx:
            self._playback_diff_texts.append(None)
        while len(self._playback_snapshots) <= idx:
            self._playback_snapshots.append(None)
        self._playback_live_pres[idx] = (
            live.copy() if live is not None else None
        )
        self._playback_diff_texts[idx] = diff_text
        # Keep the snapshot list parallel; snapshot is the same image.
        self._playback_snapshots[idx] = (
            live.copy() if live is not None else None
        )

        def _update():
            self._render_step_info(event, total)
            if expected is not None:
                _widgets.show_image_on_canvas(
                    self, self.expected_canvas, expected, is_expected=True,
                )
            else:
                _widgets.draw_placeholder(
                    self.expected_canvas,
                    "No before-screenshot for this step",
                )
            self._update_current_label(diff_text)
            if live is not None:
                display_img = self._pick_current_display_image(
                    expected, live,
                )
                _widgets.show_image_on_canvas(
                    self, self.current_canvas, display_img,
                    is_expected=False,
                )
            else:
                _widgets.draw_placeholder(
                    self.current_canvas,
                    "No verification capture (verify off / warm-up)",
                )

        self.root.after(0, _update)

    def _on_playback_step(self, event: RecordedEvent, total: int,
                          recording: Recording) -> None:
        """Post-action step hook — progress / status only.

        Image rendering happens in _on_step_verified (pre-action). This
        runs after _execute_event, so it can't show a meaningful "did
        the action complete?" comparison without doubling capture cost
        and changing the baseline. Kept narrow on purpose.
        """
        if self._closing:
            return
        # Step-info text was already updated by _on_step_verified for
        # this idx, so no Tk work needed here. Hook retained for future
        # post-action diagnostics (e.g. duration timing).
        return

    def _on_playback_complete(self, status: str = "completed") -> None:
        if self._closing:
            return

        def _complete():
            self._playback_overlay.hide()
            self.root.deiconify()
            # Don't overwrite a verification-failure state set by
            # _on_verification_fail. Just hide overlay + restore window;
            # the failure handler already updated mode/info text. We
            # still refresh button states so e.g. the Settings button
            # (disabled while playback was running) re-enables now that
            # the playback thread has actually exited.
            if status == "verification_failed":
                self._update_button_states()
                return
            if status == "stopped":
                info = "Playback stopped — use ◀ Prev / Next ▶ to review steps"
            else:
                info = "Playback complete — use ◀ Prev / Next ▶ to review steps"
            self._set_mode("Browsing", info=info)
            if self._browse_recording and self._browse_recording.events:
                self._browse_index = len(self._browse_recording.events) - 1
                self._show_browse_step()

        self.root.after(0, _complete)

    def _on_verification_fail(self, event: RecordedEvent, diff_text: str,
                              expected_img, live_img) -> None:
        """Pre-action verification failed. Show recorded BEFORE vs live so
        the user can diagnose. All Tk updates are marshalled via root.after
        because this runs on the playback worker thread."""
        if self._closing:
            return

        # Cache fail context so toggling overlay re-renders in place
        # without falling through to browse mode.
        self._in_fail_state = True
        self._fail_event = event
        self._fail_expected = expected_img
        self._fail_live = live_img
        self._fail_diff_text = diff_text

        def _fail():
            self._playback_overlay.hide()
            self.root.deiconify()
            self._show_fail_banner(event.step, diff_text)
            self.step_var.set(f"Step: {event.step}")
            self.event_info_var.set("⚠ verification failed")
            self.desc_var.set(
                f"Pre-action screenshot diverged ({diff_text}, "
                f"method={_cfg_module.VERIFY_METHOD}). "
                f"Playback halted before firing this action."
            )
            self.status_var.set(f"⚠ FAILED at step {event.step}")
            self.info_var.set(
                f"Pre-action screenshot diverged: {diff_text} — "
                f"playback halted before firing this action."
            )
            self._update_button_states()
            self._render_fail_view()

        self.root.after(0, _fail)

    def _render_fail_view(self) -> None:
        """Re-render the recorded BEFORE / live capture for fail state.

        Used both by _on_verification_fail (initial render) and
        _refresh_current_view (toggle re-render). Updates the CURRENT
        label and image without touching banner / status / step info.
        """
        expected_img = self._fail_expected
        live_img = self._fail_live
        diff_text = self._fail_diff_text
        if expected_img is not None:
            _widgets.show_image_on_canvas(
                self, self.expected_canvas, expected_img, is_expected=True,
            )
        else:
            _widgets.draw_placeholder(self.expected_canvas, "No expected image")
        if live_img is not None:
            display_img = self._pick_current_display_image(
                expected_img, live_img,
            )
            _widgets.show_image_on_canvas(
                self, self.current_canvas, display_img, is_expected=False,
            )
        else:
            _widgets.draw_placeholder(self.current_canvas, "No live capture")
        self._update_current_label(diff_text)

    def _clear_fail_state(self) -> None:
        """Drop the cached fail context so toggling falls back to browse."""
        self._in_fail_state = False
        self._fail_event = None
        self._fail_expected = None
        self._fail_live = None
        self._fail_diff_text = None
        self._hide_fail_banner()

    def _show_fail_banner(self, step: int, diff_text: str) -> None:
        """Pop the big red TEST FAILED banner under the header."""
        self.fail_banner_title_var.set(f"❌ TEST FAILED — Step {step}")
        self.fail_banner_subtitle_var.set(
            f"Pre-action screenshot diverged: {diff_text} "
            f"(method={_cfg_module.VERIFY_METHOD}). "
            f"Playback halted before firing this action."
        )
        if not self.fail_banner.winfo_ismapped():
            self.fail_banner.pack(
                fill="x", pady=(0, 6),
                before=self.fail_banner_anchor,
            )

    def _hide_fail_banner(self) -> None:
        """Hide the FAIL banner if visible."""
        banner = getattr(self, "fail_banner", None)
        if banner is not None and banner.winfo_ismapped():
            banner.pack_forget()

    # ── Browse actions ────────────────────────────────────────────────

    def _browse_recording_file(self) -> None:
        """Load a recording file for step-by-step browsing."""
        json_path = filedialog.askopenfilename(
            title="Browse Recording",
            initialdir=str(self.output_dir),
            filetypes=[("JSON files", "*.json")],
        )
        if not json_path:
            return

        rec = load_recording(Path(json_path))
        if not rec.events:
            messagebox.showinfo("Empty Recording",
                                "This recording has no events.")
            return

        self._browse_recording = rec
        self._browse_index = 0
        self._playback_snapshots = []
        self._playback_diff_texts = []
        self._playback_live_pres = []
        self._clear_fail_state()
        self.last_recording_path = Path(json_path)
        self.name_var.set(rec.name)
        self._set_mode("Browsing")
        self._show_browse_step()

    def _show_browse_step(self) -> None:
        """Display the current browse step on the UI.

        Browse uses the BEFORE-baseline (recorded before-screenshot vs
        cached pre-action live capture) so the comparison shown matches
        what verification actually ran. Steps without verification (no
        before-shot, warm-up, verify off) display a "no comparison"
        placeholder rather than misleading numbers.
        """
        # Don't hide the fail banner here — _show_browse_step is also
        # called by _on_playback_complete after a halt; preserving the
        # banner is what the user expects. Banner is cleared on next
        # playback start / file open via _clear_fail_state.
        rec = self._browse_recording
        if not rec:
            return

        idx = self._browse_index
        event = rec.events[idx]
        total = len(rec.events)

        expected_img = self._decode_before(event, rec)
        self._render_step_info(event, total)
        self._show_expected(expected_img)

        live = (self._playback_live_pres[idx]
                if idx < len(self._playback_live_pres) else None)
        cached = (self._playback_diff_texts[idx]
                  if idx < len(self._playback_diff_texts) else None)
        if live is not None and cached is None and expected_img is not None:
            cached = self._compute_diff_text(expected_img, live)
        self._update_current_label(cached)
        if live is not None:
            display_img = self._pick_current_display_image(expected_img, live)
            _widgets.show_image_on_canvas(
                self, self.current_canvas, display_img,
                is_expected=False,
            )
        else:
            _widgets.draw_placeholder(
                self.current_canvas,
                "No verification capture for this step",
            )

        self._update_nav_buttons()

    def _prev_step(self) -> None:
        if self._browse_recording and self._browse_index > 0:
            self._browse_index -= 1
            self._clear_fail_state()
            self._show_browse_step()

    def _next_step(self) -> None:
        if self._browse_recording:
            if self._browse_index < len(self._browse_recording.events) - 1:
                self._browse_index += 1
                self._clear_fail_state()
                self._show_browse_step()

    # ── Shared rendering helpers ──────────────────────────────────────

    def _render_step_info(self, event: RecordedEvent, total: int) -> None:
        """Update the info bar with step counter and action description."""
        self.step_var.set(f"Step: {event.step} / {total}")
        self.event_info_var.set(event.type.replace("_", " "))
        self.desc_var.set(self._describe_event(event))

    def _decode_expected(self, event: RecordedEvent,
                         recording: Recording) -> Optional[Image.Image]:
        """Decode the AFTER screenshot for an event from the recording.

        Kept for callers that want the recorded post-action state. Most
        playback / browse code now uses :meth:`_decode_before` instead so
        the displayed comparison matches verification's baseline.
        """
        hash_key = event.screenshot
        if hash_key and hash_key in recording.screenshots:
            try:
                return base64_to_image(recording.screenshots[hash_key])
            except Exception:
                return None
        return None

    def _decode_before(self, event: RecordedEvent,
                       recording: Recording) -> Optional[Image.Image]:
        """Decode the recorded BEFORE screenshot for an event."""
        hash_key = event.before_screenshot
        if hash_key and hash_key in recording.screenshots:
            try:
                return base64_to_image(recording.screenshots[hash_key])
            except Exception:
                return None
        return None

    def _show_expected(self, image: Optional[Image.Image]) -> None:
        """Show expected screenshot or a placeholder on the expected canvas."""
        if image:
            _widgets.show_image_on_canvas(self, self.expected_canvas, image,
                                       is_expected=True)
        else:
            _widgets.draw_placeholder(self.expected_canvas, "No screenshot")

    def _compute_diff_text(self, expected: Optional[Image.Image],
                           live: Optional[Image.Image]) -> Optional[str]:
        """Return a human-readable diff measure between expected and live.

        Uses the configured verification method's metric so the value
        matches what verification would report. Returns None if either
        image is missing or the comparison errors out.
        """
        if expected is None or live is None:
            return None
        try:
            _passed, _value, text = compare_screenshots(
                live, expected,
                method=_cfg_module.VERIFY_METHOD,
                tolerance_pct=_cfg_module.VERIFY_TOLERANCE_PCT,
                pixel_threshold=_cfg_module.VERIFY_PIXEL_THRESHOLD,
                phash_max_distance=_cfg_module.VERIFY_PHASH_MAX_DISTANCE,
            )
            return text
        except Exception as exc:
            print(f"[ui] compare_screenshots failed: {exc!r}")
            return None

    def _update_current_label(self, diff_text: Optional[str]) -> None:
        """Update the CURRENT panel header with the per-step diff value."""
        if diff_text:
            self.current_label_var.set(f"CURRENT — diff: {diff_text}")
        else:
            self.current_label_var.set("CURRENT")

    def _pick_current_display_image(self, expected: Optional[Image.Image],
                                    live: Image.Image) -> Image.Image:
        """Choose between raw live and red-overlay diff based on toggle."""
        if not bool(self.show_diff_var.get()) or expected is None:
            return live
        try:
            return make_diff_image(expected, live)
        except Exception as exc:
            print(f"[ui] make_diff_image failed: {exc!r}; "
                  f"falling back to raw capture")
            return live

    def _refresh_current_view(self) -> None:
        """Re-render the CURRENT panel after the diff-overlay toggle changes.

        Three cases, in priority order:
        1. Verification fail is on screen → re-render fail view in place
           so the BEFORE-baseline label / images stay correct.
        2. Active playback → can't re-render past steps mid-flight.
        3. Browse mode → re-render the current browse step.
        """
        if self._in_fail_state:
            self._render_fail_view()
            return
        if self.player.is_running:
            return
        if self._browse_recording and self._browse_recording.events:
            self._show_browse_step()

    @staticmethod
    def _describe_event(event: RecordedEvent) -> str:
        """Generate a human-readable description of the event."""
        if event.type == "mouse_click":
            btn = (event.button or "left").capitalize()
            base = f"{btn} click at ({event.x}, {event.y})"
            if event.modifiers:
                prefix = "+".join(m.capitalize() for m in event.modifiers)
                return f"{prefix}+{base}"
            return base
        if event.type == "type_text":
            text = event.text or ""
            preview = text if len(text) <= 40 else text[:37] + "..."
            return f"Type '{preview}'"
        if event.type == "hotkey":
            mods = "+".join(m.capitalize() for m in (event.modifiers or []))
            key = event.key or "?"
            return f"Hotkey [{mods}+{key}]" if mods else f"Press key [{key}]"
        if event.type == "key_press":
            key = event.key or "?"
            return f"Type '{key}'" if len(key) == 1 else f"Press key [{key}]"
        return event.type.replace("_", " ")

    # ── Misc actions ──────────────────────────────────────────────────

    def _open_recordings_folder(self) -> None:
        folder = str(self.output_dir)
        os.makedirs(folder, exist_ok=True)
        os.startfile(folder)

    def _open_settings(self) -> None:
        from .settings_dialog import SettingsDialog
        SettingsDialog(self.root)

    def _on_close(self) -> None:
        self._closing = True
        self._cancel_target_watch()
        if hasattr(self, '_hotkey_listener'):
            self._hotkey_listener.stop()
        if self.recorder.is_running:
            self.recorder.stop()
        if self.player.is_running:
            self.player.stop()
        try:
            self._record_overlay.destroy()
            self._playback_overlay.destroy()
        except Exception:
            pass
        self.root.destroy()

    def run(self) -> None:
        """Start the tkinter main loop."""
        self.root.mainloop()
