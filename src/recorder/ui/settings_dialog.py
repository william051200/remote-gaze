"""Modal dialog for editing runtime configuration.

Timing-related settings apply live (consumers read them from the
``recorder.config`` module at use-time). The recordings folder and stop
hotkey require a restart because they're bound during app/recorder
construction.
"""

from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Callable, Optional

from .. import config

_HOTKEYS = [f"f{i}" for i in range(1, 13)]

# Display labels for the verification method dropdown. Maps the visible
# string ↔ the underlying config token.
_VERIFY_METHOD_LABELS = {
    "Disabled": "disabled",
    "Pixel diff": "pixel",
    "Perceptual hash (pHash)": "phash",
}
_VERIFY_METHOD_REVERSE = {v: k for k, v in _VERIFY_METHOD_LABELS.items()}

_VERIFY_ON_MISMATCH_LABELS = {
    "Halt playback": "halt",
    "Continue (warn only)": "continue",
}
_VERIFY_ON_MISMATCH_REVERSE = {v: k for k, v in _VERIFY_ON_MISMATCH_LABELS.items()}


def _initial_method_label() -> str:
    """Map current config state to a method dropdown label."""
    if not config.VERIFY_BEFORE_ACTION:
        return "Disabled"
    return _VERIFY_METHOD_REVERSE.get(config.VERIFY_METHOD, "Pixel diff")


_DEFAULTS = {
    "recordings_dir_name": "recordings",
    "stop_hotkey": "f6",
    "post_inject_settle_seconds": 0.1,
    "text_buffer_idle_flush_seconds": 1.5,
    "pyautogui_pause": 0.05,
    "target_title_contains": "",
    "target_auto_launch_uri": "",
    "target_fullscreen_only": True,
    "target_stop_on_focus_loss": True,
    "target_stop_on_minimize": True,
    "verify_method_label": "Pixel diff",
    "verify_on_mismatch_label": "Halt playback",
    "verify_tolerance_pct": 25.0,
    "verify_pixel_threshold": 16,
    "verify_phash_max_distance": 125,
    "capture_before_screenshots": True,
    "minimize_during_playback": True,
}


