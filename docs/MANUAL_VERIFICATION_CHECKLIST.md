# TargetHub manual verification checklist (0.2.0)

**Purpose:** confirm by hand, on real infrastructure, what automated tests and simulators cannot. Mark
items `[x]` when verified and log anything that fails in the findings table at the end, with the date.

**What automation already covers (Linux dev host, simulators):** ~250 backend tests (API, auth, roles,
reservations, waitlist, scheduler, DD driver against the mock, agent runtime with a pty serial device,
migrations up/down, installers incl. PowerShell under pwsh), a live server + real agent end-to-end run,
Playwright browser smoke, and the simulated demo lab (`tools/verify_demo_lab.py`) passing in production
mode. **Never exercised:** real DD hardware, a real Raspberry Pi relay, a Windows agent on Windows, a real
board, the Docker image on your hosts, HTTPS certificates.

Suggested order: A (server) → B (users) → C (DD) → D (Pi agent) → E (Windows agent) → F (daily use) → G (ops).
CLI/SDK and VS Code (section H) come after the server and agents are verified.

---

## A. Server installation

- [ ] Linux: `scripts/install.sh` on a clean host → healthy stack, URL and bootstrap token printed.
- [ ] Windows: `scripts\install.ps1` with Docker Desktop → healthy stack; `.env` readable only by you
      (`icacls .env`).
- [ ] Optional: `--image ghcr.io/…/targethub:0.2.0` after the first release workflow run (amd64 and arm64).
- [ ] First admin created with the bootstrap token; token rejected afterwards.
- [ ] `docker compose restart` and a host reboot → data survives, users stay signed in or can sign in again.
- [ ] Optional: `--domain` with a public DNS name → valid certificate, http redirects to https,
      `/metrics` returns 404 publicly.
