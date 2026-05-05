# POC — Drive a devbox UI from your laptop via Windows App

A tiny feasibility script. Answers one question:

> Can a Python script on my laptop click a button on the devbox and screenshot
> the result back, using the existing Microsoft **Windows App** session?

It does **not** speak the RDP protocol. It treats the Windows App session
window as a regular top-level window on the laptop and drives its pixels via
standard Windows APIs (`pyautogui`, `pywin32`, `Pillow`).

## Prerequisites

- Windows laptop.
- Microsoft **Windows App** installed and signed in with your corp account.
- The devbox connection is reachable via Windows App (today's normal flow).
- Python 3.10+.

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

Key fields:

- `window_title_contains` — a substring of the Windows App session window
  title (usually the devbox / Dev Box connection name).
- `launch_uri` — optional. Best-effort launch via `ms-avd:` / `ms-rd:` URI
  or a command like `msrdcw.exe`. Leave blank to skip launch and assume the
  session is already open.
- `click_x` / `click_y` — coordinates **relative to the session window's
  top-left**. Pick something safe like an empty area of the desktop.
- `type_text` — text to type after the click.

## Run

1. Open the devbox session in Windows App. Make sure the window is **visible
   and not minimized or locked**.
2. From the repo root:

```powershell
python poc\rdp_click.py --config poc\config.ini
```

3. Look at `poc\out\screenshot.png` for the captured region.

Exit codes: `0` PASS, `2` window not found, `3` window minimized, `4`
screenshot blank.

## Caveats this POC does NOT solve

These are documented on purpose — surfacing them is the point of the POC.

- **Session must stay visible.** If you minimize Windows App or lock the
  laptop, the remote desktop stops rendering and screenshots go blank.
- **Coordinates are pixel-based.** If the Windows App window moves or
  resizes, every coordinate breaks.
- **DPI / resolution mismatch** between laptop and devbox shifts UI
  elements; the configured `click_x/click_y` may miss after a resolution
  change.
- **Network latency.** Clicks reach the devbox after a round trip; the
  script's `settle_delay` is a blunt instrument.
- **Some keys are intercepted by Windows App** (Ctrl+Alt+Del, Win-key
  combos). Plain text and ordinary clicks work fine.

## Findings

_Fill in after the first real run on a devbox._

- Date / devbox tested:
- What worked:
- What failed:
- Surprises:
- Next thing to try:
