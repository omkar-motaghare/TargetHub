# TargetHub Security Review

**Date:** 2026-09-23
**Scope:** Full-repository in-depth security review (authentication, RBAC, Agent enrollment/credential lifecycle, provider gateway, repositories, deployment configuration, Agent installer/runtime supply chain).
**Status update (2026-10-22):** findings 1-4 are remediated with regression tests; see the Remediation table below.
**Type:** Report-only pass. No fixes were applied in this pass; see "Suggested fix" per finding for remediation guidance.

This document is a point-in-time record of the review. It should be revisited whenever authentication, RBAC, Agent credential handling, provider gateway logic, or deployment configuration changes materially.

---

## Summary

| # | Severity | File(s) | Vulnerability | Confidence |
|---|----------|---------|----------------|------------|
| 1 | 🟠 HIGH | `docker-compose.yml`, `docker-compose.team.yml` | Hardcoded/well-known fallback `SECRET_KEY` used for both JWT signing and Agent credential HMAC | 7/10 |
| 2 | 🟡 MEDIUM | `backend/app/api/v1/target_capabilities.py`, `backend/app/api/v1/targets.py` | Any authenticated user can read internal `provider_config`/`agent_id`/`resource_id` for every target | 7/10 |
| 3 | 🟡 MEDIUM | `backend/app/services/reservation_service.py`, `backend/app/repositories/reservation_repository.py` | Check-then-act race in reservation overlap validation; no DB exclusion constraint | 6/10 |
| 4 | 🟡 MEDIUM | `backend/app/web/agent/install.sh`, `backend/app/api/v1/agents.py` | Agent installer/runtime fetched via `curl \| sudo bash` and run as root with no integrity/signature verification; defaults to plaintext HTTP | 6/10 |

### Remediation status

| # | Status | Fix | Regression test |
|---|--------|-----|-----------------|
| 1 | Fixed | `Settings` rejects empty/placeholder/<32-char `SECRET_KEY` unless `ENVIRONMENT` is `development`/`dev`/`test` (default is `production`); compose files require `SECRET_KEY` | `tests/test_config_validation.py` |
| 2 | Fixed | Non-admin target/capability responses omit `provider_key`, `provider_config`, `agent_id`, `resource_id` | `tests/test_auth_rbac.py::test_non_admin_target_and_capability_responses_hide_internals` |
| 3 | Fixed | Overlap check and insert run behind a per-target write lock (row lock on Postgres, write lock on SQLite). A Postgres exclusion constraint remains a possible defense-in-depth follow-up. | `tests/test_reservation_service.py::test_concurrent_overlapping_reservations_allow_exactly_one` (SQLite serializes writers, so this test cannot prove the Postgres path) |
| 4 | Fixed | Enrollment command downloads then verifies the installer sha256; installer verifies the agent sha256, refuses `http://` without `--allow-insecure-http`, and runs the service as a dedicated `targethub` user with a hardened unit | `tests/test_installer.py` |

---

## Finding 1 — Hardcoded fallback `SECRET_KEY` (HIGH, confidence 7/10)

**Files:** `docker-compose.yml:12`, `docker-compose.team.yml:29,44`

**Problem:**
The Docker Compose deployment files ship a working fallback/hardcoded HMAC signing secret:
- `docker-compose.yml`: `SECRET_KEY: ${SECRET_KEY:-targethub-dev-only-change-me}`
- `docker-compose.team.yml`: literal `SECRET_KEY: replace-me` with no env-var override at all

`settings.secret_key` is the sole key used both for signing/verifying the custom HS256 JWT (`backend/app/services/auth_service.py` — `create_access_token`/`verify_token`) and for HMAC-hashing Agent enrollment tokens and Agent credentials (`backend/app/services/agent_service.py` — `_hash_secret`). Anyone who runs `docker compose up` (the documented quick-start path) without explicitly overriding `SECRET_KEY` gets a publicly known key baked into the compose file.

**Impact:**
Any attacker who knows this well-known default key (it is committed in this public/shared repo) can forge arbitrary JWTs with `roles: ["admin"]`, achieving full authentication bypass and admin privilege escalation, and can forge Agent HMAC credentials/enrollment tokens to impersonate lab hardware.

**Evidence:**
Verified via inspection of `docker-compose.yml`/`docker-compose.team.yml` and `auth_service.py`/`agent_service.py` showing `settings.secret_key` used directly for both JWT HMAC and Agent credential HMAC with no rotation/derivation.

**Suggested fix:**
Remove the hardcoded fallback/default value; fail startup (raise) if `SECRET_KEY` is unset or equals a known placeholder, forcing operators to supply a strong random secret.

---

## Finding 2 — Over-exposed target/capability configuration data (MEDIUM, confidence 7/10)

**Files:** `backend/app/api/v1/target_capabilities.py:35,44`, `backend/app/api/v1/targets.py:23,28`, `backend/app/schemas/target_capability.py:20-25`

**Problem:**
`GET /targets`, `GET /targets/{id}`, `GET /targets/{id}/capabilities`, and `GET /targets/{id}/capabilities/{id}` are gated only by `Depends(get_current_user)` (any authenticated user, no admin role, no reservation-ownership check), yet the returned `TargetCapabilityResponse`/`TargetResponse` include `provider_key`, `provider_config` (a free-form dict), `agent_id`, and `resource_id` for every target in the system.

