"""Tkinter GUI control panel for the recorder/player.

Warm light theme inspired by Notion's design system.
Design reference: https://github.com/VoltAgent/awesome-design-md
"""

import os
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from pathlib import Path
from typing import Optional

from PIL import Image, ImageTk
from pynput import keyboard as kb

from .models import RecordedEvent, Recording
from .recorder import EventRecorder
from .player import EventPlayer
from .overlay import BorderOverlay
from .monitors import list_monitors, Monitor
from .utils import base64_to_image, take_screenshot, load_recording
from .theme import COLORS, FONT_FAMILY, THUMBNAIL_SIZE
from .config import (
    WINDOW_TITLE,
    STOP_HOTKEY,
    INFO_WRAPLENGTH,
    TARGET_WINDOW_TITLE_CONTAINS,
)
from .target_window import TargetWindow

# Shared button style applied to all action buttons
_BTN_STYLE = {
    "font": (FONT_FAMILY, 9),
    "relief": "flat",
    "borderwidth": 0,
    "padx": 10,
    "pady": 4,
    "cursor": "hand2",
}


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
        )

        self._build_ui()
        self._update_button_states()
        self._setup_global_hotkey()
        self._center_window()

        # Screen-edge overlays — visible during recording / playback so the
        # user has a clear cue that capture or injection is active. They are
        # click-through and excluded from screen captures.
        self._record_overlay = BorderOverlay(self.root, color="red")
        self._playback_overlay = BorderOverlay(self.root, color="#1e90ff")

    # ── Window helpers ────────────────────────────────────────────────

    def _center_window(self) -> None:
        self.root.update_idletasks()
        w = self.root.winfo_width()
        h = self.root.winfo_height()
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        x = (sw - w) // 2
        y = max(10, (sh - h) // 6)
        self.root.geometry(f"+{x}+{y}")

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

    # ── UI construction ───────────────────────────────────────────────

    def _build_ui(self) -> None:
        main = tk.Frame(self.root, bg=COLORS["bg"], padx=12, pady=8)
        main.pack(fill="both", expand=True)

        self._build_header(main)
        self._build_toolbar(main)
        self._build_info_bar(main)
        self._build_screenshot_panels(main)
        self._build_navigation(main)
        self._build_footer(main)

    def _build_header(self, parent: tk.Frame) -> None:
        """Row 1: App title + status indicator."""
        row = tk.Frame(parent, bg=COLORS["bg"])
        row.pack(fill="x", pady=(0, 6))
        tk.Label(row, text="⊙ RemoteGaze", font=(FONT_FAMILY, 14, "bold"),
                 bg=COLORS["bg"], fg=COLORS["text_primary"]).pack(side="left")
        self.status_var = tk.StringVar(value="Idle")
        tk.Label(row, textvariable=self.status_var, font=(FONT_FAMILY, 10),
                 bg=COLORS["bg"], fg=COLORS["accent"]).pack(side="right")

    def _build_toolbar(self, parent: tk.Frame) -> None:
        """Row 2: Test case name entry + action buttons."""
        row = tk.Frame(parent, bg=COLORS["bg"])
        row.pack(fill="x", pady=(0, 6))

        tk.Label(row, text="Test Case:", font=(FONT_FAMILY, 9),
                 bg=COLORS["bg"], fg=COLORS["text_secondary"]).pack(side="left")
        self.name_var = tk.StringVar(value="")
        self.name_entry = tk.Entry(
            row, textvariable=self.name_var, font=(FONT_FAMILY, 9),
            bg=COLORS["surface"], fg=COLORS["text_primary"], relief="flat",
            width=20, highlightbackground=COLORS["border"], highlightthickness=1,
            insertbackground=COLORS["text_primary"],
        )
        self.name_entry.pack(side="left", padx=(4, 8))

        self.start_btn = tk.Button(
            row, text="🔴 Record", bg=COLORS["green"], fg="#ffffff",
            command=self._start_recording,
            activebackground="#15932f", activeforeground="white", **_BTN_STYLE,
        )
        self.start_btn.pack(side="left", padx=(0, 2))

        self.stop_btn = tk.Button(
            row, text="⏹ Stop Rec", bg=COLORS["red"], fg="#ffffff",
            command=self._stop_recording,
            activebackground="#d94444", activeforeground="white", **_BTN_STYLE,
        )
        self.stop_btn.pack(side="left", padx=(0, 2))

        self.play_btn = tk.Button(
            row, text="▶ Play", bg=COLORS["accent"], fg="#ffffff",
            command=self._play_recording,
            activebackground=COLORS["accent_hover"], activeforeground="white",
            **_BTN_STYLE,
        )
        self.play_btn.pack(side="left", padx=(0, 2))

        self.stop_play_btn = tk.Button(
            row, text="⏹ Stop Play", bg=COLORS["surface_hover"],
            fg=COLORS["text_secondary"], command=self._stop_playback,
            activebackground=COLORS["border"],
            activeforeground=COLORS["text_primary"], **_BTN_STYLE,
        )
        self.stop_play_btn.pack(side="left", padx=(0, 2))

        self.folder_btn = tk.Button(
            row, text="📂", bg=COLORS["badge_bg"], fg=COLORS["accent"],
            command=self._open_recordings_folder,
            activebackground=COLORS["surface_hover"],
            activeforeground=COLORS["accent_hover"], **_BTN_STYLE,
        )
        self.folder_btn.pack(side="left")

        self.settings_btn = tk.Button(
            row, text="⚙", bg=COLORS["badge_bg"], fg=COLORS["accent"],
            command=self._open_settings,
            activebackground=COLORS["surface_hover"],
            activeforeground=COLORS["accent_hover"], **_BTN_STYLE,
        )
        self.settings_btn.pack(side="left", padx=(2, 0))

        # Monitor picker — only meaningful with multiple displays, but the
        # combobox is always shown so the user can confirm what's recorded.
        self._monitors: list[Monitor] = list_monitors()
        tk.Label(row, text="Monitor:", font=(FONT_FAMILY, 9),
                 bg=COLORS["bg"], fg=COLORS["text_secondary"]).pack(
            side="left", padx=(12, 4))
        self.monitor_var = tk.StringVar()
        self.monitor_combo = ttk.Combobox(
            row, textvariable=self.monitor_var, state="readonly",
            width=24, font=(FONT_FAMILY, 9),
            values=[m.label for m in self._monitors],
        )
        # Default to primary (which list_monitors guarantees is index 0).
        if self._monitors:
            self.monitor_combo.current(0)
        self.monitor_combo.pack(side="left")

    def _build_info_bar(self, parent: tk.Frame) -> None:
        """Row 3: Step counter + event type + action description."""
        row = tk.Frame(parent, bg=COLORS["panel"],
                       highlightbackground=COLORS["border"],
                       highlightthickness=1, padx=10, pady=4)
        row.pack(fill="x", pady=(0, 6))

        self.step_var = tk.StringVar(value="Steps: 0")
        tk.Label(row, textvariable=self.step_var, font=(FONT_FAMILY, 9),
                 bg=COLORS["panel"], fg=COLORS["text_secondary"]).pack(side="left")

        self.event_info_var = tk.StringVar(value="")
        tk.Label(row, textvariable=self.event_info_var, font=(FONT_FAMILY, 9),
                 bg=COLORS["panel"], fg=COLORS["text_muted"]).pack(side="left", padx=(12, 0))

        self.desc_var = tk.StringVar(value="No action")
        tk.Label(row, textvariable=self.desc_var, font=(FONT_FAMILY, 9, "bold"),
                 bg=COLORS["panel"], fg=COLORS["text_primary"]).pack(side="right")

    def _build_screenshot_panels(self, parent: tk.Frame) -> None:
        """Row 4: Expected and Current screenshot canvases side by side."""
        frame = tk.Frame(parent, bg=COLORS["bg"])
        frame.pack(fill="x", pady=(0, 6))

        for label_text, attr_name, placeholder in [
            ("EXPECTED", "expected_canvas", "No recording loaded"),
            ("CURRENT", "current_canvas", "Not playing"),
        ]:
            col = tk.Frame(frame, bg=COLORS["bg"])
            col.pack(side="left", padx=2, expand=True, fill="both")
            tk.Label(col, text=label_text, font=(FONT_FAMILY, 8, "bold"),
                     bg=COLORS["bg"], fg=COLORS["text_muted"]).pack(anchor="w")
            canvas = tk.Canvas(
                col, width=THUMBNAIL_SIZE[0], height=THUMBNAIL_SIZE[1],
                bg=COLORS["panel"], highlightbackground=COLORS["border"],
                highlightthickness=1,
            )
            canvas.pack(pady=(2, 0))
            setattr(self, attr_name, canvas)
            self._draw_placeholder(canvas, placeholder)

    def _build_navigation(self, parent: tk.Frame) -> None:
        """Row 5: Browse recording file + prev/next step buttons."""
        row = tk.Frame(parent, bg=COLORS["bg"])
        row.pack(fill="x", pady=(0, 4))

        self.prev_btn = tk.Button(
            row, text="◀ Prev", bg=COLORS["surface_hover"],
            fg=COLORS["text_secondary"], command=self._prev_step,
            activebackground=COLORS["border"],
            activeforeground=COLORS["text_primary"], **_BTN_STYLE,
        )
        self.prev_btn.pack(side="left", padx=(0, 2))

        self.browse_btn = tk.Button(
            row, text="📋 Browse Recording", bg=COLORS["badge_bg"],
            fg=COLORS["accent"], command=self._browse_recording_file,
            activebackground=COLORS["surface_hover"],
            activeforeground=COLORS["accent_hover"], **_BTN_STYLE,
        )
        self.browse_btn.pack(side="left", padx=(0, 2))

        self.next_btn = tk.Button(
            row, text="Next ▶", bg=COLORS["surface_hover"],
            fg=COLORS["text_secondary"], command=self._next_step,
            activebackground=COLORS["border"],
            activeforeground=COLORS["text_primary"], **_BTN_STYLE,
        )
        self.next_btn.pack(side="left")

    def _build_footer(self, parent: tk.Frame) -> None:
        """Row 6: Info/help text."""
        self.info_var = tk.StringVar(value="Press F6 to stop recording or playback")
        tk.Label(parent, textvariable=self.info_var, font=(FONT_FAMILY, 8),
                 bg=COLORS["bg"], fg=COLORS["text_muted"],
                 wraplength=INFO_WRAPLENGTH).pack(fill="x", pady=(4, 0))

    # ── Canvas helpers ────────────────────────────────────────────────

    def _draw_placeholder(self, canvas: tk.Canvas, text: str) -> None:
        canvas.delete("all")
        canvas.create_text(
            THUMBNAIL_SIZE[0] // 2, THUMBNAIL_SIZE[1] // 2,
            text=text, fill=COLORS["text_muted"], font=(FONT_FAMILY, 11),
        )

    def _show_image_on_canvas(self, canvas: tk.Canvas, image: Image.Image,
                               is_expected: bool = True) -> None:
        """Resize image to thumbnail and display on canvas."""
        thumb = image.copy()
        thumb.thumbnail(THUMBNAIL_SIZE, Image.Resampling.LANCZOS)
        photo = ImageTk.PhotoImage(thumb)
        if is_expected:
            self._expected_photo = photo
        else:
            self._current_photo = photo
        canvas.delete("all")
        canvas.create_image(
            THUMBNAIL_SIZE[0] // 2, THUMBNAIL_SIZE[1] // 2,
            image=photo, anchor="center",
        )

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
        self.stop_play_btn.config(state="normal" if playing else "disabled")
        self.browse_btn.config(state="normal" if idle else "disabled")
        if hasattr(self, "settings_btn"):
            self.settings_btn.config(state="normal" if idle else "disabled")
        if hasattr(self, "monitor_combo"):
            self.monitor_combo.config(state="readonly" if idle else "disabled")
        self._update_nav_buttons()

    def _selected_monitor(self) -> Optional[Monitor]:
        if not getattr(self, "_monitors", None):
            return None
        idx = self.monitor_combo.current()
        if 0 <= idx < len(self._monitors):
            return self._monitors[idx]
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

    # ── Recording actions ─────────────────────────────────────────────

    def _start_recording(self) -> None:
        name = self.name_var.get().strip() or None
        self._browse_recording = None
        self._playback_snapshots = []
        monitor = self._selected_monitor()
        self.recorder.monitor = monitor
        self.recorder.start(name=name)
        self._set_mode("● Recording", step_text="Steps: 0")
        self.event_info_var.set("")
        self._draw_placeholder(self.expected_canvas, "Recording in progress...")
        self._draw_placeholder(self.current_canvas, "Recording in progress...")
        self.root.iconify()
        self._record_overlay.show(monitor=monitor)

    def _stop_recording(self) -> None:
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
        self._set_mode("Idle")
        self._draw_placeholder(self.expected_canvas, "No recording loaded")
        self._draw_placeholder(self.current_canvas, "Not playing")

        if json_path:
            self.last_recording_path = json_path
            self.name_var.set(json_path.stem)
            self.info_var.set(f"Saved: {json_path.name}")
            messagebox.showinfo("Recording Saved",
                                f"Recording saved to:\n{json_path}")

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
        json_path = filedialog.askopenfilename(
            title="Select Recording",
            initialdir=str(self.output_dir),
            filetypes=[("JSON files", "*.json")],
        )
        if not json_path:
            return

        self._browse_recording = load_recording(Path(json_path))
        self._browse_index = 0
        self._playback_snapshots = []
        self.last_recording_path = Path(json_path)

        self.player.play(Path(json_path))
        self._set_mode("▶ Playing", step_text="Step: 0 / ?")
        self._draw_placeholder(self.current_canvas, "Starting playback...")
        self.root.iconify()
        # Show the playback overlay over the monitor that the recording was
        # captured on (when known); otherwise default to the currently
        # selected monitor.
        monitor = self._monitor_for_recording(self._browse_recording) \
            or self._selected_monitor()
        self._playback_overlay.show(monitor=monitor)

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

    def _on_playback_step(self, event: RecordedEvent, total: int,
                          recording: Recording) -> None:
        if self._closing:
            return

        expected_img = self._decode_expected(event, recording)

        current_img = None
        try:
            current_img = take_screenshot(region=self._playback_region(recording))
        except Exception:
            pass

        self._playback_snapshots.append(
            current_img.copy() if current_img else None
        )

        def _update():
            self._render_step_info(event, total)
            self._show_expected(expected_img)
            if current_img:
                self._show_image_on_canvas(self.current_canvas, current_img,
                                           is_expected=False)
            else:
                self._draw_placeholder(self.current_canvas, "Capture failed")

        self.root.after(0, _update)

    def _on_playback_complete(self) -> None:
        if self._closing:
            return

        def _complete():
            self._playback_overlay.hide()
            self.root.deiconify()
            self._set_mode(
                "Browsing",
                info="Playback complete — use ◀ Prev / Next ▶ to review steps",
            )
            if self._browse_recording and self._browse_recording.events:
                self._browse_index = len(self._browse_recording.events) - 1
                self._show_browse_step()

        self.root.after(0, _complete)

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
        self.last_recording_path = Path(json_path)
        self.name_var.set(rec.name)
        self._set_mode("Browsing")
        self._show_browse_step()

    def _show_browse_step(self) -> None:
        """Display the current browse step on the UI."""
        rec = self._browse_recording
        if not rec:
            return

        idx = self._browse_index
        event = rec.events[idx]
        total = len(rec.events)

        self._render_step_info(event, total)
        self._show_expected(self._decode_expected(event, rec))

        if idx < len(self._playback_snapshots) and self._playback_snapshots[idx]:
            self._show_image_on_canvas(
                self.current_canvas, self._playback_snapshots[idx],
                is_expected=False,
            )
        else:
            self._draw_placeholder(self.current_canvas, "No playback snapshot")

        self._update_nav_buttons()

    def _prev_step(self) -> None:
        if self._browse_recording and self._browse_index > 0:
            self._browse_index -= 1
            self._show_browse_step()

    def _next_step(self) -> None:
        if self._browse_recording:
            if self._browse_index < len(self._browse_recording.events) - 1:
                self._browse_index += 1
                self._show_browse_step()

    # ── Shared rendering helpers ──────────────────────────────────────

    def _render_step_info(self, event: RecordedEvent, total: int) -> None:
        """Update the info bar with step counter and action description."""
        self.step_var.set(f"Step: {event.step} / {total}")
        self.event_info_var.set(event.type.replace("_", " "))
        self.desc_var.set(self._describe_event(event))

    def _decode_expected(self, event: RecordedEvent,
                         recording: Recording) -> Optional[Image.Image]:
        """Decode the expected screenshot for an event from the recording."""
        # Single screenshot per event in the new schema.
        hash_key = event.screenshot
        if hash_key and hash_key in recording.screenshots:
            try:
                return base64_to_image(recording.screenshots[hash_key])
            except Exception:
                return None
        return None

    def _show_expected(self, image: Optional[Image.Image]) -> None:
        """Show expected screenshot or a placeholder on the expected canvas."""
        if image:
            self._show_image_on_canvas(self.expected_canvas, image,
                                       is_expected=True)
        else:
            self._draw_placeholder(self.expected_canvas, "No screenshot")

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
