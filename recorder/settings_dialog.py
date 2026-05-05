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

from . import config

_HOTKEYS = [f"f{i}" for i in range(1, 13)]

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

        btns = ttk.Frame(frm)
        btns.grid(row=16, column=0, columnspan=2, sticky="e", pady=(12, 0))
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
