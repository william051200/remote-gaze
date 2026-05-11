"""Reusable Tk widget helpers and shared styling for the recorder GUI."""

from __future__ import annotations

import tkinter as tk

from PIL import Image, ImageTk

from ..config.theme import COLORS, FONT_FAMILY, THUMBNAIL_SIZE

# Shared button style applied to all action buttons in the toolbar/navigation.
BTN_STYLE = {
    "font": (FONT_FAMILY, 9),
    "relief": "flat",
    "borderwidth": 0,
    "padx": 10,
    "pady": 4,
    "cursor": "hand2",
}


def center_window(root: tk.Tk) -> None:
    """Center `root` horizontally and place it ~1/6 down the screen."""
    root.update_idletasks()
    w = root.winfo_width()
    h = root.winfo_height()
    sw = root.winfo_screenwidth()
    sh = root.winfo_screenheight()
    x = (sw - w) // 2
    y = max(10, (sh - h) // 6)
    root.geometry(f"+{x}+{y}")


def draw_placeholder(canvas: tk.Canvas, text: str) -> None:
    """Clear `canvas` and draw centered placeholder text."""
    canvas.delete("all")
    canvas.create_text(
        THUMBNAIL_SIZE[0] // 2, THUMBNAIL_SIZE[1] // 2,
        text=text, fill=COLORS["text_muted"], font=(FONT_FAMILY, 11),
    )


def show_image_on_canvas(gui, canvas: tk.Canvas, image: Image.Image,
                         is_expected: bool = True) -> None:
    """Resize `image` to thumbnail and display on `canvas`.

    The PhotoImage is stashed on `gui` (`_expected_photo` / `_current_photo`)
    so Tk's GC doesn't drop the underlying buffer.
    """
    thumb = image.copy()
    thumb.thumbnail(THUMBNAIL_SIZE, Image.Resampling.LANCZOS)
    photo = ImageTk.PhotoImage(thumb)
    if is_expected:
        gui._expected_photo = photo
    else:
        gui._current_photo = photo
    canvas.delete("all")
    canvas.create_image(
        THUMBNAIL_SIZE[0] // 2, THUMBNAIL_SIZE[1] // 2,
        image=photo, anchor="center",
    )
