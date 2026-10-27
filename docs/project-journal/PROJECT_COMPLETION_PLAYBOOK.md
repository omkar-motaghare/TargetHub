# TargetHub Production Completion Playbook

**Purpose:** Single source of truth for completing TargetHub from its current working prototype to a shareable, supportable production release.

**Repository:** `/home/omkar_motaghare/TargetHub`

**Last reviewed:** 2026-09-28

**How to use this document:** Execute the phases in order. Give one phase prompt at a time to an AI coding agent. Do not ask an agent to implement several unrelated phases in one request. After every phase, review the agent report and run the listed validation commands before continuing.

---

## 0. Execution History

This playbook is the working plan. Dated phase notes capture what was actually completed and validated at each step.

- [Phase 0 Baseline Audit](PHASE-0-BASELINE-AUDIT-2026-09-22.md)
- [Phase 1 M0 Canonical Runtime Record](PHASE-1-M0-CANONICAL-RUNTIME-2026-09-22.md)
- [Phase 2 Setup Reproducibility Record](PHASE-2-SETUP-REPRODUCIBILITY-2026-09-22.md)
- [Phase 3 Database Lifecycle Record](PHASE-3-DATABASE-LIFECYCLE-2026-09-22.md)
- [Phase 4 Authentication and RBAC Record](PHASE-4-AUTH-RBAC-2026-09-22.md)
- [Phase 5 Target Capability Agent Resource Integrity Record](PHASE-5-TARGET-CAPABILITY-AGENT-RESOURCE-INTEGRITY-2026-09-22.md)
- [Phase 6 Agent Runtime and Enrollment Record](PHASE-6-AGENT-RUNTIME-ENROLLMENT-2026-09-28.md)
- [Phase 7 Agent-Backed Serial Vertical Slice Record](PHASE-7-AGENT-BACKED-SERIAL-VERTICAL-SLICE-2026-09-28.md)
- [Phase 8 Real Provider Adapters Record](PHASE-8-REAL-PROVIDER-ADAPTERS-2026-09-28.md)
- [Phase 10 React Frontend Decision and Migration Gate](PHASE-10-REACT-FRONTEND-DECISION-2026-09-28.md)

Current milestone status:

- Phase 0: complete
- Phase 1 / M0: complete
- Phase 2: complete
- Phase 3: complete
- Phase 4: complete
- Phase 5: complete
- Phase 6: complete
- Phase 7: complete
- Phase 8: complete
- Phase 10: complete

---

## 1. Product Goal

TargetHub is an embedded-lab orchestration platform. A production release must allow a team to:

1. Install TargetHub with Docker.
2. Create users and administer roles securely.
3. Register TargetHub Agents on Linux hosts near laboratory hardware.
4. Discover physical resources through Agents.
5. Create logical Targets and map capabilities to Agent resources.
6. Reserve a Target for a time window.
7. Open an authorized Session for a configured capability.
8. Operate hardware through a session-bound provider.
9. Release access without interfering with another user.
10. Review audit history and operational health.
11. Upgrade, back up, restore, and troubleshoot the installation.
12. Consume the API through a CLI, SDK, and later a VS Code extension.

The production architecture is:

```text
User / Admin / CLI / SDK / VS Code
              |
              v
       TargetHub API + Web UI
              |
       Auth, RBAC, Audit, Metrics
              |
   Target -> Capability -> Agent -> Resource
              |
          TargetHub Agent
              |
       Serial / Power / Network /
       Debugger / Deployment hardware
```

The server must own logical resources and authorization. The Agent must own access to physical resources. A server-local device path must never be assumed for a remote Agent.

---

## 2. Current Baseline

This baseline was established from the repository documentation and implementation.

### Present

- FastAPI backend under `backend/app`.
- SQLAlchemy models and Alembic migrations.
- Target and capability management.
- Reservation and session services.
- Token authentication and initial RBAC.
- Agent enrollment, credential rotation/revocation, heartbeat, and resource reporting.
- Session-gated provider gateway.
- Serial provider with simulated fallback.
- Simulated power, network, debugger, and deployment providers.
- Audit API and metrics/health endpoints.
- Backend-served dashboard at `/dashboard`.
- Docker Compose deployment.
- Basic CI workflow.
- Backend unit tests and frontend production build.

### Incomplete or risky

