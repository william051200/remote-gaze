# Remote Agent POC

Drive a devbox UI from your laptop by running a small HTTP **agent** on the
devbox. The laptop sends `click` / `type` / `screenshot` commands over HTTP;
the agent executes them locally on the devbox using `pyautogui` + `Pillow`.

Compared to the RDP-pixel POC (`poc/`), this:

- uses **real devbox coordinates** (no Windows App window math, no DPI mismatch)
- doesn't need the Windows App window to stay visible during the test run
- gives clearer failures (HTTP status codes) and a path to upgrade later
  (e.g. add an accessibility-tree endpoint via `uiautomation`)

> **The big open question:** can your laptop reach the devbox on an arbitrary
> TCP port? Microsoft Dev Box / Cloud PC may block inbound traffic. Run
> `check_connectivity.py` first \u2014 it's designed to tell you exactly which
> layer fails.

## Layout

```
agent_poc/
\u251c\u2500\u2500 agent/                    # runs ON the devbox
\u2502   \u251c\u2500\u2500 server.py
\u2502   \u2514\u2500\u2500 requirements.txt
\u251c\u2500\u2500 client/                   # runs ON the laptop
\u2502   \u251c\u2500\u2500 check_connectivity.py
\u2502   \u251c\u2500\u2500 demo.py
\u2502   \u2514\u2500\u2500 requirements.txt
\u251c\u2500\u2500 config.example.ini
\u2514\u2500\u2500 README.md
```

## Setup

### On the devbox (one-time)

1. RDP in via Windows App, sign in.
2. Open a terminal **inside the Windows App session** (must be in the
   interactive desktop session, not session 0 \u2014 a Windows service can't see
   the UI).
3. Clone or copy this repo, then:

```powershell
cd agent_poc\agent
py -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

4. Pick a long random shared secret and set it:

```powershell
$env:GAZE_TOKEN = "use-a-long-random-string-here"
```

5. Open the firewall for the chosen port (one-time; default 8765):

```powershell
New-NetFirewallRule -DisplayName "remote-gaze agent" `
  -Direction Inbound -Protocol TCP -LocalPort 8765 -Action Allow
```

6. Start the agent (must stay running while tests run):

```powershell
python server.py --port 8765
```

You should see uvicorn log `Application startup complete.`

### On the laptop (one-time)

```powershell
cd agent_poc\client
py -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item ..\config.example.ini ..\config.ini
# edit ..\config.ini: devbox_host, port, token (must match GAZE_TOKEN)
```

## Run it

### Step 1 \u2014 connectivity check

```powershell
python check_connectivity.py --config ..\config.ini
```

This walks DNS \u2192 TCP \u2192 token \u2192 healthz and prints exactly which one
fails plus next-step hints. Don't proceed until this prints `PASS`.

### Step 2 \u2014 demo

```powershell
python demo.py --config ..\config.ini
```

On success, look at `client/out/before.png` and `client/out/after.png` \u2014 you
should see the click + typed text reflected on the devbox.

## Caveats

- **Agent must run inside an interactive session.** Logging out of the
  devbox (closing Windows App or signing the user out) kills the desktop
  session and the agent stops being able to see / click the UI.
- **Shared-token auth only.** Anyone who can reach the port and knows the
  token gets full mouse/keyboard control of the devbox. POC-only; production
  needs proper auth.
- **No retries / no waits-for-element.** The demo blindly clicks coordinates
  after a fixed delay. Real tests would need synchronization.
- **Coordinates are physical pixels** of the devbox primary monitor (DPI
  awareness is set at agent startup).

## Findings

_Fill in after the first real run on a devbox._

- Date / devbox tested:
- `check_connectivity.py` result (which step PASS/FAIL):
- `demo.py` result:
- Inbound TCP from laptop \u2192 devbox: works? required VPN? required port
  change? blocked entirely?
- Surprises:
- Next thing to try:
