# Solution Approaches — RemoteGaze

## Overview

Three candidate approaches for automating manual UI testing of desktop applications running on ephemeral cloud VMs, with tests executed from a local laptop.

---

## A. Remote Agent Model

A test automation agent is installed on the VM alongside the app. Local test code sends commands to the agent over the network, and the agent interacts with the UI on the VM.

```
[Your Laptop]                    [Cloud VM]
 Test Runner  ---HTTP/REST--->   Agent (WinAppDriver/FlaUI)
              <--results------       ↕
                                 Target App (VS, VS Code)
```

### Pros

- Reliable — agent has direct access to the app's UI automation tree
- Fast — no screen rendering overhead
- Precise — can target UI elements by automation ID, not pixels

### Cons

- Agent + dependencies must be installed on every fresh VM (adds to setup time)
- WinAppDriver hasn't been actively maintained (last update ~2021)
- FlaUI doesn't have a built-in remote server — would need a thin service wrapper or PowerShell remoting/WinRM

### Best For

Native WPF/Win32 apps where precise element interaction is needed.

### Candidate Tools

- **WinAppDriver** — Microsoft's Appium-compatible driver for Windows apps
- **FlaUI** — .NET wrapper around Microsoft UI Automation, commonly used for WPF/WinForms
- **Appium + Windows Driver** — cross-platform framework with Windows desktop support

---

## B. Screen-Based / RDP Model

Connect to the VM's display via RDP or VNC and automate based on what's visually rendered — using image recognition, OCR, or pixel matching.

```
[Your Laptop]                    [Cloud VM]
 Test Runner  ---RDP/VNC---->   Desktop Session
              <--screen------       ↕
                                 Target App
```

### Pros

- Nothing to install on the VM beyond the app itself — minimal VM setup
- Works with any app regardless of UI framework
- Framework-agnostic — doesn't depend on accessibility tree support

### Cons

- Fragile — breaks when resolution, DPI, theme, or font rendering changes
- Slower — screen capture + image matching adds latency
- Harder to debug — failures are "didn't find this image" rather than "element not found"
- RDP session quirks (disconnecting minimizes windows, locking kills rendering)

### Best For

Quick automation where you can't access the UI automation tree, or as a fallback for specific hard-to-automate dialogs.

### Candidate Tools

- **SikuliX** — image-based GUI automation
- **PyAutoGUI** — Python library for screen-based automation
- **Azure Computer Vision / OCR** — for text recognition on screen captures

---

## C. Hybrid Model (Recommended)

Use the right tool for each layer. Automate VM provisioning and app install via scripts/APIs, use CLI/API calls where possible for setup and verification, and reserve UI automation only for interactions that truly require it.

```
[Your Laptop]
 Orchestrator (scripts/Terraform)
    ├── VM provisioning ---------> Cloud API (Azure/AWS)
    ├── App install + config ----> WinRM/SSH to VM
    ├── UI tests ----------------> Agent on VM (for UI-only parts)
    └── Result collection -------> Pull logs/screenshots back
```

### Pros

- Most reliable — UI tests are only used where needed, reducing flakiness
- Faster — CLI/API checks are instant compared to UI clicks
- Maintainable — if the app adds a CLI flag, you skip the UI path entirely
- VM setup is automated as a first-class concern, not an afterthought

### Cons

- More upfront design work — need to analyze each test case and decide the right layer
- Requires knowledge of the app's non-UI interfaces (CLI flags, config files, APIs)

### Best For

Long-term, production-grade test automation. This is where most mature test teams end up.

### Candidate Tools

- **Terraform / Bicep / ARM templates** — VM provisioning
- **PowerShell + WinRM** — remote VM setup and app installation
- **FlaUI / WinAppDriver** — UI automation agent on VM
- **Playwright** — if targeting Electron apps (VS Code), can connect to remote Electron process natively

---

## D. Record & Playback with Visual Regression (Team Idea)

A custom desktop app runs on the tester's local machine and mirrors the remote VM screen. The tester clicks through the app normally while the tool records every mouse/keyboard event and takes before/after screenshots. During playback, the tool replays events and compares screenshots to detect regressions.

```
[Your Laptop - Custom App]              [Cloud VM]
 ┌──────────────────────┐
 │ VM Screen Mirror      │<--RDP/VNC--- Desktop Session
 │ Record/Playback Engine│                  ↕
 │ Screenshot Comparator │              Target App
 └──────────────────────┘
```

### How It Works

1. **Recording:** User interacts with the mirrored VM screen. The app captures mouse/keyboard events and takes screenshots before and after each action.
2. **Playback:** The app replays recorded events step-by-step, taking screenshots at each step and comparing against the recorded baseline.
3. **Validation:** If a screenshot doesn't match, playback stops and reports an error. If it matches, it proceeds to the next step.

### Pros

- Low barrier to entry — testers click through the app, no code needed
- Visual comparison catches UI regressions that element-based tools miss (layout shifts, rendering bugs)
- Familiar model — similar to commercial tools (Ranorex, TestComplete)
- Test artifacts (JSON steps + screenshots) are easy to understand

### Cons & Risks (Critical)

**1. Screenshot comparison is extremely fragile**
- A 1-pixel shift, font smoothing difference, or cursor blink triggers a false failure
- Different VM hardware/GPU produces different font rendering
- Timing differences (screenshot taken 50ms too early) capture loading states
- Risk: team spends more time triaging false failures than finding real bugs