The project's own architecture docs explicitly state `provider_key`/`provider_config` are meant to be "internal implementation fields... not part of the normal team-admin workflow" and that the UI should "avoid showing provider_config JSON or Linux paths" — confirming this data is not meant to be exposed to ordinary users, yet the API enforces no such restriction.

**Impact:**
Any team member with a valid TargetHub login (not just admins, not just users who have reserved that target) can enumerate internal Agent/resource identifiers, device paths, and any operator-entered `provider_config` values (which could include real hardware controller credentials such as PDU/SSH/network-device secrets for non-simulated providers) for every target in the lab.

**Evidence:**
Traced `target_capabilities.py`/`targets.py` route dependencies and `TargetCapabilityResponse` schema fields; confirmed via `backend/tests/test_auth_rbac.py` that only *write* operations on capabilities are role-tested (`test_ordinary_user_cannot_add_capability`) — read access is never restricted in code or tests.

**Suggested fix:**
Require `require_role("admin")` (or a redacted response model omitting `provider_config`/`agent_id`/`resource_id`) for capability/target read endpoints, or strip sensitive fields for non-admin callers.

---

## Finding 3 — Reservation overlap check race condition (MEDIUM, confidence 6/10)

**Files:** `backend/app/services/reservation_service.py:41-64`, `backend/app/repositories/reservation_repository.py:29-40`

**Problem:**
`create_reservation` performs a check-then-act sequence — `find_overlapping_active()` (a plain `SELECT`) followed later by `INSERT`/`COMMIT` of a new `Reservation` — with no DB-level exclusion/unique constraint on `(target_id, time-range, status=active)` and no `SELECT ... FOR UPDATE`/serializable isolation. Confirmed via Alembic migration inspection that no such constraint exists on the `reservations` table.

**Impact:**
Under the team/Postgres deployment (`docker-compose.team.yml`, default READ COMMITTED isolation), two concurrent requests for overlapping windows on the same target can both pass the overlap check before either commits, producing two simultaneously "active" reservations for the same target. Each reservation owner can then independently open a session and drive the same physical resource (e.g., the same serial console/power/debugger capability) concurrently, breaking the exclusivity guarantee the whole session-gated provider model relies on for tenant isolation — one user could observe or interfere with another user's live target session.

**Evidence:**
Verified empirically with a concurrent-thread test against `ReservationService.create_reservation`; SQLite serialized the two writers (masking the race locally), but the check-then-insert pattern and absence of any exclusion constraint mean the race is not prevented at the database level for Postgres, which is the documented multi-user "team" deployment backend.

**Suggested fix:**
Add a Postgres exclusion constraint (`EXCLUDE USING gist` on `target_id` + tstzrange) or wrap the overlap check + insert in a `SELECT ... FOR UPDATE`/serializable transaction scoped to the target.

---

## Finding 4 — Agent installer/runtime supply-chain risk (MEDIUM, confidence 6/10)

**Files:** `backend/app/web/agent/install.sh:66-70`, `backend/app/api/v1/agents.py:56-60`

**Problem:**
The generated enrollment install command (`curl -fsSL {install_url} | sudo bash -s -- ...`) and the installer itself (`curl -fsSL "${TARGETHUB_URL%/}/web/agent/targethub_agent.py" -o "$TEMP_AGENT_PATH"`) fetch and execute code as root (the systemd unit has no `User=`, so `targethub_agent.py` runs as root) with **no integrity verification** of the downloaded script — `sha256sum` is present only to derive a config filename, never to check the fetched payload against a known-good hash/signature. `TARGETHUB_PUBLIC_URL` (used to build both the install command and the in-script download URL) defaults to `http://localhost:8000` in `core/config.py`/`.env.example`, i.e., plaintext HTTP by default.

**Impact:**
If `TARGETHUB_PUBLIC_URL` is left at its insecure-by-default HTTP scheme (a very plausible operator mistake given it's the shipped default), any on-path/network attacker (or anyone who can DNS/ARP spoof the TargetHub host) can serve a modified `targethub_agent.py`, which is compiled and run as root via a systemd service with no signature check — full remote code execution as root on every enrolled lab host.

**Evidence:**
Read `install.sh` end-to-end confirming no checksum/signature comparison step exists before `mv "$TEMP_AGENT_PATH" "$AGENT_PATH"`; confirmed the unit file lacks a `User=` directive; confirmed `targethub_public_url` defaults to `http://...` in `core/config.py`.

**Suggested fix:**
Default `TARGETHUB_PUBLIC_URL` to require HTTPS (or validate the scheme and warn/refuse HTTP in production), and have the enrollment API return an expected SHA-256 of `targethub_agent.py` for the installer to verify before installing/running it.

---

## Notes

- This review was conducted against commit `282ac91` on branch `develop` (with local uncommitted changes present at review time; see `git status` for the exact working-tree state at review time).
- Findings above are prioritized by severity, then confidence. No code fixes were made in this pass — see the Phase 6 agent-hardening work already completed (installer `py_compile` validation, atomic writes, retry/backoff, credential redaction) as unrelated but complementary hardening.
- Recommended immediate action: address Finding 1 (hardcoded secret) before any shared/team deployment, since it undermines every other authentication and Agent-credential control in the system.