- [ ] Upgrade from your 0.1.0 install following [upgrade notes](operations/upgrade.md#010--020-upgrade-notes)
      (volume copy) → old users, targets and history present.

## B. Accounts and roles

- [ ] Create one user of each role (admin, user, viewer). Viewer sees targets/calendar but no reserve buttons;
      direct API calls as viewer to reserve return 403.
- [ ] User cannot open admin pages or call admin APIs (403), cannot see `provider_config`/agent IDs.
- [ ] Wrong password 5× → "Too many failed attempts"; works again after the window.
- [ ] Disable a signed-in user → their next request fails within seconds; re-enable works.
- [ ] Reset password from Admin → Users; `scripts/reset_admin_user.sh reset <admin>` on the server console.
- [ ] Account → create API token; `curl -H "Authorization: Bearer thp_…" <url>/api/v1/auth/me` works; revoke → 401.
- [ ] Leave a tab open > 15 min, then act → it keeps working (silent refresh); "Sign out everywhere" logs
      out a second browser.

## C. DD power system (real hardware)

Prerequisite: `TARGETHUB_DD_API_KEY` in `.env`, `docker compose up -d`.

- [ ] Server container reaches DD: Admin → Targets → add **Power / DD power system (server)** with your hub
      MAC, node, endpoint → save accepted.
- [ ] Reserve → open power session → **Status** matches the DD dashboard (state, endpoint name, node connected).
- [ ] **Power on** / **Power off** → relay switches; result says *confirmed*; the time to confirm is acceptable
      (adjust *Confirm timeout* if needed).
- [ ] **Power cycle** and **Reset** → OFF, pause (cycle off-time), ON; board reboots.
- [ ] Wrong API key → "DD API key is missing or was rejected" (no stack trace, key never shown anywhere).
- [ ] Wrong node/endpoint → 404 message; wrong MAC → 400/404 message.
- [ ] Emergency lock active on DD → "emergency lock" message; nothing switches.
- [ ] Node disconnected → "accepted; device has not confirmed yet" (not a false success).
- [ ] Two targets on different endpoints of the same node do not affect each other.
- [ ] A target with only DD power (no agent anywhere) works end to end: the power-and-reservations setup.
- [ ] Record any field-name or status-code differences from the API reference in the findings table.

## D. Raspberry Pi agent (Linux)

- [ ] Admin → Agents → enrollment → Linux command on the Pi → agent online within ~15 s; platform and version shown.
- [ ] USB-serial adapter appears under resources (by-id path). Map it to a target's serial capability.
- [ ] Console: boot log visible, typing works, special keys (Ctrl+C, arrows) reach the board, paste works.
- [ ] Leave the console, let the board print, come back → buffered output appears.
- [ ] Download transcript → contains input and output.
- [ ] Relay HAT via `gpiod` config → on/off/cycle switch the relay; `active_low` correct.
- [ ] Deploy with your real flashing tool (`st-flash`, `openocd`, `esptool`, …) → board runs the new firmware;
      wrong SHA-256 → refused before flashing.
- [ ] Unplug the adapter during a session → clear error; replug → reopen works.
- [ ] Reboot the Pi → agent returns online; stop it (`systemctl stop`) → offline within ~45 s and an
      `agent.offline` webhook/notification arrives; start → `agent.online`.
- [ ] Session/reservation end → serial port is released on the Pi (another tool can open it).

## E. Windows agent

- [ ] Python 3.10+ installed for all users; elevated PowerShell → Windows enrollment command → scheduled task
      "TargetHub Agent …" running as SYSTEM; log file written.
- [ ] COM ports listed as resources; console works with a real USB-serial board (baud rate correct).
- [ ] Deploy with a Windows flashing tool (full path to the `.exe` in the agent config).
- [ ] Reboot Windows → agent starts without anyone logging in.
- [ ] Config file ACL: a normal user cannot read `C:\ProgramData\TargetHub\agent\*.json`.

## F. Daily use

- [ ] Reserve now and reserve later (start time); overlapping reservation by a second user is refused.
- [ ] Two users click **Reserve** on the same free board at the same moment → exactly one wins.
- [ ] Busy board → **Join waitlist** as user 2 → user 1 releases → user 2 gets the reservation and a notification.
- [ ] **Reserve any** with a tag picks a free board; with all busy, waitlist by tag works.
- [ ] Extend within policy; extend beyond max duration refused; with someone waiting, extend refused
      (unless the policy allows it).
- [ ] "Ending soon" notification arrives; at the end time the session closes and the board frees up.
- [ ] Policy changes (max duration, per-user limit) take effect immediately.
- [ ] Maintenance mode with a reason → users see it, cannot reserve; back to available.
- [ ] Admin force release → owner notified, waitlist advances, audited.
- [ ] Slack and/or Teams webhook: **Send test**, then real events arrive with a working link; generic webhook
      signature verifies with your secret.
- [ ] Calendar shows everyone's bookings in local time.
- [ ] Mobile/tablet browser: targets, reservations and console usable.

## G. Operations

- [ ] `scripts/backup.sh backups/` → restore into a staging copy with `scripts/restore.sh --yes …` → data intact.
- [ ] `/metrics` with `METRICS_TOKEN` scraped by your Prometheus.
- [ ] `docker compose logs api` shows request IDs; no passwords, tokens or DD keys in logs.
- [ ] Audit log shows sign-ins, admin changes, reservations and power operations with the right users.
- [ ] Load sanity: 10+ users browsing and 3+ consoles open at once stay responsive.

## H. Later: CLI/SDK and VS Code extension

Deferred until A to G pass.

- [ ] CLI: `targethub login`, `reserve --tag … --wait`, `open`, `power`, `serial --expect`, `console`, `log`, `release`.
- [ ] CI example from [CLI, SDK and CI](automation/ci-hil.md) on a self-hosted runner.
- [ ] VS Code extension (`npm run package` → install the .vsix): sign in with an API token, reserve, open console, release.

---

## Findings log

| Date | Area | Finding | Severity | Status |
|------|------|---------|----------|--------|
|      |      |         |          |        |