- The root `app/` tree exists beside `backend/app`; `backend/app` is intended to be canonical.
- Local backend tests previously failed before assertions because dependencies were unavailable, and earlier invocation also exposed import-context problems. The test environment must be made reproducible.
- The React frontend is experimental and still uses mock/localStorage behavior.
- Several providers are simulated rather than connected to real hardware or external services.
- Agent resource discovery exists, but the complete server-to-agent operation path is not yet a production hardware-control boundary.
- The mapping between `agent_id`, `resource_id`, provider configuration, and runtime provider execution needs end-to-end enforcement.
- Authentication/RBAC has a documented bootstrap policy, role boundaries, identity enforcement, and a focused security test matrix; the remaining remote Agent and hardware boundary work is scheduled for later phases.
- CLI, SDK, and VS Code integration are not complete.
- Audit, migrations, backups, observability, deployment upgrades, and release procedures need production validation.
- `backend/README.md` and `docs/tasks/TH-003-configuration-management.md` need useful content.
- `mkdocs.yml` is only a starter configuration.
- The working tree contains uncommitted and untracked development work. Agents must preserve it.

### Known successful checks

- Backend source compilation succeeded with `python3 -m compileall -q backend/app`.
- Frontend `npm run build` succeeded.
- Backend tests could not be considered reliable until dependencies and import configuration are fixed.

---

## 3. Agent Working Rules

Paste this block before every phase prompt.

```text
You are working in /home/omkar_motaghare/TargetHub.

This repository may contain user changes, modified files, and untracked files. Preserve them. Do not use git reset, git checkout, git clean, or destructive cleanup. Do not commit or create branches unless explicitly requested.

Read the relevant existing code, tests, migrations, and documentation before editing. Keep changes scoped to this phase. Follow existing project patterns. Do not replace working behavior with a new framework without a concrete reason.

After editing:
1. Run the narrowest relevant validation first.
2. Run broader validation required by the phase.
3. Report files changed, behavior implemented, commands run, results, and remaining risks.
4. Stop if a migration, security decision, or destructive data change needs product-owner approval; explain the decision needed.
```

### Agent handoff rules

- One phase, one owner, one acceptance report.
- Agents may discover additional work, but they should not silently expand the phase.
- A failed test is not complete until the failure is classified as code, environment, test defect, or expected limitation.
- Never mark a simulated provider as production-ready without a real adapter or an explicit deferred-product decision.
- Keep provider authorization in the server/session boundary. Do not duplicate authorization rules in each client.
- Never print tokens, passwords, private keys, or full provider credentials in logs or reports.

---

## 4. Model Selection Guide

Use the least expensive model that can safely handle the work.

| Work | Preferred model | Escalate when |
|---|---|---|
| File inventory, docs, small test additions | Claude Haiku 4.5, Gemini Flash, GPT-5.4 mini, MAL-Code-1.1-Flash | The task changes architecture or security |
| Small isolated Python/TypeScript fix | GPT-5.4 mini, MAL-Code-1.1-Flash | More than three modules or unclear behavior |
| Backend service or migration work | GPT-5.3-Codex | Cross-module authorization or data migration risk appears |
| Authentication, RBAC, credential lifecycle | Claude Sonnet 5 or GPT-5.5 | Final threat-model review: Claude Opus or GPT-6 Astra |
| Agent protocol and real hardware path | GPT-5.3-Codex | Security/protocol design review: Claude Sonnet 5 |
| Dashboard/API integration | GPT-5.3-Codex | Broad UX or architecture decisions are needed |
| Documentation and release checklists | Claude Haiku 4.5 or GPT-5.4 mini | The docs contradict implementation materially |
| Final production/security review | GPT-5.5 or Claude Sonnet 5 | Use Claude Opus or GPT-6 Astra only for high-risk unresolved issues |

Recommended default: **Auto** for discovery, **GPT-5.4 mini** for small scoped work, and **GPT-5.3-Codex** for multi-file implementation.

---

## 5. Phase 0 - Establish a Reproducible Baseline

**Goal:** Know exactly what passes before modifying product behavior.

**Recommended model:** Claude Haiku 4.5, Gemini Flash, GPT-5.4 mini, or Auto.

**Prompt:**