**2. Absolute mouse/keyboard coordinates break constantly**
- Recorded clicks are at (x, y) positions — if the window moves, resizes, or a dialog shifts, every subsequent step fails
- Different VM resolution or DPI scaling invalidates all coordinates
- A new toolbar button shifts everything below it

**3. No understanding of app state**
- Playback replays blindly — doesn't know if the app is loading, if a dialog appeared, or if a step failed silently
- A 2-second delay on one run vs. instant on another desyncs the playback

**4. Remote screen mirroring adds latency and artifacts**
- RDP/VNC compression introduces visual artifacts that break screenshot comparison
- Network latency means clicks may not land where expected
- RDP disconnection or session lock kills the display

**5. Tests are not maintainable at scale**
- A recorded test is a rigid sequence — one changed step in a 50-step flow requires re-recording the whole thing
- No reusable components (can't share a "log in" sequence across tests)
- JSON of mouse coordinates is hard to review or debug

**6. Screenshot storage grows fast**
- Two screenshots per step × hundreds of steps × multiple tests = GBs quickly

### Biggest Risk

This approach is a well-known pattern in test automation. It works great in demos but tends to fail in daily use. By the 10th release, many tests fail due to minor visual differences that aren't bugs, and the team stops trusting the tool.

### Improvements to Make It Viable

If the team pursues this approach, these upgrades are essential:

| Original design | Required improvement |
|----------------|---------------------|
| Record mouse (x, y) clicks | Record **what element** was clicked (by name/ID/text) + coordinates as fallback |
| Pixel-exact screenshot compare | **Region-based perceptual comparison** (SSIM/perceptual hash) with tolerance threshold |
| Blind sequential playback | **State-aware playback** — wait for expected visual state before proceeding |
| Mirror VM screen to local app | Run a **lightweight agent on the VM** that captures + relays, reducing latency artifacts |
| Flat step sequence | **Step groups / macros** for reusable sub-sequences |
| Full-page screenshots | **Regions of interest** — compare only the relevant area, not the full screen |

With these improvements, the tool evolves from "record-and-playback" into a **visual test orchestrator**, which is significantly more viable for production use.

---

## Comparison Matrix

| Criteria                    | A. Remote Agent       | B. Screen-Based       | C. Hybrid             | D. Record & Playback  |
|-----------------------------|-----------------------|-----------------------|-----------------------|-----------------------|
| VM setup complexity         | Medium (install agent)| Low (nothing extra)   | Medium (install agent)| Low (RDP only)        |
| Test reliability            | High                  | Low                   | Highest               | Low (without upgrades)|
| Maintenance effort          | Medium                | High                  | Low (long-term)       | High (re-record often)|
| Initial development effort  | Low–Medium            | Low                   | High                  | High (build the app)  |
| Works with any UI framework | No (needs UIA support)| Yes                   | Partial               | Yes                   |
| Debugging experience        | Good (element IDs)    | Poor (pixel matching) | Good                  | Medium (screenshots)  |
| Ephemeral VM friendly       | Yes (with setup script)| Yes                  | Yes (with setup script)| Yes                   |
| Tester skill required       | Medium (write code)   | Medium                | Medium–High           | Low (just click)      |

---

## Recommendation

**Target architecture: Hybrid (C) with Remote Agent (A) for the UI layer.**

### Why

1. The biggest risk isn't which UI tool you pick — it's whether the **full loop** (VM lifecycle → app install → remote execution → result collection) works smoothly
2. Many test validations (file exists, config is correct, service is running) don't need UI automation at all
3. UI automation is the most fragile part — minimizing its surface area improves reliability

### Suggested POC Scope

1. **Script VM provisioning** — create a fresh VM via cloud API
2. **Automate app install** — use WinRM/PowerShell to install the target app
3. **Run one UI test** — install a test agent, execute a single UI scenario
4. **Collect results** — pull back pass/fail status + screenshots
5. **Tear down VM**

This proves the full loop works before investing in writing hundreds of test cases.

---

## Existing Free Tools

Only free / open-source tools are considered. The team can evaluate these for the POC.

### Desktop UI Automation

| Tool | Strengths | Notes |
|------|-----------|-------|
| **FlaUI** | .NET, actively maintained, precise WPF/WinForms/Win32 automation | Needs a remote wrapper for VM setup |
| **WinAppDriver** | Appium-compatible, WPF/Win32, CI/CD friendly | Not actively maintained since ~2021 |
| **AutoIt** | Simple scripting, works with any Windows GUI | Good for setup scripts, less for full test suites |

### Image-Based / Visual Automation

| Tool | Strengths | Notes |
|------|-----------|-------|
| **SikuliX** | Open-source image recognition, works with any visible UI | Cross-platform, no element selectors needed |
| **PyAutoGUI** | Python library for screen-based mouse/keyboard automation | Lightweight, pairs well with image comparison libraries |

### Test Frameworks (to pair with above)

| Tool | Strengths | Notes |
|------|-----------|-------|
| **Robot Framework** | Keyword-driven, human-readable tests, plugins for Appium/FlaUI/SikuliX | Good for team collaboration |
| **Playwright** | Excellent for Electron apps (VS Code), built-in remote connection | Free, Microsoft-backed, very active |

### Recommended Free Stack

For your scenario (ephemeral VM + remote testing + desktop apps), the strongest free combination is:

1. **FlaUI** (or WinAppDriver) — UI automation agent running on the VM
2. **PowerShell + WinRM** — VM setup, app installation, agent deployment
3. **Robot Framework** — test orchestration with readable test cases
4. **Playwright** — if any target apps are Electron-based (e.g., VS Code)
5. **SikuliX** — fallback for UI elements that don't expose accessibility info
