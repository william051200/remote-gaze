# Recorder — Model B (drive a remote devbox via Windows App)

The recorder/player can be used in two modes:

| Mode | Behavior |
|---|---|
| **Legacy** (default) | Records absolute screen coords. Replays at the same screen coords. Good for local apps. |
| **Model B** | Records coords **relative to a Microsoft Windows App session window** that's connected to your devbox. Replays into that window even if it's been moved or restarted. |

Model B is what you want when the recorder runs on your **laptop** and you
want to test a UI on the **devbox** through the Windows App session.

## Enable Model B

Configure the target window from the **Settings → Target window** dialog,
or edit `config.json` (at the repo root) directly:

```json
"target_window": {
  "title_contains": "devbox",
  "fullscreen_only": true,
  "auto_launch_uri": "",
  "stop_on_focus_loss": true,
  "stop_on_minimize": true
}
```

- `title_contains` — substring of your Windows App session window title
  (case-insensitive). Empty string disables Model B (legacy mode).
- `fullscreen_only` — set `true` if your Windows App is fullscreen so the
  Win-key reaches the remote session. In windowed mode the Win-key never
  forwards; use Alt-Home shortcuts on the devbox instead.
- `auto_launch_uri` — optional URI (e.g. an `ms-avd:` link) launched at
  record/playback start when the target window isn't already open.
- `stop_on_focus_loss` / `stop_on_minimize` — auto-stop recording or
  playback when the target window loses focus or is minimized.

When Model B is enabled:

- The recorder finds the matching Windows App window at start of every
  recording, captures its rect, drops mouse events outside it, and
  stores coords as window-relative.
- Screenshots are cropped to the window region.
- The player finds the same window at playback time, focuses it (using
  the AttachThreadInput trick for reliable focus), warm-up clicks the
  center to give the remote desktop keyboard input, and translates
  every relative click back to absolute screen coords using the window's
  *current* position.
- Win-key presses are held for ~80 ms — Windows App drops too-fast taps.

## Caveats

- **Win-key only forwards in fullscreen Windows App.** Even with the
  hold, windowed Windows App captures Win locally. Switch to fullscreen
  before recording any workflow that uses the Windows key.
- **Window resize between record and playback** still shifts UI
  elements. The player logs a warning when sizes differ but doesn't
  refuse to play.
- **No drag/scroll capture.** Same limitation as legacy mode.
- Target-window settings are editable both from the **Settings** dialog
  and directly in `config.json`.

## Pre-action screenshot verification

Each recorded event now stores **two** screenshots:

- `before_screenshot` — captured in the input listener thread, ~30–150 ms
  after the OS dispatched the event but before the worker queues it.
  Approximates the screen state immediately *before* the action's
  visible effects.
- `after_screenshot` — the post-settle snapshot the GUI shows in the
  Expected panel during browsing (unchanged behaviour).

During playback, before injecting event N the player:

1. Captures the live screen (using the same window region as the
   recorded `before_screenshot`).
2. Compares it to the recorded `before_screenshot` using the configured
   method (see below).
3. On mismatch, invokes the `on_verification_fail` callback. If
   `verify_on_mismatch` is `"halt"` (default), playback stops *before*
   firing the action and the GUI shows the recorded BEFORE alongside
   the live capture so you can diagnose the drift.

### Comparison methods

| Method | What it measures | Best for | Trade-off |
|---|---|---|---|
| `pixel` (default) | % of pixels whose per-channel max delta exceeds `verify_pixel_threshold` | Native local recording, sharp UI checks | Sensitive to RDP / JPEG compression jitter |
| `phash` | 324-bit perceptual hash + Hamming distance | Recordings played over Windows App / RDP where compression noise is high | Coarser — won't catch single-icon changes or caret blink |

Switch via `playback.verify_method` in `config.json` or via the
**Settings → Pre-action verification** dialog.

### Config knobs

All of these are now editable from the **Settings** dialog
(*Pre-action verification* section). They're also still in
`config.json` for headless/scripted use:

```jsonc
"recording": {
  "capture_before_screenshots":    true,  // disable to skip listener-thread before-shot
  "stable_poll_interval_seconds":  0.05,  // stable-capture: poll cadence between samples
  "stable_max_wait_seconds":       0.8,   // stable-capture: give up after this long
  "stable_phash_distance":         8      // stable-capture: pHash distance treated as "settled"
},
"playback": {
  "verify_before_action":      true,    // master toggle
  "verify_method":             "pixel", // "pixel" | "phash"
  "verify_tolerance_pct":      5.0,     // pixel: % of changed pixels allowed
  "verify_pixel_threshold":    16,      // pixel: per-channel delta for "changed"
  "verify_phash_max_distance": 125,     // phash: max Hamming distance (0-324)
  "verify_on_mismatch":        "halt",  // "halt" | "continue"
  "minimize_during_playback":  false    // hide recorder window while replaying
}
```

The `stable_*` knobs control the post-action settle loop: after each
recorded event the capture thread polls the screen until two consecutive
shots are within `stable_phash_distance` of each other (or
`stable_max_wait_seconds` elapses), so the stored AFTER screenshot
isn't a mid-animation frame.

### Caveats

- **Model B event 0 is never verified.** The player performs an
  unrecorded warm-up click in the centre of the target window so
  Windows App routes input to the remote desktop. That click mutates
  the screen between record-time and playback-time, so verifying the
  first event would always false-fail.
- **Size mismatch = failure** for both methods. If the live capture
  and the recorded before-shot have different dimensions (window
  resized, DPI changed, wrong region), verification fails immediately
  rather than silently resizing.
- **pHash is uniform-blind.** Two solid-colour images of different
  colours hash to similar fingerprints (no high-frequency content for
  the DCT to lock onto). For UIs with structure this is a feature; for
  contrived all-white-vs-all-black checks it isn't.
- **Older recordings still play.** Events without a
  `before_screenshot` simply skip verification with a warning.
- **Storage cost.** Hash dedup (`Recording.screenshots`) means a
  static UI between actions only stores one entry — but rapidly
  changing UIs roughly double the recording's screenshot footprint.


