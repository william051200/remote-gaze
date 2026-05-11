"""View construction for the recorder GUI.

Each `build_*` function takes the controller (`gui`, an instance of
`recorder.ui.controller.RecorderGUI`) and the parent frame, creates widgets, and
attaches them to `gui` as attributes the controller methods expect.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from ..config import INFO_WRAPLENGTH
from ..platform.monitors import list_monitors
from ..config.theme import COLORS, FONT_FAMILY, THUMBNAIL_SIZE
from .widgets import BTN_STYLE, draw_placeholder


def build_ui(gui) -> None:
    """Build the full widget tree under `gui.root`."""
    main = tk.Frame(gui.root, bg=COLORS["bg"], padx=12, pady=8)
    main.pack(fill="both", expand=True)

    _build_header(gui, main)
    _build_fail_banner(gui, main)
    _build_toolbar(gui, main)
    _build_info_bar(gui, main)
    _build_screenshot_panels(gui, main)
    _build_navigation(gui, main)
    _build_footer(gui, main)


def _build_header(gui, parent: tk.Frame) -> None:
    """Row 1: App title + status indicator."""
    row = tk.Frame(parent, bg=COLORS["bg"])
    row.pack(fill="x", pady=(0, 6))
    tk.Label(row, text="⊙ RemoteGaze", font=(FONT_FAMILY, 14, "bold"),
             bg=COLORS["bg"], fg=COLORS["text_primary"]).pack(side="left")
    gui.status_var = tk.StringVar(value="Idle")
    tk.Label(row, textvariable=gui.status_var, font=(FONT_FAMILY, 10),
             bg=COLORS["bg"], fg=COLORS["accent"]).pack(side="right")


def _build_fail_banner(gui, parent: tk.Frame) -> None:
    """Compact red TEST FAILED banner. Hidden by default; the controller
    packs it via ``_show_fail_banner`` when verification fails and
    ``_hide_fail_banner`` removes it on the next state change.

    Sized to be unmistakable but not jarring — sits at roughly the same
    visual weight as the header.
    """
    fail_bg = "#c62828"  # strong red
    banner = tk.Frame(parent, bg=fail_bg, padx=10, pady=6)
    # Don't pack yet — controller will pack it on demand.
    gui.fail_banner = banner
    gui.fail_banner_parent = parent

    gui.fail_banner_title_var = tk.StringVar(value="❌ TEST FAILED")
    tk.Label(
        banner,
        textvariable=gui.fail_banner_title_var,
        font=(FONT_FAMILY, 13, "bold"),
        bg=fail_bg,
        fg="#ffffff",
    ).pack(side="top", anchor="w")

    gui.fail_banner_subtitle_var = tk.StringVar(value="")
    tk.Label(
        banner,
        textvariable=gui.fail_banner_subtitle_var,
        font=(FONT_FAMILY, 9),
        bg=fail_bg,
        fg="#ffe5e5",
        wraplength=INFO_WRAPLENGTH,
        justify="left",
    ).pack(side="top", anchor="w", pady=(1, 0))


def _build_toolbar(gui, parent: tk.Frame) -> None:
    """Row 2: Test case name entry + action buttons + capture target picker."""
    row = tk.Frame(parent, bg=COLORS["bg"])
    row.pack(fill="x", pady=(0, 6))
    # Stash the toolbar so the FAIL banner can re-pack itself just
    # above this widget when shown.
    gui.fail_banner_anchor = row

    tk.Label(row, text="Test Case:", font=(FONT_FAMILY, 9),
             bg=COLORS["bg"], fg=COLORS["text_secondary"]).pack(side="left")
    gui.name_var = tk.StringVar(value="")
    gui.name_entry = tk.Entry(
        row, textvariable=gui.name_var, font=(FONT_FAMILY, 9),
        bg=COLORS["surface"], fg=COLORS["text_primary"], relief="flat",
        width=20, highlightbackground=COLORS["border"], highlightthickness=1,
        insertbackground=COLORS["text_primary"],
    )
    gui.name_entry.pack(side="left", padx=(4, 8))

    gui.start_btn = tk.Button(
        row, text="🔴 Record", bg=COLORS["green"], fg="#ffffff",
        command=gui._start_recording,
        activebackground="#15932f", activeforeground="white", **BTN_STYLE,
    )
    gui.start_btn.pack(side="left", padx=(0, 2))

    gui.stop_btn = tk.Button(
        row, text="⏹ Stop Rec", bg=COLORS["red"], fg="#ffffff",
        command=gui._stop_recording,
        activebackground="#d94444", activeforeground="white", **BTN_STYLE,
    )
    gui.stop_btn.pack(side="left", padx=(0, 2))

    gui.play_btn = tk.Button(
        row, text="▶ Play", bg=COLORS["accent"], fg="#ffffff",
        command=gui._play_recording,
        activebackground=COLORS["accent_hover"], activeforeground="white",
        **BTN_STYLE,
    )
    gui.play_btn.pack(side="left", padx=(0, 2))

    gui.replay_btn = tk.Button(
        row, text="🔁 Replay", bg=COLORS["accent"], fg="#ffffff",
        command=gui._replay_recording,
        activebackground=COLORS["accent_hover"], activeforeground="white",
        **BTN_STYLE,
    )
    gui.replay_btn.pack(side="left", padx=(0, 2))

    gui.stop_play_btn = tk.Button(
        row, text="⏹ Stop Play", bg=COLORS["surface_hover"],
        fg=COLORS["text_secondary"], command=gui._stop_playback,
        activebackground=COLORS["border"],
        activeforeground=COLORS["text_primary"], **BTN_STYLE,
    )
    gui.stop_play_btn.pack(side="left", padx=(0, 2))

    gui.folder_btn = tk.Button(
        row, text="📂", bg=COLORS["badge_bg"], fg=COLORS["accent"],
        command=gui._open_recordings_folder,
        activebackground=COLORS["surface_hover"],
        activeforeground=COLORS["accent_hover"], **BTN_STYLE,
    )
    gui.folder_btn.pack(side="left")

    gui.settings_btn = tk.Button(
        row, text="⚙", bg=COLORS["badge_bg"], fg=COLORS["accent"],
        command=gui._open_settings,
        activebackground=COLORS["surface_hover"],
        activeforeground=COLORS["accent_hover"], **BTN_STYLE,
    )
    gui.settings_btn.pack(side="left", padx=(2, 0))

    # Capture target picker — unified Monitor + Target window list.
    # Monitor entries record the whole display; window entries enable
    # Model B (window-relative coords + window-cropped screenshots).
    # Refreshed on click so the live window list is always current.
    gui._monitors = list_monitors()
    tk.Label(row, text="Capture:", font=(FONT_FAMILY, 9),
             bg=COLORS["bg"], fg=COLORS["text_secondary"]).pack(
        side="left", padx=(12, 4))
    gui.capture_var = tk.StringVar()
    gui.capture_combo = ttk.Combobox(
        row, textvariable=gui.capture_var, state="readonly",
        width=38, font=(FONT_FAMILY, 9),
    )
    gui.capture_combo.pack(side="left")
    gui.capture_combo.bind("<Button-1>", lambda _e: gui._refresh_capture_choices())
    gui._refresh_capture_choices(initial=True)


def _build_info_bar(gui, parent: tk.Frame) -> None:
    """Row 3: Step counter + event type + action description."""
    row = tk.Frame(parent, bg=COLORS["panel"],
                   highlightbackground=COLORS["border"],
                   highlightthickness=1, padx=10, pady=4)
    row.pack(fill="x", pady=(0, 6))

    gui.step_var = tk.StringVar(value="Steps: 0")
    tk.Label(row, textvariable=gui.step_var, font=(FONT_FAMILY, 9),
             bg=COLORS["panel"], fg=COLORS["text_secondary"]).pack(side="left")

    gui.event_info_var = tk.StringVar(value="")
    tk.Label(row, textvariable=gui.event_info_var, font=(FONT_FAMILY, 9),
             bg=COLORS["panel"], fg=COLORS["text_muted"]).pack(side="left", padx=(12, 0))

    gui.desc_var = tk.StringVar(value="No action")
    tk.Label(row, textvariable=gui.desc_var, font=(FONT_FAMILY, 9, "bold"),
             bg=COLORS["panel"], fg=COLORS["text_primary"]).pack(side="right")


def _build_screenshot_panels(gui, parent: tk.Frame) -> None:
    """Row 4: Expected and Current screenshot canvases side by side."""
    frame = tk.Frame(parent, bg=COLORS["bg"])
    frame.pack(fill="x", pady=(0, 6))

    # EXPECTED column (static label).
    exp_col = tk.Frame(frame, bg=COLORS["bg"])
    exp_col.pack(side="left", padx=2, expand=True, fill="both")
    tk.Label(exp_col, text="EXPECTED", font=(FONT_FAMILY, 8, "bold"),
             bg=COLORS["bg"], fg=COLORS["text_muted"]).pack(anchor="w")
    gui.expected_canvas = tk.Canvas(
        exp_col, width=THUMBNAIL_SIZE[0], height=THUMBNAIL_SIZE[1],
        bg=COLORS["panel"], highlightbackground=COLORS["border"],
        highlightthickness=1,
    )
    gui.expected_canvas.pack(pady=(2, 0))
    draw_placeholder(gui.expected_canvas, "No recording loaded")

    # CURRENT column with dynamic label (shows diff value) + toggle.
    cur_col = tk.Frame(frame, bg=COLORS["bg"])
    cur_col.pack(side="left", padx=2, expand=True, fill="both")
    header = tk.Frame(cur_col, bg=COLORS["bg"])
    header.pack(fill="x")
    gui.current_label_var = tk.StringVar(value="CURRENT")
    tk.Label(header, textvariable=gui.current_label_var,
             font=(FONT_FAMILY, 8, "bold"),
             bg=COLORS["bg"], fg=COLORS["text_muted"]).pack(side="left")
    gui.show_diff_var = tk.BooleanVar(value=True)
    ttk.Checkbutton(
        header, text="Show diff overlay", variable=gui.show_diff_var,
        command=gui._refresh_current_view,
    ).pack(side="right")
    gui.current_canvas = tk.Canvas(
        cur_col, width=THUMBNAIL_SIZE[0], height=THUMBNAIL_SIZE[1],
        bg=COLORS["panel"], highlightbackground=COLORS["border"],
        highlightthickness=1,
    )
    gui.current_canvas.pack(pady=(2, 0))
    draw_placeholder(gui.current_canvas, "Not playing")


def _build_navigation(gui, parent: tk.Frame) -> None:
    """Row 5: Browse recording file + prev/next step buttons."""
    row = tk.Frame(parent, bg=COLORS["bg"])
    row.pack(fill="x", pady=(0, 4))

    gui.prev_btn = tk.Button(
        row, text="◀ Prev", bg=COLORS["surface_hover"],
        fg=COLORS["text_secondary"], command=gui._prev_step,
        activebackground=COLORS["border"],
        activeforeground=COLORS["text_primary"], **BTN_STYLE,
    )
    gui.prev_btn.pack(side="left", padx=(0, 2))

    gui.browse_btn = tk.Button(
        row, text="📋 Browse Recording", bg=COLORS["badge_bg"],
        fg=COLORS["accent"], command=gui._browse_recording_file,
        activebackground=COLORS["surface_hover"],
        activeforeground=COLORS["accent_hover"], **BTN_STYLE,
    )
    gui.browse_btn.pack(side="left", padx=(0, 2))

    gui.next_btn = tk.Button(
        row, text="Next ▶", bg=COLORS["surface_hover"],
        fg=COLORS["text_secondary"], command=gui._next_step,
        activebackground=COLORS["border"],
        activeforeground=COLORS["text_primary"], **BTN_STYLE,
    )
    gui.next_btn.pack(side="left")


def _build_footer(gui, parent: tk.Frame) -> None:
    """Row 6: Info/help text."""
    gui.info_var = tk.StringVar(value="Press F6 to stop recording or playback")
    tk.Label(parent, textvariable=gui.info_var, font=(FONT_FAMILY, 8),
             bg=COLORS["bg"], fg=COLORS["text_muted"],
             wraplength=INFO_WRAPLENGTH).pack(fill="x", pady=(4, 0))
