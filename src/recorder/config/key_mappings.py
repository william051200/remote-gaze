"""Key name mappings between pynput and pyautogui.

pynput and pyautogui use different names for the same keys.
This mapping translates pynput listener output to pyautogui action input.
"""

PYNPUT_TO_PYAUTOGUI: dict[str, str] = {
    "cmd": "win",
    "cmd_l": "winleft",
    "cmd_r": "winright",
    "ctrl": "ctrl",
    "ctrl_l": "ctrlleft",
    "ctrl_r": "ctrlright",
    "alt": "alt",
    "alt_l": "altleft",
    "alt_r": "altright",
    "alt_gr": "altright",
    "shift": "shift",
    "shift_l": "shiftleft",
    "shift_r": "shiftright",
    "caps_lock": "capslock",
    "num_lock": "numlock",
    "scroll_lock": "scrolllock",
    "print_screen": "printscreen",
    "page_up": "pageup",
    "page_down": "pagedown",
    "esc": "escape",
    "media_play_pause": "playpause",
    "media_volume_up": "volumeup",
    "media_volume_down": "volumedown",
    "media_volume_mute": "volumemute",
    "menu": "apps",
}
