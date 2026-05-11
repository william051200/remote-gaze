"""Non-UI behavioral configuration for the recorder/player.

Values are loaded from ``config.json`` alongside this file. Most are
exposed as plain module attributes; the recorder/player read them via
``recorder.config.X`` at use-time so the settings dialog can update them
live without restarting the app.
"""

import json
from pathlib import Path

from pynput import keyboard as kb

_CONFIG_PATH = Path(__file__).parent / "config.json"


def _load_config() -> dict:
    with open(_CONFIG_PATH, encoding="utf-8") as f:
        return json.load(f)


_cfg = _load_config()

# ── Playback ──────────────────────────────────────────────────────────

PYAUTOGUI_PAUSE: float = _cfg["playback"]["pyautogui_pause"]
PLAYBACK_SLEEP_INCREMENT: float = _cfg["playback"]["sleep_increment"]

# ── Recording ─────────────────────────────────────────────────────────

WORKER_JOIN_TIMEOUT: float = _cfg["recording"]["worker_join_timeout"]
SCREENSHOT_HASH_LENGTH: int = _cfg["recording"]["screenshot_hash_length"]
POST_INJECT_SETTLE_SECONDS: float = _cfg["recording"]["post_inject_settle_seconds"]
TEXT_BUFFER_IDLE_FLUSH_SECONDS: float = _cfg["recording"]["text_buffer_idle_flush_seconds"]

# ── Application ───────────────────────────────────────────────────────

WINDOW_TITLE: str = _cfg["application"]["window_title"]
RECORDINGS_DIR_NAME: str = _cfg["application"]["recordings_dir_name"]
INFO_WRAPLENGTH: int = _cfg["application"]["info_wraplength"]

# ── Target window (Model B: drive a remote app session window) ────────
# Empty title_contains disables Model B and keeps legacy whole-screen
# recording. Non-empty: events outside the matched window are dropped at
# record time, mouse coords are stored relative to the window, and
# playback re-targets the same window (which may have moved since).

_target_cfg = _cfg.get("target_window", {})
TARGET_WINDOW_TITLE_CONTAINS: str = _target_cfg.get("title_contains", "")
TARGET_WINDOW_FULLSCREEN_ONLY: bool = _target_cfg.get("fullscreen_only", True)
TARGET_WINDOW_AUTO_LAUNCH_URI: str = _target_cfg.get("auto_launch_uri", "")
TARGET_WINDOW_STOP_ON_FOCUS_LOSS: bool = _target_cfg.get("stop_on_focus_loss", True)
TARGET_WINDOW_STOP_ON_MINIMIZE: bool = _target_cfg.get("stop_on_minimize", True)

# Convert hotkey string (e.g. "f6") to pynput Key enum
STOP_HOTKEY = getattr(kb.Key, _cfg["application"]["stop_hotkey"])


def apply_runtime_settings() -> None:
    """Sync external state that mirrors module-level settings.

    Currently this just pushes ``PYAUTOGUI_PAUSE`` into the ``pyautogui``
    module. Call this after mutating any of the timing constants from the
    settings dialog so consumers immediately observe the new values.
    """
    try:
        import pyautogui
        pyautogui.PAUSE = PYAUTOGUI_PAUSE
    except Exception:
        pass


def save_to_disk() -> None:
    """Persist the current module-level values back into config.json."""
    payload = {
        "playback": {
            "pyautogui_pause": PYAUTOGUI_PAUSE,
            "sleep_increment": PLAYBACK_SLEEP_INCREMENT,
        },
        "recording": {
            "worker_join_timeout": WORKER_JOIN_TIMEOUT,
            "screenshot_hash_length": SCREENSHOT_HASH_LENGTH,
            "post_inject_settle_seconds": POST_INJECT_SETTLE_SECONDS,
            "text_buffer_idle_flush_seconds": TEXT_BUFFER_IDLE_FLUSH_SECONDS,
        },
        "application": {
            "window_title": WINDOW_TITLE,
            "stop_hotkey": STOP_HOTKEY.name,
            "recordings_dir_name": RECORDINGS_DIR_NAME,
            "info_wraplength": INFO_WRAPLENGTH,
        },
        "target_window": {
            "title_contains": TARGET_WINDOW_TITLE_CONTAINS,
            "fullscreen_only": TARGET_WINDOW_FULLSCREEN_ONLY,
            "auto_launch_uri": TARGET_WINDOW_AUTO_LAUNCH_URI,
            "stop_on_focus_loss": TARGET_WINDOW_STOP_ON_FOCUS_LOSS,
            "stop_on_minimize": TARGET_WINDOW_STOP_ON_MINIMIZE,
        },
    }
    _CONFIG_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