```text
Perform a read-only baseline audit of /home/omkar_motaghare/TargetHub.

Inspect the README, roadmap, architecture documents, backend configuration, Docker Compose files, backend tests, frontend package files, scripts, plugins, CLI, SDK, and VS Code extension directories.

Record git status and recent commits, but preserve all user changes.

Run these checks where dependencies are available:
- python3 --version
- node --version
- cd backend && python3 -m pytest -q
- cd frontend && npm run build
- cd /home/omkar_motaghare/TargetHub && python3 -m compileall -q backend/app

Do not edit files. Report:
- implemented capabilities;
- partial or simulated capabilities;
- missing capabilities;
- test/build failures and whether each is environment or code;
- duplicate or legacy runtime trees;
- the smallest next phase that can be executed safely.
```

**Exit criteria:** Baseline report exists, current tests/build status is known, and no agent is asked to work from an unverified assumption.

---

## 6. Phase 1 - Repository Hygiene and Canonical Runtime

**Goal:** Make `backend/app` the unambiguous runtime application.

**Recommended model:** GPT-5.4 mini or MAL-Code-1.1-Flash.

**Prompt:**

```text
Implement roadmap milestone M0 for TargetHub.

Compare the root app/ tree with backend/app/ file by file. Identify unique functionality, references, imports, Docker references, scripts, and documentation references before changing anything. Treat archive/ as historical unless active code references it.

Make backend/app the canonical runtime tree. Preserve any unique useful functionality by moving or integrating it into backend/app before archiving redundant files. Update Docker, scripts, imports, and documentation as needed.

Do not delete files solely because they look duplicated. Do not destroy user changes. Do not change product behavior unless required to establish the canonical runtime.

Acceptance criteria:
- Docker and local commands consistently use backend/app.
- Runtime imports do not depend on the root app/ tree.
- Duplicate application code is archived or removed only after reference checks.
- `python3 -m compileall -q backend/app` passes.
- Backend tests can collect in the documented environment.
- Docker Compose configuration remains valid.
```

**Validation:**

```bash
cd /home/omkar_motaghare/TargetHub
python3 -m compileall -q backend/app
python3 -m pytest -q backend/tests
```

**Exit criteria:** One canonical runtime tree and documented commands.

---

## 7. Phase 2 - Reproducible Python, Node, and CI Setup

**Goal:** Remove environment ambiguity before deeper implementation.

**Recommended model:** GPT-5.4 mini or MAL-Code-1.1-Flash.

**Prompt:**

```text
Make TargetHub's development and CI setup reproducible.

Inspect backend/pyproject.toml, backend/requirements.txt, CI workflow files, backend/tests, frontend/package.json, package lock files, Dockerfiles, and scripts/e2e-demo.sh.

Fix only setup and test-execution issues in this phase:
- keep dependency declarations consistent;
- make pytest import backend/app reliably from the documented command;
- use Python 3.12 consistently;
- remove hard-coded absolute virtual-environment paths from scripts;
- document installation and validation commands;
- make CI run the same meaningful checks developers run locally;
- keep frontend build validation.

Do not change domain behavior unless required for test execution. Do not hide failing tests with skips.

Acceptance criteria:
- A clean Python 3.12 environment can install backend dependencies.
- `cd backend && python -m pytest -q` collects tests.
- CI runs lint and tests from the same supported context.
- `python -m compileall -q app` succeeds.
- `cd frontend && npm run build` succeeds.
```

**Validation:**

```bash
cd backend
python3 -m pip install -r requirements.txt
python3 -m pytest -q
python3 -m compileall -q app
cd ../frontend
npm ci
npm run build
```

**Exit criteria:** Test failures represent product defects rather than missing packages or import context.

---

## 8. Phase 3 - Database and Migration Baseline

**Goal:** Ensure a new installation and an existing installation can reach the same schema.

**Recommended model:** GPT-5.3-Codex.

**Prompt:**

```text
Audit and harden TargetHub's database lifecycle.

Inspect backend/alembic.ini, backend/alembic/env.py, every migration in backend/alembic/versions, database models, Docker startup, and current development database handling.

Verify migration order, multiple heads, merge migrations, foreign keys, indexes, uniqueness constraints, nullable fields, timestamps, and downgrade behavior where supported.

Implement only necessary fixes. Do not delete a migration already used by a database. If a migration is unsafe to alter, create a follow-up migration and explain why.

Add automated checks for:
- applying migrations to an empty temporary database;
- checking the final revision;
- creating representative users, targets, capabilities, agents, reservations, sessions, and audit records;
- upgrading an existing schema if a fixture is available.

Document backup and migration commands. Do not include database files or secrets in source control.
```

