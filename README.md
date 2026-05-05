# RemoteGaze

Automated UI testing framework that remotely observes and interacts with desktop applications, enabling repeatable verification across releases.

## Status

🟢 **Active development** — PyAutoGUI recorder/playback app implemented.

## Recorder App

A desktop app that records mouse/keyboard interactions with coordinates, timestamps, and full screenshots — then replays them step by step.

### Features

- **Record** mouse clicks and keyboard input via global OS hook (passive observation)
- **Screenshot per event** captured just after the input fires, stored as base64 in JSON (SHA-256 hash deduplication)
- **Typing batched** into single `type_text` events — no screenshot per keystroke
- **Playback** with original timing, showing expected vs current screenshot comparison
- **Clean UI** inspired by Notion's design system
- Self-click filtering to ignore recorder GUI interactions

### Quick Start

```bash
pip install -r requirements.txt
py -m recorder
```

### How It Works

1. Click **● Record** to start capturing
2. Interact with your desktop — input flows normally to the target app; the recorder observes each event and snapshots the screen right after
3. Click **■ Stop** (or press **F6**) to save the recording as a single `.json` file in `recordings/`
4. Click **▶ Play** to load and replay a recording, with side-by-side expected vs current screenshots

### Capture Model

Each recorded event stores a single screenshot taken shortly after the event. Event types:

- `mouse_click` — single click (optionally with `modifiers` for Shift+Click / Ctrl+Click)
- `type_text` — a buffered run of plain typed characters (one event + one screenshot per typing run, flushed on idle, special key, click, or stop)
- `key_press` — a single non-printable key tap (Enter, Tab, arrows, F-keys, …)
- `hotkey` — modifier(s) + key chord (e.g. Ctrl+S, Alt+Tab); replayed via `pyautogui.hotkey`

### Recording Format

All data (events + screenshots) is stored in a single JSON file. Screenshots are base64-encoded and deduplicated by content hash — identical screenshots are stored only once.

## Goal

Eliminate repetitive manual UI testing by automating button clicks, menu navigation, form interactions, and visual verification for every new release.

## Design

UI design inspired by [Notion](https://www.notion.so/). Design system reference: [`DESIGN.md`](DESIGN.md)

> Design system sourced from [VoltAgent/awesome-design-md](https://github.com/VoltAgent/awesome-design-md) — a curated collection of DESIGN.md files inspired by developer-focused websites. Licensed under MIT.
