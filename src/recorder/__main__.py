"""Entry point for the RemoteGaze Recorder.

Runs when the package is invoked with ``py -m src.recorder``. Python
sets ``__name__ == "__main__"`` on this file in that case, so the guard
at the bottom fires.
"""

# Side-effect import: enables per-monitor DPI awareness BEFORE tkinter,
# pyautogui, or PIL are loaded by the imports below. Must stay first.
from . import _dpi  # noqa: F401

from pathlib import Path

from .ui.controller import RecorderGUI
from .config import RECORDINGS_DIR_NAME


def main() -> None:
    output_dir = Path(__file__).resolve().parent.parent / RECORDINGS_DIR_NAME
    output_dir.mkdir(exist_ok=True)
    app = RecorderGUI(output_dir=output_dir)
    app.run()


if __name__ == "__main__":
    main()