**Validation:**

```bash
cd backend
alembic upgrade head
alembic current
python3 -m pytest -q
```

**Exit criteria:** Fresh and upgraded databases reach the same expected schema, with a documented backup-before-upgrade procedure.

---

## 9. Phase 4 - Authentication, Bootstrap, and RBAC

**Goal:** Make identity and authorization safe enough for team use.

**Recommended model:** Claude Sonnet 5 or GPT-5.5.

**Prompt:**

```text
Harden TargetHub authentication and RBAC.

Inspect backend/app/api/v1/auth.py, backend/app/api/dependencies.py, auth_service.py, user models, migrations, every API router, dashboard authentication behavior, and the e2e script.

Define and implement an explicit first-admin bootstrap policy. After bootstrap, user creation must require an administrator or an explicitly documented one-time setup mode. Do not leave an unauthenticated public user-creation endpoint without a deliberate security rationale.

Ensure authenticated identity, not an arbitrary request-body user_id, controls ordinary user actions. Preserve an explicit, tested administrator path for administering another user where the product requires it.

Protect user management, target/capability administration, agent administration, audit access, and operational endpoints appropriately. Use consistent 401 versus 403 behavior.

Add tests for:
- missing, malformed, invalid, and expired tokens;
- ordinary user versus admin permissions;
- target and capability ownership/administration;
- reservation and session ownership;
- user bootstrap and duplicate users;
- disabled or revoked credentials.

Do not weaken authorization to make a script pass. Update scripts and documentation to follow the final policy.
```

**Validation:**

```bash
cd backend
python3 -m pytest -q
ruff check app
```

**Exit criteria:** A threat-model review can explain who may perform every administrative and data-plane operation.

---

## 10. Phase 5 - Target, Capability, Agent, and Resource Integrity

**Goal:** Enforce the architecture's `Target -> Capability -> Agent -> Resource` model.

**Recommended model:** GPT-5.3-Codex.

**Prompt:**

```text
Complete TargetHub's agent/resource integration boundary.

Inspect target and capability models, schemas, repositories, API routes, agent models/services/routes, heartbeat handling, session_service.py, provider_gateway.py, providers/registry.py, migrations, dashboard code, and tests.

Implement validation rules:
- selected agent exists and is enabled;
- selected resource belongs to that agent;
- resource type is compatible with capability type;
- disabled, revoked, offline, or unavailable resources are handled explicitly;
- capability configuration preserves agent_id and resource_id;
- sessions resolve the configured agent/resource rather than relying only on provider_key;
- deleting or disabling an agent cannot silently leave an active unusable capability.

Add focused unit and service tests for valid mappings, invalid mappings, stale heartbeats, unavailable resources, disabled agents, and session creation against configured capabilities.

Do not implement real physical hardware control in this phase. Establish the correct identity and authorization boundary first.
```

**Validation:**

```bash
cd backend
python3 -m pytest -q tests/test_agent_enrollment.py tests/test_session_service.py
python3 -m pytest -q
```

**Exit criteria:** The backend cannot create an invalid capability-to-resource mapping or authorize a session against one.

---

## 11. Phase 6 - Agent Runtime and Enrollment Production Hardening

**Goal:** Make remote Linux Agent enrollment operationally reliable.

**Recommended model:** GPT-5.3-Codex; security review with Claude Sonnet 5.

**Prompt:**

```text
Harden TargetHub Agent enrollment and runtime without changing the intended workflow.

Inspect backend/app/web/agent/targethub_agent.py, the installer, systemd service generation, agent API routes/services, credential hashing, heartbeat handling, agent operations documentation, and tests.

Verify and improve:
- one-time enrollment token expiry and hashing;
- persistent credential storage permissions;
- credential revocation and re-enrollment;
- disabled/offline/reconnected state transitions;
- heartbeat timeout behavior;
- safe retry and timeout behavior;
- atomic configuration writes;
- stable resource identifiers;
- multiple Agent instances on one Linux host;
- installer validation and failure cleanup;
- logs that do not expose credentials.

Add tests for token replay, expiry, revocation, disable/enable, reconnect, malformed heartbeat resources, and stale agents. Add a fake HTTP server test for the dependency-free runtime where practical.

Do not add arbitrary remote shell execution. Preserve Linux-only support unless a separate design is approved.
```

**Validation:**

