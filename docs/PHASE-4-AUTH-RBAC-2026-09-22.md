# Phase 4 Authentication and RBAC Record

**Project:** TargetHub  
**Repository:** `/home/omkar_motaghare/TargetHub`  
**Date:** 2026-09-22  
**Milestone:** Phase 4 - Authentication, bootstrap, and RBAC

## Summary

Phase 4 established an explicit first-admin bootstrap policy, enforced role-based
access to administrative APIs, and made ordinary reservation/session operations
use the authenticated identity instead of trusting an arbitrary request-body
`user_id`.

Agent enrollment and heartbeat remain a separate credential flow: Agents do not
have TargetHub user accounts, and a TargetHub user bearer token cannot be used as
an Agent credential.

The phase is complete for the current product scope. The implementation is
covered by a focused 24-test authentication/RBAC suite and the broader backend,
compile, frontend, Compose, and E2E-script checks listed below.

## Policy Decisions

### First-admin bootstrap

- `POST /api/v1/auth/bootstrap` is the only unauthenticated first-admin path.
- Bootstrap is disabled when `ADMIN_BOOTSTRAP_TOKEN` is unset or empty.
- A matching bootstrap token creates the first user with the `admin` role.
- A wrong bootstrap token returns `401 Unauthorized`.
- Disabled bootstrap returns `403 Forbidden`.
- Any attempt after the first user already exists returns `409 Conflict`.
- The bootstrap token is supplied through configuration and is not hard-coded in
  the application.

After bootstrap, `POST /api/v1/auth/users` requires an authenticated administrator.
There is no unauthenticated public user-creation or self-registration endpoint.

### Status conventions

- `401 Unauthorized`: missing, malformed, invalid, expired, or wrong-kind
  credentials.
- `403 Forbidden`: valid credentials without the required role or an otherwise
  forbidden administrative operation.
- `409 Conflict`: an authenticated and authorized request conflicts with current
  state, such as one-time bootstrap or an ownership-sensitive release attempt.
- Duplicate usernames are rejected with `400 Bad Request` by the user-creation
  endpoint.

### Identity and ownership

- Target and capability administration requires the `admin` role.
- Ordinary reservation and session creation resolves the effective user from the
  authenticated user. A non-admin cannot impersonate another user by supplying
  a different `user_id` in the request body.
- Reservation and session reads enforce ownership for ordinary users.
- An administrator has an explicit, tested path to create a reservation for
  another user where administration requires it.
- Audit access is restricted to administrators.

### Agent credentials

- Agent list/detail, enrollment management, enable/disable, and credential
  revocation are administrator-only operations.
- Agent enrollment uses a short-lived, single-use enrollment token.
- Agent heartbeat requires the enrolled Agent credential and verifies that the
  credential belongs to the URL-selected Agent.
- Disabled or revoked Agent credentials cannot send heartbeats.
- User bearer tokens are rejected on the Agent heartbeat endpoint.

## Changes Implemented

- Added the first-admin bootstrap endpoint and configuration-backed
  `ADMIN_BOOTSTRAP_TOKEN` policy in the authentication API/configuration.
- Restricted user creation to authenticated administrators.
- Applied consistent authentication and role dependencies to administrative
  routes, including target/capability, Agent administration, and audit access.
- Enforced current-user identity and explicit administrator impersonation in
  reservation and session routes.
- Preserved the distinction between TargetHub user authentication and Agent
  credential authentication.
- Updated the backend README with bootstrap commands, response semantics,
  authorization boundaries, and Agent credential behavior.
- Updated `docker-compose.yml` to expose the bootstrap-token configuration path.
- Updated the backend-served dashboard to avoid making administrator-only Agent
  calls for ordinary users.
- Updated `scripts/e2e-demo.sh` to bootstrap an admin, obtain bearer tokens, and
  create subsequent users through the authenticated admin route rather than an
  unauthenticated user-creation flow.
- Added `backend/tests/test_auth_rbac.py` with the focused security matrix.

## Focused Test Coverage

The 24 tests in `backend/tests/test_auth_rbac.py` cover:

1. First-admin creation, disabled bootstrap, wrong bootstrap token, and
   one-time bootstrap behavior.
2. Missing, malformed, invalid, and expired user tokens.
3. Ordinary-user and administrator permissions for user creation.
4. Duplicate usernames.
5. Target and capability administration permissions.
6. Reservation and session ownership, including forbidden reads and release
   conflicts.
7. Protection against ordinary-user impersonation through `user_id`.
8. Explicit administrator creation of a reservation for another user.
9. Administrator-only Agent listing, reading, enrollment management, and
   enable/disable operations.
10. Agent heartbeat rejection without an Agent credential, with a user token,
    after Agent disablement, and after credential revocation.
11. Administrator-only audit access.

## Validation Results

### Narrow validation

- `python -m pytest -q tests/test_auth_rbac.py`  
  Result: **24 passed**
- `ruff check app` from `backend/`  
  Result: **pass**
- `bash -n scripts/e2e-demo.sh`  
  Result: **SYNTAX_OK**

### Broader validation

- `python -m pytest -q` from `backend/`  
  Result: **58 passed**
- `python3 -m compileall -q backend/app`  
  Result: **COMPILE_OK**
- `npm run build` from `frontend/`  
  Result: **pass**
- `docker compose config`  
  Result: **pass**, with `ADMIN_BOOTSTRAP_TOKEN` present in the configuration

## Files Changed in Phase 4

- `backend/app/api/v1/auth.py`
- `backend/app/api/v1/agents.py`
- `backend/app/api/v1/reservations.py`
- `backend/app/api/v1/sessions.py`
- `backend/app/api/dependencies.py`
- `backend/app/core/config.py`
- `backend/app/web/app.js`
- `backend/tests/test_auth_rbac.py`
- `backend/README.md`
- `docker-compose.yml`
- `scripts/e2e-demo.sh`
- `docs/PHASE-4-AUTH-RBAC-2026-09-22.md`

## Known Warnings and Remaining Risks

- FastAPI `on_event` lifecycle deprecation warnings remain.
- Starlette/httpx and `datetime.utcnow()` deprecation warnings remain.
- Docker Compose reports the existing obsolete `version` key warning.
- Authentication uses the project's existing custom PBKDF2 and HS256 token
  implementation. A future security review should confirm secret rotation,
  token revocation/rotation strategy, password policy, rate limiting, and
  production secret management.
- Agent enrollment and credentials are tested at the API boundary, but the full
  remote Agent runtime and real hardware protocol are future phases.
- Authorization coverage should be extended as new routes and providers are
  added; every new administrative or data-plane operation must declare its
  identity and role boundary.

## Next Safe Phase

Proceed to Phase 5, enforcing the complete
`Target -> Capability -> Agent -> Resource` integrity boundary before adding
real remote hardware operations.