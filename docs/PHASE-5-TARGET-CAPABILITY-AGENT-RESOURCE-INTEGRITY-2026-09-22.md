# Phase 5 Target Capability Agent Resource Integrity Record

**Project:** TargetHub  
**Repository:** `/home/omkar_motaghare/TargetHub`  
**Date:** 2026-09-22  
**Milestone:** Phase 5 - Target/Capability/Agent/Resource integrity boundary

## Summary

Phase 5 completed the backend integrity boundary for
`Target -> Capability -> Agent -> Resource` by enforcing capability mapping
validation, persisting capability/agent/resource binding into sessions, and
revalidating that binding at operation time.

This phase keeps providers simulated where designed and does not introduce real
hardware control. The focus is structural/runtime integrity and explicit failure
modes for disabled, revoked, offline, stale, or unavailable mappings.

## What Was Implemented

### Capability mapping validation

- Added centralized mapping validators in
  `backend/app/services/capability_binding.py`.
- Enforced create/update capability checks in
  `backend/app/services/target_capability_service.py`:
  - if one of `agent_id`/`resource_id` is set, both are required;
  - selected Agent must exist;
  - selected resource must exist;
  - selected resource must belong to selected Agent;
  - resource type must be compatible with capability type;
  - enabled capabilities require an available resource.
- Added equivalent validation for target create payload capabilities in
  `backend/app/services/target_service.py`.

### Session binding persistence and runtime enforcement

- Extended `TargetSession` with binding columns:
  - `capability_id`
  - `agent_id`
  - `resource_id`
- Added Alembic migration
  `backend/alembic/versions/e6a7b8c9d0e1_add_session_capability_bindings.py`
  to add columns, foreign keys, and indexes.
- Extended session schema in `backend/app/schemas/session.py`:
  - request supports optional `capability_id`;
  - response includes `capability_id`, `agent_id`, `resource_id`.
- Updated session creation flow in `backend/app/services/session_service.py`:
  - resolves a concrete capability;
  - requires `capability_id` when multiple enabled capabilities share a type;
  - validates runtime readiness (enabled/online/stale/revoked/unavailable);
  - stores capability/agent/resource binding on session record.
- Updated provider gateway in `backend/app/services/provider_gateway.py`:
  - verifies session binding metadata is present;
  - resolves current capability from target state;
  - rejects drift between session binding and current capability mapping;
  - revalidates runtime readiness before executing provider operations.

### Agent disable/revoke safety

- Updated `backend/app/services/agent_service.py` so disabling or revoking an
  Agent credential also disables enabled capabilities mapped to that Agent.
- Added repository helper in `backend/app/repositories/agent_repository.py`:
  `disable_capabilities_for_agent(...)`.
- This prevents a silent state where a capability remains enabled but cannot be
  used due to disabled/revoked Agent credentials.

### API/UI/script alignment

- Updated dashboard session-open flow in `backend/app/web/app.js`:
  - selection is by concrete capability label (`name (type)`), not type only;
  - sends `capability_id` with session creation request.
- Updated session router dependency in
  `backend/app/api/v1/sessions.py` to construct gateway with target repository
  for runtime mapping checks.
- Updated E2E script `scripts/e2e-demo.sh`:
  - enroll Agent;
  - publish serial + power resources via heartbeat;
  - create capabilities mapped to `agent_id` and `resource_id`;
  - open sessions with explicit `capability_id`.

## Focused Tests Added or Expanded

- `backend/tests/test_target_capability_service.py` (new)
  - valid mapping and unmapped capability behavior;
  - missing pair checks;
  - missing Agent/resource checks;
  - incompatible resource type checks;
  - unavailable resource behavior for enabled/disabled capabilities.
- `backend/tests/test_session_service.py` (expanded)
  - session binds capability/agent/resource IDs;
  - ambiguous same-type capability rejection without `capability_id`;
  - explicit capability selection by `capability_id`;
  - offline Agent rejection;
  - stale heartbeat rejection;
  - unavailable resource rejection;
  - disabled Agent rejection.
- `backend/tests/test_provider_gateway.py` (expanded)
  - session binding mismatch rejection;
  - missing binding metadata rejection.
- `backend/tests/test_agent_enrollment.py` (expanded)
  - disabling/revoking Agent triggers capability disable helper.
- `backend/tests/test_auth_rbac.py` (updated for new boundary)
  - ownership/session test now provisions a mapped Agent/resource-backed
    capability before opening a session.
- `backend/tests/test_migrations_lifecycle.py` (updated)
  - expected Alembic head revised;
  - representative session record now includes binding columns.

## Validation Results

### Narrow validation

- `python -m pytest -q tests/test_target_capability_service.py`  
  Result: **7 passed**
- `python -m pytest -q tests/test_session_service.py`  
  Result: **10 passed**
- `python -m pytest -q tests/test_provider_gateway.py`  
  Result: **9 passed**
- `python -m pytest -q tests/test_agent_enrollment.py`  
  Result: **8 passed**
- `python -m pytest -q tests/test_auth_rbac.py`  
  Result: **24 passed**
- `python -m pytest -q tests/test_migrations_lifecycle.py`  
  Result: **4 passed**

### Broader phase validation

- `python -m pytest -q tests/test_agent_enrollment.py tests/test_session_service.py`  
  Result: **pass**
- `python -m pytest -q` from `backend/`  
  Result: **74 passed**
- `ruff check app` from `backend/`  
  Result: **pass**

### Additional repository checks

- `python3 -m compileall -q backend/app`  
  Result: **COMPILE_OK**
- `npm run build` from `frontend/`  
  Result: **pass**
- `docker compose config`  
  Result: **pass**
- `bash -n scripts/e2e-demo.sh`  
  Result: **SYNTAX_OK**

## Files Changed in Phase 5

- `backend/app/services/capability_binding.py`
- `backend/app/services/target_capability_service.py`
- `backend/app/services/target_service.py`
- `backend/app/services/session_service.py`
- `backend/app/services/provider_gateway.py`
- `backend/app/services/agent_service.py`
- `backend/app/repositories/agent_repository.py`
- `backend/app/models/session.py`
- `backend/app/schemas/session.py`
- `backend/app/api/v1/sessions.py`
- `backend/app/api/v1/targets.py`
- `backend/app/api/v1/target_capabilities.py`
- `backend/alembic/versions/e6a7b8c9d0e1_add_session_capability_bindings.py`
- `backend/app/web/app.js`
- `scripts/e2e-demo.sh`
- `backend/tests/test_target_capability_service.py`
- `backend/tests/test_session_service.py`
- `backend/tests/test_provider_gateway.py`
- `backend/tests/test_agent_enrollment.py`
- `backend/tests/test_auth_rbac.py`
- `backend/tests/test_migrations_lifecycle.py`
- `docs/PHASE-5-TARGET-CAPABILITY-AGENT-RESOURCE-INTEGRITY-2026-09-22.md`

## Remaining Risks and Follow-Up

- Runtime checks currently depend on Agent heartbeat freshness and status fields;
  Phase 6 should further harden stale/offline transitions and agent-runtime
  behavior under process/network faults.
- Existing sessions created before this migration may have null binding columns;
  runtime gateway now rejects missing session-binding metadata. This is safe for
  integrity, but operators should close/reopen legacy sessions after upgrade.
- Provider execution remains simulated for non-serial and optionally simulated
  for serial; real remote serial and protocol work remains a Phase 7 objective.
- FastAPI lifecycle and `datetime.utcnow()` deprecation warnings observed in
  prior phases remain out of scope for this phase.

## Next Safe Phase

Proceed to Phase 6: Agent runtime and enrollment production hardening.