Project Roadmap
===============

This document records the development milestones to bring the repository from its current state to full feature-complete, production-ready status. Work will be tracked on the `develop` branch.

Milestones
----------

M0 — Repository hygiene (priority: high)
- Goal: Reconcile duplicate `app/` trees and make `backend/app/` canonical for runtime.
- Tasks:
  - Diff `app/` (repo root) vs `backend/app/` and list unique/modified files.
  - Merge any unique, useful files from root `app/` into `backend/app/`.
  - Remove or archive the redundant root `app/` tree.
  - Update `backend/Dockerfile` and `docker-compose.yml` to reference `backend/app/` consistently.
- Status: **Complete (2026-09-22)**
- Result: The root `app/` tree was audited and contained no files or active runtime references. It was preserved as `archive/app-root-legacy/`. `backend/app/` remains the canonical runtime tree.
- Docker already builds from `./backend`, and the API/worker entrypoints already import the canonical `app` package from that build context. No runtime configuration change was necessary.
- Acceptance: Single canonical `backend/app/` used by Docker build; no functional regressions in API routes.

M1 — Authentication & RBAC
- Goal: Add user authentication and role-based access control to protect admin endpoints.
- Tasks: implement token-based auth, role claims, protect services and API routes, add tests.
- Acceptance: Admin operations require appropriate role; test coverage for auth flows.

M2 — Session enforcement and provider gating
- Goal: Enforce session ownership/time gating for provider data-plane operations.
- Tasks: add session lifecycle checks to providers; restrict provider operations to active sessions; add provider-level audit logs.
- Acceptance: Providers reject operations outside session ownership/window; integration tests pass.

M3 — Provider ecosystem and debugging UX
- Goal: Add more provider implementations and a debugging/inspector UI for providers and sessions.
- Tasks: implement at least one additional provider; add provider debug endpoints and UI pages.
- Acceptance: New provider works end-to-end; UI shows provider/session state.

M4 — Observability and monitoring
- Goal: Add metrics, structured logging, and health checks for runtime and providers.
- Tasks: instrument key services, expose Prometheus metrics, add Grafana dashboards (optional).
- Acceptance: Metrics available and basic dashboards show health and usage.

M5 — Hardening, CI/CD, release
- Goal: Tests, CI, packaging, and release process.
- Tasks: Add unit/integration tests, CI pipeline (lint, tests, build), Docker image tagging and release notes.
- Acceptance: CI passing; reproducible Docker image build and published artifact pipeline.

Status update (2026-10-22, v0.1.0)
----------------------------------
- M1 Auth/RBAC, M2 session gating: done and covered by backend tests.
- M3 UI/provider ecosystem: React UI with serial terminal, power/deploy panels, admin pages; GPIO power and deploy providers via the agent. Done on a dev host (no real hardware).
- M4 Observability: request-id logs, `/metrics`, health endpoints, audit filters, backup/restore, TLS overlay. Done. Grafana dashboards not provided.
- M5 Hardening/release: CI workflow written (not yet run on GitHub); local tag v0.1.0. Docker image publishing is not set up.
- Post-0.1 work: real Raspberry Pi validation, upgrade-migration test on real data, react-router v7 / vitest upgrades, Postgres exclusion constraint for reservations, user token revocation, hide agent/resource ids from session owners.

Next steps (historical, superseded by the update above)
- Begin M1/M2 revalidation after the backend dependency environment is available.
- Establish reproducible local test setup before relying on backend test results; the Phase 0 audit found SQLAlchemy missing from the current environment.

Notes
- Keep changes minimal and focused per milestone.
- M0 was completed as an archival change because no unique root application files needed migration.
- Before treating M1 or M2 as complete, run the backend tests in a clean environment and verify the API routes manually.
