# TargetHub Manual Verification Checklist

**Purpose:** Track manual, in-depth verification of each functionality area before treating it as
"done" — both backend/API behavior and the UI built on top of it. Existing automated tests passing
does not mean a feature is verified for real product use; use this checklist to confirm behavior,
UX, and edge cases by hand.

**How to use:** Work through each area. Mark items `[x]` when verified, and add a short note (date,
result, bug reference) next to any item that fails or is deferred. Keep this file updated as the
running source of truth for verification status — do not lose progress between sessions.

---

## 1. Authentication

- [ ] Bootstrap: first admin creation works only once / is protected (cannot silently create a
      second bootstrap admin via the same path).
- [ ] Login with correct credentials issues a token; wrong username/password fails cleanly.
- [ ] Token expiry: token actually expires (currently 15 min default) and an expired token is
      rejected with 401, not 500.
- [ ] `GET /auth/me` returns correct username + roles.
- [ ] Passwords are hashed (not stored/returned as plaintext) in the DB.
- [ ] No lockout/rate-limiting on login currently exists — confirm whether this is acceptable for
      v1 or needs to be flagged as a gap.

## 2. RBAC (roles & privileges)

> Note: today only two effective tiers exist — `admin` vs any authenticated user. No
> `operator`/`viewer`/etc. yet. Confirm this matches product intent, or flag as a gap.

- [ ] As **admin**: can create users, create/edit/delete targets & capabilities, manage agents
      (enroll/enable/disable/revoke), view audit log, force-release reservations.
- [ ] As **non-admin/regular user**: every admin-only action correctly returns 403 (test via direct
      API call, not just UI visibility).
- [ ] Regular user *can* do what they should: view targets, reserve, open/close own sessions, view
      own reservations.
- [ ] Regular user **cannot** see/act on another user's reservations or sessions (ownership check),
      except via admin override.
- [ ] Role field cannot be self-escalated by a non-admin (e.g. user edits their own roles via API).

## 3. Targets & Capabilities (admin config)

- [ ] Create/edit/delete a Target.
- [ ] Add/edit/delete a Capability under a target, bound to an `agent_id` + `resource_id`.
- [ ] Invalid/nonexistent `agent_id`/`resource_id` is rejected, not silently accepted.
- [ ] `provider_config` validation per provider type (power, network, deployment, debugger, serial)
      — test both valid and intentionally invalid configs for each.
- [ ] Non-admin users can list/view targets but do not see overly sensitive fields (previously
      flagged as a security gap — confirm what's actually exposed today).

## 4. Agents

- [ ] Enroll a new agent (via enrollment token flow) — confirm token single-use / expiry behavior.
- [ ] Agent heartbeat: "online/offline" status updates correctly on a sane timeout.
- [ ] Resource discovery: discovered resources from an agent show up and can be mapped to a
      capability.
- [ ] Disable / enable / revoke-credential actions on an agent — confirm a revoked/disabled agent
      can no longer talk to the server.
- [ ] Re-enrollment of a previously disabled/revoked agent works (documented "safe re-enrollment"
      feature — test explicitly).

## 5. Reservations

- [ ] Reserve a target for a time window; overlapping reservations are rejected — including under
      **concurrent** requests (known race-condition risk; stress-test manually).
- [ ] Release own reservation.
- [ ] Attempt to release someone else's reservation as non-admin → fails.
- [ ] Admin force-release → always succeeds, and is audited.
- [ ] Session creation is blocked outside the reserved time window.

## 6. Sessions

- [ ] Open a session bound to a capability only within an active reservation window.
- [ ] A user who doesn't own the reservation cannot open a session against it.
- [ ] Session expiry: session becomes unusable after expiry/close; provider calls fail cleanly
      afterward.
- [ ] Closing a session explicitly releases resources (agent side too, not just the DB row).

## 7. Providers / Operations

> Test simulated **and** real mode where available.

- [ ] **Serial**: open/read/write/close through an agent-backed session (the one real
      hardware-vertical-slice — prioritize this).
- [ ] **Power**: status/on/off/reset/cycle, both simulated and real-mode config; unreachable
      controller and timeout behavior.
- [ ] **Network**: info + exec, allowlist enforcement (disallowed command is rejected),
      unreachable/timeout behavior.
- [ ] **Deployment**: deploy + status; unsafe artifact paths (absolute path / `../`) are rejected;
      timeout behavior.
- [ ] **Debugger/J-Link**: attach/halt/resume/reset/detach + status; auth-missing and unreachable
      behavior.
- [ ] For every provider: operations are blocked if the session is not active/owned/expired
      (authorization boundary, not just business logic).

## 8. Audit Log

- [ ] Audit entries are created for: login, admin actions, target/capability changes, agent
      changes, reservation create/release/force-release, session open/close, provider operations.
- [ ] Only admin can read the audit log.
- [ ] Secrets/tokens/passwords never appear in audit entries or logs.

## 9. Health / Metrics

- [ ] `/health` (liveness) works even if DB/agents are down.
- [ ] `/health/ready` (readiness) correctly fails if DB is unreachable or migrations aren't
      applied.
- [ ] Metrics endpoint returns sane, bounded output (no unbounded label explosion).

## 10. Frontend (React) — functionality parity + UX

- [ ] Login/logout, token expiry → redirect to login (not a silent broken state).
- [ ] Target list/detail page renders real data (not mock).
- [ ] Admin: target/capability CRUD UI (verify what actually works vs. is a stub — some views
      previously flagged as read-only-only).
- [ ] Agent admin UI: enroll, list, enable/disable/revoke, resource visibility, online/offline
      indicator.
- [ ] Capability-to-resource mapping UI (previously flagged as not implemented — confirm).
- [ ] Reservation UI: create, list "my reservations," release, conflict error shown clearly.
- [ ] Session UI: open, see status/expiry, close.
- [ ] Operations console: execute a provider operation from the UI and see the result (previously
      flagged as not implemented — confirm).
- [ ] Audit/activity view: queries the real backend, not localStorage (previously flagged as still
      mock).
- [ ] Error states across the UI: 401, 403, 409 (conflict), agent-offline, resource-unavailable —
      each shows a clear, distinct message, not a generic crash/blank screen.
- [ ] Non-admin user never sees admin-only controls in the UI (not just blocked server-side —
      should be visually absent/disabled).
- [ ] General design pass: responsiveness, consistent components (tables/forms/dialogs),
      accessibility of controls.

## 11. Deployment / Ops

- [ ] `docker compose up` from a clean checkout — setup is actually reproducible.
- [ ] Restart containers — data persists (volumes) and DB is not wiped.
- [ ] Migrations run automatically and idempotently on startup.

---

## Notes / Findings Log

Use this section to log issues found during verification (area, description, severity, status).

| Date | Area | Finding | Severity | Status |
|------|------|---------|----------|--------|
|      |      |         |          |        |