```bash
cd backend
python3 -m pytest -q tests/test_agent_enrollment.py
python3 -m pytest -q
```

**Exit criteria:** A remote Linux Agent can enroll, restart, reconnect, report resources, and be revoked without credential leakage.

---

## 12. Phase 7 - First Real Hardware Vertical Slice: Agent-Backed Serial

**Goal:** Deliver one real end-to-end hardware capability safely.

**Recommended model:** GPT-5.3-Codex; design review with Claude Sonnet 5.

**Prompt:**

```text
Implement the first real Agent-backed hardware path for serial access.

The Agent owns the physical serial resource. The server must not assume a server-local /dev/tty device for a remote Agent.

Inspect the provider interface, serial provider, provider gateway, session authorization, capability mapping, Agent runtime, heartbeat resource model, and dashboard/API flow.

Design and implement a narrow authenticated operation protocol. The Agent may poll for work or expose an authenticated operation channel, but choose one approach and document it before coding.

Requirements:
- operations require an active, unexpired, owned TargetHub session;
- the session capability must be serial;
- agent_id and resource_id must match the configured capability;
- Agent authentication is required;
- operations are limited to an explicit allowlist such as open/read/write/close;
- arbitrary shell execution is impossible;
- serial device access happens only on the Agent host;
- disconnects and offline Agents return clear errors;
- simulated serial mode remains available for development;
- real serial tests use fake transports and do not require hardware.

Add service, protocol, and integration tests. Add one manual Linux test with a real serial device and document it.
```

**Validation:**

```bash
cd backend
python3 -m pytest -q
```

Then run the documented fake-Agent integration test and manual hardware test if hardware is available.

**Exit criteria:** A user can reserve a target, open a session, operate a real serial resource on a remote Agent, close the session, and lose access after expiry or release.

---

## 13. Phase 8 - Real Provider Adapters

**Goal:** Replace simulations one provider at a time while preserving the generic gateway.

**Recommended model:** GPT-5.4 mini for an isolated adapter; GPT-5.3-Codex for gateway integration.

Use this prompt separately for Power, Network, Deployment, and Debugger:

```text
Implement the real [POWER / NETWORK / DEPLOYMENT / DEBUGGER] provider adapter for TargetHub.

First inspect the existing provider interface, registry, gateway, session authorization, capability configuration, tests, and current simulated provider. Preserve generic session authorization and the simulated provider mode.

Add a real adapter behind explicit, validated provider configuration. Define connection timeouts and failure behavior. Normalize results through ProviderOperationResult. Do not log passwords, tokens, private keys, or full sensitive configuration. Reject unsafe paths, commands, or parameters according to the provider's protocol.

Add unit tests with mocks/fakes and a gateway integration test. Add a manual setup document that lists required hardware, credentials, configuration, and cleanup. Keep this task limited to one provider.

The adapter is not production-ready until unavailable hardware, timeout, reconnect, and authorization failures are tested.
```

**Suggested order:** power/reset, deployment, network access, debugger/J-Link.

**Exit criteria:** Each provider has a real adapter, an explicit simulation mode, safe configuration, tests, and a manual verification procedure.

---

## 14. Phase 9 - React Frontend Completion

**Goal:** Make the React frontend a polished, supported operator experience with real backend integration.

**Execution note:** Phase 10 is the architecture decision gate and must select React before this phase begins. Do not separately complete the backend-served dashboard. Use it only as a temporary reference and migration fallback while React reaches parity.

**Recommended model:** GPT-5.3-Codex or Claude Sonnet 5.

**Prompt:**

```text
Complete the React + TypeScript TargetHub frontend as the only supported production UI.

Inspect frontend/src, the backend API routes and schemas, the existing backend-served dashboard, the architecture workflow, and deployment scripts. Treat the backend-served dashboard as a temporary reference implementation, not as a second UI to complete.

Replace mockApi.ts and browser-only data behavior with a typed API client for the real backend. Implement and test the primary workflows:
- login, logout, token restoration, and server-side permission handling;
- target list, details, creation, editing, and capability administration;
- Agent list, enrollment, status, and discovered resources;
- mapping a discovered resource to a capability;
- reservation, release, and conflict handling;
- session open, operation discovery, operation execution, and session close;
- audit/activity visibility for authorized administrators;
- clear loading, empty, expired-session, offline-Agent, unavailable-resource, conflict, 401, and 403 states.

Build a consistent visual system for the operator product: responsive layouts, reusable tables/forms/dialogs, accessible controls, clear status indicators, and focused error feedback. Do not expose provider_config JSON or Linux paths as the normal admin workflow.

Add focused frontend tests, an API/browser smoke test for login -> configure target -> reserve -> open session -> execute -> close -> release, and production build validation. Update deployment and README documentation so React is the only supported frontend.
```

