# Recorder — Model B (drive a remote devbox via Windows App)

The recorder/player can be used in two modes:

| Mode | Behavior |
|---|---|
| **Legacy** (default) | Records absolute screen coords. Replays at the same screen coords. Good for local apps. |
| **Model B** | Records coords **relative to a Microsoft Windows App session window** that's connected to your devbox. Replays into that window even if it's been moved or restarted. |

Model B is what you want when the recorder runs on your **laptop** and you
want to test a UI on the **devbox** through the Windows App session.

## Enable Model B

Edit `recorder/config.json`:

```json
"target_window": {
  "title_contains": "devbox",
  "fullscreen_only": true
}
```

- `title_contains` — substring of your Windows App session window title
  (case-insensitive). Empty string disables Model B (legacy mode).
- `fullscreen_only` — set `true` if your Windows App is fullscreen so the
  Win-key reaches the remote session. In windowed mode the Win-key never
  forwards; use Alt-Home shortcuts on the devbox instead.

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
- The session-window settings aren't surfaced in the GUI yet — edit
  `config.json` directly and restart the recorder.
