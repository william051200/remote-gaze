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

### Run 1 — first attempt

- **Devbox side:** healthy.
  - `New-NetFirewallRule ... -LocalPort 8765 -Action Allow` succeeded.
  - `netstat -an | findstr 8765` → `0.0.0.0:8765   LISTENING`.
  - `python server.py --port 8765` started cleanly, uvicorn `Application
    startup complete.`
- **Laptop side:** TCP connect failed in `check_connectivity.py` step 2.

**Diagnosis:** the agent itself works. The block is **upstream of the
devbox OS**, almost certainly Microsoft Dev Box's own network policy.
Microsoft Dev Box / Cloud PC by design does not expose direct inbound TCP
from outside the Windows App / RDP gateway tunnel. A guest-OS firewall
rule cannot open a port that the Dev Box network never routes to the VM.

### Diagnostic checklist (re-run if anything changes)

Run in order:

1. **On the devbox**, prove the agent works locally:
   ```powershell
   curl.exe http://127.0.0.1:8765/healthz -H "Authorization: Bearer $env:GAZE_TOKEN"
   ```
   Expected: `{"ok": true, ...}`. If this fails, the problem is the agent
   itself, not the network.

2. **On the devbox**, get its IP:
   ```powershell
   ipconfig | findstr IPv4
   ```
   If the only IP is private (10.x / 172.16-31.x / 192.168.x) and your
   laptop isn't on the same network, you cannot route to it without a
   VPN.

3. **What does `devbox_host` in `config.ini` resolve to?** A Dev Box public
   DNS name (e.g. `*.devbox.microsoft.com`) typically resolves to the RDP
   gateway, not to the devbox's IP. Inbound TCP on port 8765 will never
   reach the VM through the gateway.

4. **From the laptop**:
   ```powershell
   Test-NetConnection -ComputerName <devbox_host> -Port 8765
   ```
   `TcpTestSucceeded : False` confirms the network path is blocked.

### Likely conclusion and paths forward

If the devbox is a **Microsoft Dev Box**, direct inbound TCP from the
laptop will not work regardless of guest-OS firewall changes. Three
options, in order of practicality:

| Option | What | Effort | Notes |
|---|---|---|---|
| **A. Reverse tunnel** | Agent on devbox makes an *outbound* connection to a relay (Cloudflare Tunnel, ngrok, custom WebSocket relay). Laptop talks to the relay's public URL. | Low\u2013medium | Devboxes almost always allow outbound HTTPS. Auth + relay choice need a small follow-up plan. |
| **B. Run tests inside the devbox** | Don't drive remotely at all. Trigger from Windows App / scheduled task, push results out to a blob store / GitHub. | Low | Loses the "drive from laptop" goal but is bulletproof. |
| **C. Fall back to `poc/rdp-pixel`** | Use the previous POC. Windows App is the only inbound path Dev Box allows, so drive its pixels. | Zero \u2014 already built | Has all the documented caveats (DPI, window must stay visible, etc.). |

Recommended next experiment: try **A. reverse tunnel** with Cloudflare
Tunnel (free, no inbound port needed). If the devbox can `cloudflared
tunnel run`, the relay path proves the laptop can talk to the agent
indirectly. That becomes the production transport pattern.