**Exit criteria:** A team can operate TargetHub end to end from the React frontend without manual database edits, and the frontend has documented build, deployment, testing, and troubleshooting procedures.

---

## 15. Phase 10 - React Frontend Decision and Migration Gate

**Goal:** Select one frontend architecture before feature work expands and prevent duplicate UI implementation.

**Decision:** Select outcome A. React becomes the canonical and only supported frontend for the final product. The backend-served dashboard remains a temporary fallback during migration and is not a second production UI.

**Recommended model:** GPT-5.4 mini for decision/documentation; GPT-5.3-Codex for integration planning.

**Prompt:**

```text
Resolve the TargetHub frontend architecture before Phase 9 implementation begins.

Choose React as the canonical supported frontend. Record that the backend-served dashboard is temporary migration reference code and must not receive an independent feature-completion effort.

Inspect frontend/src, frontend/README.md, backend/app/web, API routes, schemas, Docker/deployment scripts, and the Phase 9 workflow requirements. Define the React migration boundary, required API contracts, authentication behavior, permission model, deployment shape, test strategy, and retirement criteria for the backend-served dashboard.

Create a migration checklist that maps every supported dashboard workflow to a React route/component and identifies any missing backend API behavior. Preserve the backend dashboard only until React reaches feature parity and the smoke test passes; then remove it from normal production deployment and update documentation.

Do not implement the same workflow in both frontends. Do not describe both UIs as production-ready.
```

**Exit criteria:** The React-first decision, migration boundary, deployment approach, API gaps, and backend-dashboard retirement criteria are documented. Phase 9 is authorized to implement the React frontend against that plan.

---

## 16. Phase 11 - Audit, Metrics, Health, and Logging

**Goal:** Make operations observable without leaking secrets.

**Recommended model:** GPT-5.3-Codex or Claude Sonnet 5.

**Prompt:**

```text
Complete TargetHub observability and operational hardening.

Inspect audit models/routes/repositories/services, audit migrations, metrics, middleware, health and readiness endpoints, provider gateway, Agent lifecycle, Docker configuration, and tests.

Verify and implement:
- audit events for authentication, administration, target/capability changes, Agent changes, reservations, sessions, and provider operations;
- authorization on audit access;
- stable metric names and bounded labels;
- readiness that reflects database availability and migration state;
- liveness that does not depend on optional hardware;
- request logging that excludes passwords, tokens, and private configuration;
- structured error responses;
- provider and Agent failures that are visible but do not crash the API;
- retention and cleanup guidance for audit logs.

Add tests for audit authorization, metrics output, readiness failure, and sensitive-value redaction. Update the deployment documentation with health checks and troubleshooting.
```

**Exit criteria:** Operators can identify service, database, Agent, and provider health without inspecting application internals or secrets.

---

## 17. Phase 12 - Backups, Restore, Upgrades, and Deployment

**Goal:** Make a production installation recoverable and upgradeable.

**Recommended model:** GPT-5.3-Codex.

**Prompt:**

```text
Make TargetHub deployment production-operational.

Inspect docker-compose.yml, docker-compose.team.yml, Dockerfiles, scripts/deploy.sh, scripts/team_start.sh, migrations, configuration loading, volumes, health checks, and deployment documentation.

Implement or document:
- pinned or controlled image/dependency versions;
- required environment variables and secure secret handling;
- persistent database storage;
- pre-upgrade database backup;
- migration execution during upgrade;
- restore procedure tested on a disposable instance;
- health checks and startup ordering;
- log handling and rotation guidance;
- non-root container behavior where compatible;
- network exposure and reverse-proxy/TLS guidance;
- rollback procedure and migration compatibility policy;
- no hard-coded developer paths or credentials.

Add a disposable deployment smoke test. Do not silently overwrite an existing database during startup.
```

**Validation:**

```bash
docker compose config
docker compose up -d --build
curl -fsS http://localhost:8000/health
curl -fsS http://localhost:8000/health/ready
curl -fsS http://localhost:8000/
docker compose down
```

