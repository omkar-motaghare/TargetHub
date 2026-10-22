# Phase 6 Agent Runtime and Enrollment Record

**Project:** TargetHub  
**Repository:** `/home/omkar_motaghare/TargetHub`  
**Date:** 2026-09-28  
**Milestone:** Phase 6 - Agent runtime and enrollment production hardening

## Acceptance

Phase 6 is complete. A remote Linux Agent can enroll with a short-lived one-time token, restart using its persisted credential, reconnect after a missed heartbeat, report resources, and be disabled or revoked without leaving usable credential material on the server.

## Implemented Behavior

- Enrollment tokens are stored as hashes, expire after 30 minutes, and can be consumed only once.
- Agent credentials are generated independently, stored as hashes with a non-secret prefix, and removed on revocation.
- Disabled and revoked Agents cannot authenticate; disabled or revoked Agent mappings disable their capabilities.
- Disabled Agents may be re-enrolled with the same name and receive a new credential.
- Heartbeats update hostname, liveness, and the complete resource inventory.
- Online Agents become offline after the configured stale threshold; a valid heartbeat returns them to online.
- Resource identity is stable for the same `(resource_key, resource_type)` pair, and duplicate heartbeat entries are ignored.
- Heartbeat resource fields reject blank and overlong identifiers through schema validation.
- Runtime requests use bounded timeouts and exponential retry backoff.
- Enrollment and runtime errors redact enrollment tokens and credentials before logging.
- Configuration writes use a temporary file and atomic replacement; the persisted configuration is mode `0600`.
- The Linux installer validates the downloaded runtime with `py_compile`, installs a templated systemd service, and cleans temporary files on failure.
- The installer and runtime remain intentionally Linux-only. Windows Agent support is deferred to a separate design and implementation phase.
- The Agent operation polling and simulated/real serial transport are already present and are recorded as early Phase 7 implementation.

## Validation

Focused Phase 6 validation completed on 2026-09-28:

```text
26 passed in 4.80s
```

The focused suite covered:

- `tests/test_agent_enrollment.py`
- `tests/test_agent_runtime.py`
- `tests/test_agent_operation_service.py`
- `tests/test_agent_serial_integration.py`

Additional checks passed:

- `python -m compileall -q app`
- `bash -n app/web/agent/install.sh`

Full backend validation completed on 2026-09-28:

```text
99 passed in 9.11s
```

The frontend build remains a broader product check and should be run before a release candidate.

## Known Non-Blocking Quality Debt

- Ruff currently reports two pre-existing findings in `app/providers/power.py`; they are unrelated to Agent runtime behavior.
- Static analysis still recommends reducing cognitive complexity in the real serial execution path and the long-running Agent main loop.
- FastAPI lifespan migration, Starlette/httpx compatibility, and `datetime.utcnow()` warnings remain tracked repository-wide.
- Agent endpoint response documentation can be expanded for explicit `401` and `403` responses.

These items do not block the Phase 6 functional exit criteria, but they should be addressed during the later reliability and release review phases.
