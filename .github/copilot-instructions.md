# Copilot Instructions — RemoteGaze

## Project Purpose

RemoteGaze is an automated UI testing framework that remotely observes and interacts with desktop applications (e.g., Microsoft Visual Studio, VS Code). The goal is to replace repetitive human testing of buttons, menus, dialogs, and workflows that must be re-verified with every release.

## Current Status

**Pre-development / brainstorming phase.** The tech stack and architecture have not been finalized. The team is evaluating approaches for automated UI testing of desktop applications on Windows.

## Architecture

Tests run **remotely**: the target application runs on a cloud VM, while tests are executed from a developer's local laptop.

### Current Manual Workflow (What We're Automating)

Every release cycle, a tester repeats this loop:

1. New app version is released
2. Provision a **fresh, clean VM** (no state carried over from previous versions)
3. Install the new version of the app on the VM
4. Run all UI tests manually on the VM
5. Record and report results
6. Tear down — next release starts from step 1 again

**Key implication:** The VM is ephemeral. Any test infrastructure (agents, drivers, dependencies) must be installed as part of setup every time, or baked into a VM image.

### Architecture Constraints

- The test framework must support **remote connections** to the VM (e.g., via RDP, WinRM, SSH tunnel, or a remote automation agent)
- Tests cannot assume the app is running on the same machine as the test runner
- **VM setup + app install must be automated** — this is as important as the tests themselves
- Network latency and connection reliability are factors in test design (timeouts, retries, wait strategies)
- The solution should cover the **full loop**: VM provisioning → app installation → test execution → result reporting → teardown
- **ARM platform VMs require special permission** to use and connect — request access ahead of time

## Decision Context

When helping with this project, keep these constraints in mind:

- **Target applications** are Windows desktop apps (WPF, Electron-based, Win32) running on **ephemeral cloud VMs** (fresh VM per release)
- **Test execution** happens from a local developer laptop connecting to the remote VM
- **VM setup is part of the problem** — provisioning, app installation, and test infra setup must all be automated
- **Test scope** covers UI interactions: clicking buttons, navigating menus, filling forms, verifying visual state
- **Tests must run repeatedly** against new builds/releases — reliability and maintainability matter more than speed of initial authoring
- **The team is non-trivial** — solutions should support collaboration (clear test organization, readable test code, version control friendly)

## Candidate Technologies (Under Evaluation)

These are being considered during brainstorming — none are chosen yet:

- **Playwright** — strong for Electron apps (VS Code), web-based UIs
- **WinAppDriver / Appium** — for native Windows desktop apps (WPF, Win32)
- **Microsoft UI Automation (UIA)** — low-level Windows accessibility framework
- **FlaUI** — .NET wrapper around UIA, commonly used for WPF/WinForms testing
- **Accessibility Insights** — for inspecting UI automation trees

## Conventions (To Be Established)

Once the tech stack is decided, update this file with:

1. Build, test, and lint commands (including how to run a single test)
2. Project structure and architecture
3. Test naming and organization conventions
4. Environment setup requirements (e.g., target app installation, driver setup)
5. CI/CD integration patterns