class SettingsDialog(tk.Toplevel):
    """Modal settings editor. Returns control after Save or Cancel."""

    def __init__(self, parent: tk.Misc, on_saved: Optional[Callable[[], None]] = None):
        super().__init__(parent)
        self.title("Settings")
        self.transient(parent)
        self.resizable(False, False)
        self._on_saved = on_saved
        self._restart_dirty = False

        self._folder_var = tk.StringVar(value=config.RECORDINGS_DIR_NAME)
        self._hotkey_var = tk.StringVar(value=config.STOP_HOTKEY.name)
        self._settle_var = tk.StringVar(value=str(config.POST_INJECT_SETTLE_SECONDS))
        self._idle_var = tk.StringVar(value=str(config.TEXT_BUFFER_IDLE_FLUSH_SECONDS))
        self._pause_var = tk.StringVar(value=str(config.PYAUTOGUI_PAUSE))
        self._target_title_var = tk.StringVar(value=config.TARGET_WINDOW_TITLE_CONTAINS)
        self._target_launch_var = tk.StringVar(value=config.TARGET_WINDOW_AUTO_LAUNCH_URI)
        self._target_fullscreen_var = tk.BooleanVar(value=config.TARGET_WINDOW_FULLSCREEN_ONLY)
        self._target_stop_focus_var = tk.BooleanVar(value=config.TARGET_WINDOW_STOP_ON_FOCUS_LOSS)
        self._target_stop_min_var = tk.BooleanVar(value=config.TARGET_WINDOW_STOP_ON_MINIMIZE)

        # Verification settings
        self._verify_method_var = tk.StringVar(value=_initial_method_label())
        self._verify_on_mismatch_var = tk.StringVar(
            value=_VERIFY_ON_MISMATCH_REVERSE.get(config.VERIFY_ON_MISMATCH, "Halt playback")
        )
        self._verify_tol_var = tk.StringVar(value=str(config.VERIFY_TOLERANCE_PCT))
        self._verify_thresh_var = tk.StringVar(value=str(config.VERIFY_PIXEL_THRESHOLD))
        self._verify_phash_dist_var = tk.StringVar(value=str(config.VERIFY_PHASH_MAX_DISTANCE))
        self._capture_before_var = tk.BooleanVar(value=config.CAPTURE_BEFORE_SCREENSHOTS)
        self._minimize_var = tk.BooleanVar(value=config.MINIMIZE_DURING_PLAYBACK)

        self._build_ui()

        self.protocol("WM_DELETE_WINDOW", self._cancel)
        self.bind("<Escape>", lambda _e: self._cancel())
        self.bind("<Return>", lambda _e: self._save())

        self.update_idletasks()
        self._center_on_parent(parent)
        self.grab_set()
        self.focus_set()

    # ── UI ────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        pad = {"padx": 10, "pady": 4}
        frm = ttk.Frame(self, padding=12)
        frm.grid(row=0, column=0, sticky="nsew")

        ttk.Label(frm, text="Recordings folder:").grid(row=0, column=0, sticky="w", **pad)
        folder_frame = ttk.Frame(frm)
        folder_frame.grid(row=0, column=1, sticky="ew", **pad)
        ttk.Entry(folder_frame, textvariable=self._folder_var, width=38).pack(
            side="left", fill="x", expand=True
        )
        ttk.Button(folder_frame, text="Browse…", command=self._browse_folder).pack(
            side="left", padx=(6, 0)
        )
        ttk.Label(frm, text="(Restart required)", foreground="#888").grid(
            row=1, column=1, sticky="w", padx=10
        )

        ttk.Label(frm, text="Stop hotkey:").grid(row=2, column=0, sticky="w", **pad)
        ttk.Combobox(
            frm,
            textvariable=self._hotkey_var,
            values=_HOTKEYS,
            state="readonly",
            width=8,
        ).grid(row=2, column=1, sticky="w", **pad)
        ttk.Label(frm, text="(Restart required)", foreground="#888").grid(
            row=3, column=1, sticky="w", padx=10
        )

        ttk.Separator(frm, orient="horizontal").grid(
            row=4, column=0, columnspan=2, sticky="ew", pady=8
        )

        ttk.Label(frm, text="Settle delay (s):").grid(row=5, column=0, sticky="w", **pad)
        ttk.Entry(frm, textvariable=self._settle_var, width=10).grid(
            row=5, column=1, sticky="w", **pad
        )

        ttk.Label(frm, text="Text buffer idle flush (s):").grid(row=6, column=0, sticky="w", **pad)
        ttk.Entry(frm, textvariable=self._idle_var, width=10).grid(
            row=6, column=1, sticky="w", **pad
        )

        ttk.Label(frm, text="PyAutoGUI pause (s):").grid(row=7, column=0, sticky="w", **pad)
        ttk.Entry(frm, textvariable=self._pause_var, width=10).grid(
            row=7, column=1, sticky="w", **pad
        )

        ttk.Separator(frm, orient="horizontal").grid(
            row=8, column=0, columnspan=2, sticky="ew", pady=8
        )
        ttk.Label(frm, text="Target window (Model B)",
                  font=("TkDefaultFont", 9, "bold")).grid(
            row=9, column=0, columnspan=2, sticky="w", padx=10, pady=(0, 4)
        )

        ttk.Label(frm, text="Title contains:").grid(row=10, column=0, sticky="w", **pad)
        ttk.Entry(frm, textvariable=self._target_title_var, width=42).grid(
            row=10, column=1, sticky="ew", **pad
        )

        ttk.Label(frm, text="Auto-launch URI/cmd:").grid(row=11, column=0, sticky="w", **pad)
        ttk.Entry(frm, textvariable=self._target_launch_var, width=42).grid(
            row=11, column=1, sticky="ew", **pad
        )
        ttk.Label(frm, text="Optional. Examples: ms-avd:connect?... or msrdcw.exe",
                  foreground="#888").grid(row=12, column=1, sticky="w", padx=10)

        ttk.Checkbutton(
            frm, text="Fullscreen Windows App expected (warn on Win-key otherwise)",
            variable=self._target_fullscreen_var,
        ).grid(row=13, column=0, columnspan=2, sticky="w", padx=10, pady=2)

        ttk.Checkbutton(
            frm, text="Stop recording when target window loses focus",
            variable=self._target_stop_focus_var,
        ).grid(row=14, column=0, columnspan=2, sticky="w", padx=10, pady=2)

        ttk.Checkbutton(
            frm, text="Stop recording when target window is minimized",
            variable=self._target_stop_min_var,
        ).grid(row=15, column=0, columnspan=2, sticky="w", padx=10, pady=2)

        # ── Verification ──────────────────────────────────────────────
        ttk.Separator(frm, orient="horizontal").grid(
            row=16, column=0, columnspan=2, sticky="ew", pady=8
        )
        ttk.Label(frm, text="Pre-action verification",
                  font=("TkDefaultFont", 9, "bold")).grid(
            row=17, column=0, columnspan=2, sticky="w", padx=10, pady=(0, 4)
        )

        ttk.Label(frm, text="Method:").grid(row=18, column=0, sticky="w", **pad)
        method_combo = ttk.Combobox(
            frm,
            textvariable=self._verify_method_var,
            values=list(_VERIFY_METHOD_LABELS.keys()),
            state="readonly",
            width=24,
        )
        method_combo.grid(row=18, column=1, sticky="w", **pad)
        method_combo.bind("<<ComboboxSelected>>",
                          lambda _e: self._sync_verify_field_states())

        ttk.Label(frm, text="On mismatch:").grid(row=19, column=0, sticky="w", **pad)
        self._on_mismatch_combo = ttk.Combobox(
            frm,
            textvariable=self._verify_on_mismatch_var,
            values=list(_VERIFY_ON_MISMATCH_LABELS.keys()),
            state="readonly",
            width=24,
        )
        self._on_mismatch_combo.grid(row=19, column=1, sticky="w", **pad)

        ttk.Label(frm, text="Pixel: tolerance (%):").grid(row=20, column=0, sticky="w", **pad)
        self._verify_tol_entry = ttk.Entry(frm, textvariable=self._verify_tol_var, width=10)
        self._verify_tol_entry.grid(row=20, column=1, sticky="w", **pad)

        ttk.Label(frm, text="Pixel: per-channel threshold (0-255):").grid(
            row=21, column=0, sticky="w", **pad
        )
        self._verify_thresh_entry = ttk.Entry(frm, textvariable=self._verify_thresh_var, width=10)
        self._verify_thresh_entry.grid(row=21, column=1, sticky="w", **pad)

        ttk.Label(frm, text="pHash: max Hamming distance (0-324):").grid(
            row=22, column=0, sticky="w", **pad
        )
        self._verify_phash_entry = ttk.Entry(frm, textvariable=self._verify_phash_dist_var, width=10)
        self._verify_phash_entry.grid(row=22, column=1, sticky="w", **pad)

        ttk.Checkbutton(
            frm, text="Capture before-action screenshots while recording",
            variable=self._capture_before_var,
        ).grid(row=23, column=0, columnspan=2, sticky="w", padx=10, pady=2)

        ttk.Checkbutton(
            frm, text="Minimize main window during playback",
            variable=self._minimize_var,
        ).grid(row=24, column=0, columnspan=2, sticky="w", padx=10, pady=2)

        self._sync_verify_field_states()

        btns = ttk.Frame(frm)
        btns.grid(row=25, column=0, columnspan=2, sticky="e", pady=(12, 0))
        ttk.Button(btns, text="Reset to defaults", command=self._reset).pack(
            side="left", padx=4
        )
        ttk.Button(btns, text="Cancel", command=self._cancel).pack(side="left", padx=4)
        ttk.Button(btns, text="Save", command=self._save).pack(side="left", padx=4)

    def _center_on_parent(self, parent: tk.Misc) -> None:
        try:
            px = parent.winfo_rootx()
            py = parent.winfo_rooty()
            pw = parent.winfo_width()
            ph = parent.winfo_height()
            w = self.winfo_width()
            h = self.winfo_height()
            x = px + max(0, (pw - w) // 2)
            y = py + max(0, (ph - h) // 2)
            self.geometry(f"+{x}+{y}")
        except Exception:
            pass

    # ── Handlers ──────────────────────────────────────────────────────

    def _sync_verify_field_states(self) -> None:
        """Enable/disable verification entries based on selected method."""
        method_label = self._verify_method_var.get()
        method = _VERIFY_METHOD_LABELS.get(method_label, "pixel")

        # Pixel-only fields
        pixel_state = "normal" if method == "pixel" else "disabled"
        self._verify_tol_entry.config(state=pixel_state)
        self._verify_thresh_entry.config(state=pixel_state)

        # pHash-only fields
        phash_state = "normal" if method == "phash" else "disabled"
        self._verify_phash_entry.config(state=phash_state)

        # On-mismatch is irrelevant when verification is disabled.
        self._on_mismatch_combo.config(
            state="readonly" if method != "disabled" else "disabled"
        )

    def _browse_folder(self) -> None:
        current = self._folder_var.get()
        initial = current if Path(current).is_absolute() else str(Path.cwd())
        chosen = filedialog.askdirectory(parent=self, initialdir=initial, mustexist=False)
        if chosen:
            self._folder_var.set(chosen)

    def _reset(self) -> None:
        self._folder_var.set(_DEFAULTS["recordings_dir_name"])
        self._hotkey_var.set(_DEFAULTS["stop_hotkey"])
        self._settle_var.set(str(_DEFAULTS["post_inject_settle_seconds"]))
        self._idle_var.set(str(_DEFAULTS["text_buffer_idle_flush_seconds"]))
        self._pause_var.set(str(_DEFAULTS["pyautogui_pause"]))
        self._target_title_var.set(_DEFAULTS["target_title_contains"])
        self._target_launch_var.set(_DEFAULTS["target_auto_launch_uri"])
        self._target_fullscreen_var.set(_DEFAULTS["target_fullscreen_only"])
        self._target_stop_focus_var.set(_DEFAULTS["target_stop_on_focus_loss"])
        self._target_stop_min_var.set(_DEFAULTS["target_stop_on_minimize"])
        self._verify_method_var.set(_DEFAULTS["verify_method_label"])
        self._verify_on_mismatch_var.set(_DEFAULTS["verify_on_mismatch_label"])
        self._verify_tol_var.set(str(_DEFAULTS["verify_tolerance_pct"]))
        self._verify_thresh_var.set(str(_DEFAULTS["verify_pixel_threshold"]))
        self._verify_phash_dist_var.set(str(_DEFAULTS["verify_phash_max_distance"]))
        self._capture_before_var.set(_DEFAULTS["capture_before_screenshots"])
        self._minimize_var.set(_DEFAULTS["minimize_during_playback"])
        self._sync_verify_field_states()

    def _parse_non_negative_float(self, raw: str, label: str) -> float:
        try:
            value = float(raw.strip())
        except ValueError:
            raise ValueError(f"{label} must be a number.")
        if value < 0:
            raise ValueError(f"{label} must be ≥ 0.")
        return value

    def _save(self) -> None:
        try:
            folder = self._folder_var.get().strip()
            if not folder:
                raise ValueError("Recordings folder must not be empty.")

            hotkey = self._hotkey_var.get().strip().lower()
            if hotkey not in _HOTKEYS:
                raise ValueError(f"Stop hotkey must be one of: {', '.join(_HOTKEYS)}.")

            settle = self._parse_non_negative_float(self._settle_var.get(), "Settle delay")
            idle = self._parse_non_negative_float(self._idle_var.get(), "Text buffer idle flush")
            pause = self._parse_non_negative_float(self._pause_var.get(), "PyAutoGUI pause")

            method_label = self._verify_method_var.get()
            if method_label not in _VERIFY_METHOD_LABELS:
                raise ValueError(f"Verification method must be one of: {', '.join(_VERIFY_METHOD_LABELS)}.")
            method_token = _VERIFY_METHOD_LABELS[method_label]

            on_mismatch_label = self._verify_on_mismatch_var.get()
            if on_mismatch_label not in _VERIFY_ON_MISMATCH_LABELS:
                raise ValueError(f"On-mismatch must be one of: {', '.join(_VERIFY_ON_MISMATCH_LABELS)}.")
            on_mismatch_token = _VERIFY_ON_MISMATCH_LABELS[on_mismatch_label]

            verify_tol = self._parse_non_negative_float(
                self._verify_tol_var.get(), "Pixel tolerance"
            )
            try:
                verify_thresh = int(self._verify_thresh_var.get().strip())
            except ValueError:
                raise ValueError("Pixel threshold must be an integer.")
            if not 0 <= verify_thresh <= 255:
                raise ValueError("Pixel threshold must be between 0 and 255.")
            try:
                verify_phash = int(self._verify_phash_dist_var.get().strip())
            except ValueError:
                raise ValueError("pHash max distance must be an integer.")
            if not 0 <= verify_phash <= 324:
                raise ValueError("pHash max distance must be between 0 and 324.")
        except ValueError as exc:
            messagebox.showerror("Invalid setting", str(exc), parent=self)
            return

        from pynput import keyboard as kb

        restart_changed = (
            folder != config.RECORDINGS_DIR_NAME
            or hotkey != config.STOP_HOTKEY.name
        )

        config.RECORDINGS_DIR_NAME = folder
        config.STOP_HOTKEY = getattr(kb.Key, hotkey)
        config.POST_INJECT_SETTLE_SECONDS = settle
        config.TEXT_BUFFER_IDLE_FLUSH_SECONDS = idle
        config.PYAUTOGUI_PAUSE = pause
        config.TARGET_WINDOW_TITLE_CONTAINS = self._target_title_var.get().strip()
        config.TARGET_WINDOW_AUTO_LAUNCH_URI = self._target_launch_var.get().strip()
        config.TARGET_WINDOW_FULLSCREEN_ONLY = bool(self._target_fullscreen_var.get())
        config.TARGET_WINDOW_STOP_ON_FOCUS_LOSS = bool(self._target_stop_focus_var.get())
        config.TARGET_WINDOW_STOP_ON_MINIMIZE = bool(self._target_stop_min_var.get())

        # Verification: "disabled" maps to flipping the master toggle off
        # while preserving the previously-selected method as the next
        # default if the user re-enables it.
        if method_token == "disabled":
            config.VERIFY_BEFORE_ACTION = False
        else:
            config.VERIFY_BEFORE_ACTION = True
            config.VERIFY_METHOD = method_token
        config.VERIFY_ON_MISMATCH = on_mismatch_token
        config.VERIFY_TOLERANCE_PCT = verify_tol
        config.VERIFY_PIXEL_THRESHOLD = verify_thresh
        config.VERIFY_PHASH_MAX_DISTANCE = verify_phash
        config.CAPTURE_BEFORE_SCREENSHOTS = bool(self._capture_before_var.get())
        config.MINIMIZE_DURING_PLAYBACK = bool(self._minimize_var.get())

        try:
            config.save_to_disk()
        except Exception as exc:
            messagebox.showerror(
                "Could not save settings",
                f"Settings updated for this session but couldn't be written to disk:\n{exc}",
                parent=self,
            )
        config.apply_runtime_settings()

        if restart_changed:
            messagebox.showinfo(
                "Restart required",
                "Recordings folder and stop hotkey changes take effect after restarting the app.",
                parent=self,
            )

        if self._on_saved is not None:
            try:
                self._on_saved()
            except Exception:
                pass

        self.destroy()

    def _cancel(self) -> None:
        self.destroy()