**Exit criteria:** A new operator can install, back up, upgrade, restore, and roll back using documentation.

---

## 18. Phase 13 - SDK and CLI

**Goal:** Provide a stable non-browser interface before building the VS Code extension.

**Recommended model:** GPT-5.3-Codex.

**Prompt:**

```text
Implement a small supported TargetHub SDK and CLI on top of the stable API.

First inspect the API routes, schemas, authentication behavior, error format, and existing sdk/ and cli/ directories. Do not duplicate business rules in the client.

SDK coverage:
- authentication and token handling;
- targets and capabilities;
- Agent status and resources;
- reservations and release;
- sessions and close;
- capability operation discovery and execution;
- typed errors and timeouts.

CLI coverage:
- login/token configuration;
- target list/show;
- reserve/release;
- session open/close;
- operation execution;
- Agent status;
- readable errors and nonzero exit codes.

Add contract tests against a test API application or disposable server. Document version compatibility, token storage, and examples. Never print credentials by default.
```

**Exit criteria:** A user can complete the main workflow without the web dashboard.

---

## 19. Phase 14 - VS Code Extension

**Goal:** Add VS Code support as a thin API client, after the API/SDK are stable.

**Recommended model:** GPT-5.3-Codex; design review with GPT-5.5 or Claude Sonnet 5.

**Prompt:**

```text
Implement the TargetHub VS Code integration as a thin client of the stable SDK/API.

Inspect vscode-extension/README.md, the SDK/CLI contract, authentication requirements, and supported TargetHub workflows.

Provide only workflows that the API and SDK already support:
- configure TargetHub server and credentials securely using VS Code SecretStorage;
- list targets and Agents;
- reserve/release a target;
- open/close a session;
- display session status and provider operations;
- surface API, authorization, expiry, and offline-Agent errors clearly.

Do not duplicate reservation, session, or authorization logic in the extension. Add command registration, cancellation/timeouts, tests for API-client behavior, and packaging validation. Do not add a marketplace release until the extension has a supportable versioning policy.
```

**Exit criteria:** VS Code is useful but remains replaceable because business logic stays in the server/SDK.

---

## 20. Phase 15 - Security, Reliability, and Performance Review

**Goal:** Find release-blocking problems before sharing the product.

**Recommended model:** GPT-5.5 or Claude Sonnet 5. Use Claude Opus or GPT-6 Astra only for unresolved high-risk findings.

**Prompt:**

```text
Perform a production security and reliability review of TargetHub. Do not make broad speculative refactors.

Review:
- authentication, token signing, expiry, password handling, and bootstrap;
- RBAC and every route's authorization boundary;
- Agent enrollment and credential revocation;
- server-to-Agent protocol and replay protection;
- provider configuration, shell/process use, file paths, and network access;
- audit and log redaction;
- SQL injection and unsafe dynamic queries;
- CORS, trusted hosts, proxy headers, TLS assumptions, and exposed ports;
- race conditions in reservations, sessions, releases, and Agent state;
- timeout, retry, and resource cleanup behavior;
- migration and backup failure modes;
- denial-of-service risks from unbounded input or labels.

Run tests and static checks. Report findings ordered by severity with file paths, exploit/precondition, impact, and smallest fix. Fix only critical or high findings in this pass, add regression tests, and leave lower-risk issues documented.
```

**Exit criteria:** No known unresolved critical/high issue and all accepted risks are documented.

---

## 21. Phase 16 - Release Candidate and Documentation Freeze

**Goal:** Produce a version that another team can install and use without the original developer.

**Recommended model:** GPT-5.5 or Claude Sonnet 5.

**Prompt:**

```text
Prepare TargetHub for a release candidate.

Inspect the full repository and current implementation, preserving unrelated user changes.

Verify and update:
- root README with supported architecture and quick start;
- backend setup and test documentation;
- Agent installation and recovery documentation;
- provider setup guides and simulation limitations;
- API documentation and authentication examples;
- backup, restore, upgrade, rollback, and troubleshooting guides;
- CLI/SDK/VS Code documentation if present;
- roadmap and architecture status markers;
- example environment file with safe placeholder values;
- changelog and release notes;
- license and contribution instructions.

Run the complete release validation. Do not call simulated providers production hardware integrations. Mark deferred features honestly.

Return a release checklist with each item marked PASS, FAIL, or DEFERRED and include exact command output summaries.
```

