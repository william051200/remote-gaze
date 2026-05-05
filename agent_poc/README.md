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

### Run 2 — confirm & give up on direct inbound

After updating `devbox_host` to the devbox's IPv4 from `ipconfig`:

- Devbox `ipconfig` showed two IPs:
  - `10.30.1.133` on the real network adapter (this is **private** \u2014 the
    `10.0.0.0/8` block is RFC1918, not public).
  - `172.26.144.1` on `vEthernet (Default Switch)` \u2014 Hyper-V internal
    virtual switch, only reachable from the devbox itself.
- Laptop `Test-NetConnection 10.30.1.133 -Port 8765`:
  - `SourceAddress: 100.79.200.91` via `MSFT-AzVPN-Manual` (laptop is on
    the corp Azure VPN).
  - `PingSucceeded: False`, `TcpTestSucceeded: False`.

**Conclusion:** direct inbound IP path is not viable on this devbox.
Microsoft Dev Box VMs live in a Microsoft-managed VNet that the corp
Azure VPN does not route into. No guest-OS firewall change, port change,
or config tweak can fix that. Even ICMP fails \u2014 there is no IP route at
all from laptop to devbox subnet.

### Decision

Direct-inbound TCP from laptop to devbox: **dead end**. Move to a reverse
tunnel for any future agent-based attempt.

## Reverse-tunnel recipe (next experiment)

The agent code as-is can stay; only the transport changes. Devbox dials
out (which works \u2014 RDP itself proves outbound is open) to a public
relay; laptop hits the relay's public URL.

```
[Laptop]                       [Cloudflare]                       [Devbox]
client/demo.py --HTTPS--> https://random.trycloudflare.com <--outbound HTTPS-- cloudflared
                                                                       |
                                                                       v
                                                               http://127.0.0.1:8765
                                                               (existing agent)
```

### Devbox-side, one-time

```powershell
winget install --id Cloudflare.cloudflared
```

### Devbox-side, every test session

Two terminals (both inside the Windows App session):

```powershell
# terminal 1 \u2014 the agent (unchanged)
$env:GAZE_TOKEN = "use-a-long-random-string"
python server.py --port 8765

# terminal 2 \u2014 the tunnel
cloudflared tunnel --url http://localhost:8765
```

The tunnel command prints a URL like
`https://random-words.trycloudflare.com`. Copy it.

### Laptop-side

Edit `config.ini`:

```ini
[connection]
# Use the Cloudflare URL instead of the devbox IP. Note: scheme + host only;
# do NOT include a port. Cloudflare terminates TLS on 443 and forwards to
# the agent's local 8765.
devbox_host = random-words.trycloudflare.com
devbox_port = 443
token = same-as-GAZE_TOKEN-on-devbox
```

> **Heads up:** `check_connectivity.py` and `demo.py` currently build URLs
> as `http://{host}:{port}`. To use the Cloudflare URL you need either
> (a) a tiny code change to use `https` when port is 443, or (b) point the
> client at `http://localhost:<some-port>` after running a `cloudflared
> access tcp` client on the laptop. The minimum-effort change is (a) \u2014
> a one-line scheme switch in both client scripts. Left as a follow-up
> per current decision to not change code yet.

### Caveats

- `trycloudflare.com` URLs are **anonymous and ephemeral** \u2014 fine for a
  POC, not for production. For longer-term use, register a Cloudflare
  account and create a named tunnel bound to your own subdomain.
- Anyone who guesses the random URL hits the agent. The bearer token is
  still your only auth \u2014 keep `GAZE_TOKEN` long and random, rotate often.
- Outbound HTTPS to `*.cloudflare.com` must be allowed from the devbox.
  Most corp networks allow this; a few don't.
