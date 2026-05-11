"""Non-UI behavioral configuration for the recorder/player.

Values are loaded from ``config.json`` at the repository root. Most are
exposed as plain module attributes; the recorder/player read them via
``recorder.config.X`` at use-time so the settings dialog can update them
live without restarting the app.
"""

import json
from pathlib import Path

from pynput import keyboard as kb

# settings.py → config → recorder → src → repo root
_CONFIG_PATH = Path(__file__).resolve().parent.parent.parent.parent / "config.json"


def _load_config() -> dict:
    with open(_CONFIG_PATH, encoding="utf-8") as f:
        return json.load(f)


_cfg = _load_config()

# ── Playback ──────────────────────────────────────────────────────────

PYAUTOGUI_PAUSE: float = _cfg["playback"]["pyautogui_pause"]
PLAYBACK_SLEEP_INCREMENT: float = _cfg["playback"]["sleep_increment"]
# Verification of the pre-action screen state during playback. Loaded with
# ``.get()`` defaults so older config.json files without these keys keep
# working.
VERIFY_BEFORE_ACTION: bool = _cfg["playback"].get("verify_before_action", True)
_raw_method = str(_cfg["playback"].get("verify_method", "pixel")).lower()
VERIFY_METHOD: str = _raw_method if _raw_method in ("pixel", "phash") else "pixel"
VERIFY_TOLERANCE_PCT: float = float(_cfg["playback"].get("verify_tolerance_pct", 25.0))
VERIFY_PIXEL_THRESHOLD: int = int(_cfg["playback"].get("verify_pixel_threshold", 16))
VERIFY_PHASH_MAX_DISTANCE: int = int(_cfg["playback"].get("verify_phash_max_distance", 125))
_raw_on_mismatch = str(_cfg["playback"].get("verify_on_mismatch", "halt")).lower()
VERIFY_ON_MISMATCH: str = _raw_on_mismatch if _raw_on_mismatch in ("halt", "continue") else "halt"
MINIMIZE_DURING_PLAYBACK: bool = bool(_cfg["playback"].get("minimize_during_playback", True))

# ── Recording ─────────────────────────────────────────────────────────

WORKER_JOIN_TIMEOUT: float = _cfg["recording"]["worker_join_timeout"]
SCREENSHOT_HASH_LENGTH: int = _cfg["recording"]["screenshot_hash_length"]
POST_INJECT_SETTLE_SECONDS: float = _cfg["recording"]["post_inject_settle_seconds"]
TEXT_BUFFER_IDLE_FLUSH_SECONDS: float = _cfg["recording"]["text_buffer_idle_flush_seconds"]
CAPTURE_BEFORE_SCREENSHOTS: bool = _cfg["recording"].get("capture_before_screenshots", True)
# Stable-capture: poll the screen until two consecutive captures are
# near-identical (pHash distance) before saving / comparing. Eliminates
# spurious diffs caused by capturing mid-animation. Defaults tuned for
# snappy desktop apps; bump max_wait for slower / heavily animated UIs.
STABLE_POLL_INTERVAL_SECONDS: float = float(
    _cfg["recording"].get("stable_poll_interval_seconds", 0.05)
)
STABLE_MAX_WAIT_SECONDS: float = float(
    _cfg["recording"].get("stable_max_wait_seconds", 0.8)
)
STABLE_PHASH_DISTANCE: int = int(
    _cfg["recording"].get("stable_phash_distance", 8)
)

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
    """Persist the current module-level values back into config.json.

    Reads attributes through the ``recorder.config`` package namespace so
    that mutations made via ``recorder.config.X = ...`` (the pattern used
    by the settings dialog) actually reach disk. Reading the bare names
    here would resolve them at this module's scope, which the dialog
    never updates.
    """
    import importlib
    pkg = importlib.import_module(__package__)
    g = vars(pkg)
    payload = {
        "playback": {
            "pyautogui_pause": g["PYAUTOGUI_PAUSE"],
            "sleep_increment": g["PLAYBACK_SLEEP_INCREMENT"],
            "verify_before_action": g["VERIFY_BEFORE_ACTION"],
            "verify_method": g["VERIFY_METHOD"],
            "verify_tolerance_pct": g["VERIFY_TOLERANCE_PCT"],
            "verify_pixel_threshold": g["VERIFY_PIXEL_THRESHOLD"],
            "verify_phash_max_distance": g["VERIFY_PHASH_MAX_DISTANCE"],
            "verify_on_mismatch": g["VERIFY_ON_MISMATCH"],
            "minimize_during_playback": g["MINIMIZE_DURING_PLAYBACK"],
        },
        "recording": {
            "worker_join_timeout": g["WORKER_JOIN_TIMEOUT"],
            "screenshot_hash_length": g["SCREENSHOT_HASH_LENGTH"],
            "post_inject_settle_seconds": g["POST_INJECT_SETTLE_SECONDS"],
            "text_buffer_idle_flush_seconds": g["TEXT_BUFFER_IDLE_FLUSH_SECONDS"],
            "capture_before_screenshots": g["CAPTURE_BEFORE_SCREENSHOTS"],
            "stable_poll_interval_seconds": g["STABLE_POLL_INTERVAL_SECONDS"],
            "stable_max_wait_seconds": g["STABLE_MAX_WAIT_SECONDS"],
            "stable_phash_distance": g["STABLE_PHASH_DISTANCE"],
        },
        "application": {
            "window_title": g["WINDOW_TITLE"],
            "stop_hotkey": g["STOP_HOTKEY"].name,
            "recordings_dir_name": g["RECORDINGS_DIR_NAME"],
            "info_wraplength": g["INFO_WRAPLENGTH"],
        },
        "target_window": {
            "title_contains": g["TARGET_WINDOW_TITLE_CONTAINS"],
            "fullscreen_only": g["TARGET_WINDOW_FULLSCREEN_ONLY"],
            "auto_launch_uri": g["TARGET_WINDOW_AUTO_LAUNCH_URI"],
            "stop_on_focus_loss": g["TARGET_WINDOW_STOP_ON_FOCUS_LOSS"],
            "stop_on_minimize": g["TARGET_WINDOW_STOP_ON_MINIMIZE"],
        },
    }
    _CONFIG_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