**Exit criteria:** An external team can install and operate the release using only repository documentation.

---

## 22. Final Release Checklist

Do not share TargetHub as production-ready until every required item is checked.

### Code and architecture

- [ ] `backend/app` is the only active runtime application tree.
- [ ] Architecture documentation matches the implementation.
- [ ] No required runtime file is untracked.
- [ ] No credentials or local absolute paths are committed.
- [ ] Simulated providers are clearly identified. (not re-audited in v0.1.0)

### Security

- [ ] First-admin bootstrap is explicit and protected.
- [ ] User creation is authorized after bootstrap.
- [ ] Every route has a documented authorization decision.
- [x] Passwords are hashed with an approved password hashing scheme.
- [x] Tokens expire (15 min access tokens); agent credentials are revocable. User token revocation is not implemented.
- [ ] Agent credentials are hashed at rest and never logged.
- [ ] Logs and audit details redact secrets.
- [x] TLS/reverse-proxy deployment guidance exists.

### Data and operations

- [x] Fresh database migration passes.
- [ ] Upgrade migration passes on a representative existing database. (NOT verified)
- [x] Backup and restore have been tested.
- [x] Health and readiness endpoints work.
- [ ] Persistent volumes are configured.
- [ ] Startup does not destroy existing data.
- [x] Agent offline and reconnect behavior is tested.

### Functional behavior

- [ ] Target and capability CRUD works.
- [ ] Capability-to-Agent-resource mapping is validated.
- [x] Reservation conflict handling works under concurrent requests.
- [ ] Session ownership and expiry are enforced.
- [ ] Provider operations require an active authorized session.
- [ ] At least one real hardware vertical slice works. (NOT verified: only pty serial + fake GPIO on a dev host; no real Pi)
- [ ] Remaining simulations are documented as deferred or development-only. (not re-audited in v0.1.0)

### Quality and release

- [x] Backend tests pass (154 passed in the existing backend/.venv; fresh-venv bootstrap not re-run).
- [x] Frontend build passes, or the experimental frontend is explicitly archived.
- [x] Lint and compile checks pass.
- [x] API/e2e smoke test passes.
- [ ] CI reproduces local validation. (workflow written; not yet run on GitHub)
- [x] Release notes exist.
- [ ] Installation, troubleshooting, and rollback docs are complete. (install + Pi + backup/TLS docs exist; troubleshooting/rollback incomplete)

---

## 23. Recommended Execution Order and Credit Budget

Use this order:

1. Phase 0 baseline.
2. Phase 1 canonical runtime.
3. Phase 2 reproducible setup.
4. Phase 3 database migrations.
5. Phase 4 authentication/RBAC.
6. Phase 5 Target/Capability/Agent/Resource integrity.
7. Phase 6 Agent hardening.
8. Phase 7 real serial vertical slice.
9. Phase 8 real providers, one at a time.
10. Phase 10 React frontend decision and migration gate.
11. Phase 9 React frontend completion.
12. Phase 11 observability.
13. Phase 12 deployment and recovery.
14. Phase 13 SDK/CLI.
15. Phase 14 VS Code extension.
16. Phase 15 security/reliability review.
17. Phase 16 release candidate.

Use cheap models for Phases 0, 1, 2, documentation, isolated tests, and release checklists. Use GPT-5.3-Codex for multi-file backend work. Reserve Claude Sonnet 5 or GPT-5.5 for security, authorization, protocol design, and final review. Use Claude Opus or GPT-6 Astra only when a high-risk architectural or security question remains unresolved after a cheaper review.

A good handoff request after every phase is:

```text
Before changing another area, stop and report the phase acceptance status. Include exact failing commands and classify each failure. Do not continue into the next phase automatically.
```

---

## 24. Definition of Production-Ready

TargetHub is production-ready only when all of the following are true:

- The supported deployment is reproducible from a clean checkout.
- Identity, authorization, and Agent credentials are secure and tested.
- Data migrations, backups, restores, and upgrades are operationally tested.
- At least one real hardware workflow is Agent-backed and session-authorized.
- Every other provider is either real and tested or explicitly marked development-only.
- One supported UI is documented.
- API, CLI, and operational documentation are sufficient for a new team.
- CI passes from a clean environment.
- A release candidate has passed the final checklist.
- Known limitations and deferred scope are visible to users.
