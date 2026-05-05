# POC — Drive a devbox UI from your laptop via Windows App

A small Python POC. Treats the Microsoft **Windows App** session window on
your laptop as a regular Windows window and drives its pixels with
`pyautogui` + `pywin32` + `Pillow`. **No RDP protocol implementation, no
agent on the devbox.** Whatever you can see in the Windows App window, the
script can click and screenshot.

## Layout

```
gaze/
└─ session.py          shared library: DPI, window finder, focus+attach,
                       click/type/screenshot, Win-key 80ms hold, Config

poc/
├─ rdp_click.py        smoke test: focus + click + type + screenshot
├─ open_notepad.py     open Start, launch Notepad, type, mouse-close, screenshot
├─ config.example.ini  single config for both scripts (copy to config.ini)
└─ out/                screenshots land here (gitignored)
```

`gaze/session.py` is now the single source of truth for the helpers — the
recorder app uses the same module for Model B (see `recorder/README` once
added).

Both scripts read the same `config.ini`. CLI is intentionally minimal:
just `--config` (and `--no-launch` for `rdp_click.py`). Tune behavior by
editing the ini file.

Install with the repo-root `requirements.txt`:

```powershell
pip install -r requirements.txt
```

## Prerequisites

- Windows laptop with Python 3.10+.
- Microsoft **Windows App** installed and signed in.
- The devbox is reachable via Windows App today.

## Install

```powershell
py -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r poc\requirements.txt
```

## Configure

```powershell
Copy-Item poc\config.example.ini poc\config.ini
# then edit poc\config.ini
```

The fields you'll most often touch:

| Key | What it controls |
|---|---|
| `[connection] window_title_contains` | Substring of the Windows App session window title. |
| `[action] click_x` / `click_y` | Click target (relative to session window) for `rdp_click.py`. |
| `[action] type_text` | Text typed by `rdp_click.py`. |
| `[notepad] start_method` | `win` (only works fullscreen) or `alt-home` (works windowed too). |
| `[notepad] write_text` | Text typed into Notepad after it opens. |
| `[notepad] close_x` / `close_y` | Mouse-click coords (relative to session window) used to close Notepad. Tune to where the X button lands on YOUR session. Negative = skip. |
| `[timing] *` | All wait times. Bump them up if your network is laggy. |

## Run

1. Open the devbox session in Windows App. Keep the window **visible** (not
   minimized, not locked).
2. From the repo root:

```powershell
# Smoke test - just click + type + screenshot:
python poc\rdp_click.py

# Full demo - open Notepad, type "hello world", mouse-close, screenshot:
python poc\open_notepad.py
```

Screenshots land in `poc/out/`.

Exit codes: `0` PASS, `2` window not found, `3` window minimized, `4`
screenshot blank.

## Coordinate model

Everything in `config.ini` (`click_x/y`, `close_x/y`) is **pixels relative
to the Windows App session window's top-left**. The scripts add the
window's screen position at runtime, so moving the Windows App window
doesn't break your coords — only resizing or zoom changes do.

## Known caveats (intentionally not solved here)

- **Session must stay visible.** Minimize / lock = blank screenshots.
- **DPI / resolution mismatch** between laptop and devbox shifts the
  remote UI; click coords may need re-tuning when resolution changes.
- **Network latency.** Bump the `[timing]` waits if clicks fire before the
  remote UI is ready.
- **Some keys are intercepted by Windows App** (Ctrl+Alt+Del, most
  Win+`<key>` combos in windowed mode). Use `start_method = alt-home` for
  the Start menu when not fullscreen.

## Findings

- `rdp_click.py`: PASS — clicks land, screenshot saved.
- `open_notepad.py`: PASS — Notepad opens, "hello world" typed, mouse
  close at relative `(close_x, close_y)` from `config.ini`. Required
  `start_method = alt-home` when Windows App was windowed.
- `close_x` / `close_y` is resolution-sensitive — tune per session.
  Future improvement: detect Notepad's window position via a short-lived
  agent on the devbox, or use `Alt+F4` instead of a mouse click.
