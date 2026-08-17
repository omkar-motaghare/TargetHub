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

Next steps (immediate)
- Commit this roadmap to `develop`.
- Begin M0: produce a file-level diff of `app/` vs `backend/app/`, propose a minimal merge/delete plan, and update Docker references.

Notes
- Keep changes minimal and focused per milestone.
- After M0 is complete, I'll provide concrete test commands for local verification (docker compose up, sample API calls).
