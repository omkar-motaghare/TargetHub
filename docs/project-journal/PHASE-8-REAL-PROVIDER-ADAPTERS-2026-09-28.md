# Phase 8 Real Provider Adapters Record

**Project:** TargetHub  
**Repository:** /home/omkar_motaghare/TargetHub  
**Date:** 2026-09-28  
**Milestone:** Phase 8 - real provider adapters (power, deployment, network, debugger)

## Summary

Phase 8 now provides real adapter modes for all four non-serial provider families while preserving explicit simulated mode for development:

1. Power / reset
2. Deployment
3. Network access
4. Debugger / J-Link

All providers continue to execute through existing session authorization and gateway controls. Provider execution stays normalized through ProviderOperationResult.

## Shared safety model

- Simulated mode remains available for every provider family.
- Real mode requires explicit provider_config fields and strict validation.
- Controller endpoints are restricted to validated URL + ID patterns.
- Environment-variable credential references are used for secrets in real mode; raw secrets are not stored in provider_config.
- Unsafe inputs are rejected (for example invalid command text, unsafe artifact paths, invalid IDs).
- TLS certificate verification bypass is not permitted by these adapters.
- Timeout and connectivity failures return clear provider messages.

## Implemented in order

### 1) Power / reset

Status: already real-capable, retained and validated.

- Real mode: authenticated HTTP controller operations for status/on/off/reset/cycle.
- Simulated mode: in-memory power state machine for development.
- Supports timeout, unreachable-controller, and auth-missing failure paths.

### 2) Deployment

Status: real mode added.

- Real mode operations:
  - POST /v1/deployments/{target_id}/deploy
  - GET /v1/deployments/{target_id}/status
- Validated config includes mode, controller_url, target_id, timeout, and auth mode.
- Artifact safety checks reject absolute paths and parent traversal.
- Simulated mode still records last deployment locally.

### 3) Network access

Status: real mode added.

- Real mode operations:
  - GET /v1/channels/{channel_id}/info
  - POST /v1/channels/{channel_id}/exec
- Validated config includes mode, controller_url, channel_id, timeout, and auth mode.
- Command safety checks:
  - required non-empty command,
  - constrained character set,
  - optional allowlist enforcement via allowed_commands.
- Simulated mode still supports info/exec for development flows.

### 4) Debugger / J-Link

Status: real mode added.

- Real mode operations:
  - GET /v1/probes/{probe_id}/status
  - POST /v1/probes/{probe_id}/attach|detach|halt|resume|reset
- Validated config includes mode, controller_url, probe_id, timeout, and auth mode.
- Simulated mode remains available with attach/core state behavior.

## Gateway and configuration integration

- Provider config validation now covers power, network, deployment, and debugger families during capability create/update.
- Target creation with embedded capabilities now validates provider_config as well.
- ProviderGateway now passes resolved capability provider_config into registry provider construction.

This ensures runtime provider behavior matches the capability configuration selected in TargetHub.

## Tests added and updated

### Unit/provider tests

- tests/test_providers.py
  - real network command allowlist success and denial;
  - real deployment unsafe artifact rejection;
  - real deployment timeout handling;
  - real debugger action flow;
  - real power unreachable-controller failure;
  - registry validation for all real provider families.

### Gateway integration tests

- tests/test_provider_gateway.py
  - real network exec through ProviderGateway;
  - real deployment timeout conflict through ProviderGateway;
  - real debugger auth failure through ProviderGateway.

### Existing session authorization preserved

- ProviderGateway authorization and runtime binding checks remain unchanged in intent:
  - active, unexpired, owned sessions only,
  - capability/resource/agent binding consistency,
  - audit + metric recording.

## Manual setup and verification procedures

Manual procedures are listed below and are intentionally controller-oriented so they are testable without embedding secrets in TargetHub records.

### Power / reset manual test

Required hardware/services:

- a reachable power controller API endpoint;
- a mapped outlet ID;
- optional bearer/basic credentials set as environment variables.

Capability provider_config example:

```json
{
  "mode": "real",
  "controller_url": "https://pdu.example.lab",
  "outlet_id": "rack-a-outlet-4",
  "auth_type": "bearer",
  "bearer_token_env": "TARGETHUB_PDU_TOKEN",
  "timeout_seconds": 3.0
}
```

Verification:

1. Open a valid session with power/reset capability.
2. Run operations: status, on, off, reset, cycle.
3. Simulate controller outage and verify clear unreachable/timeout messages.
4. Remove credential env var and verify auth failure.

Cleanup:

- return outlet to safe expected state;
- clear temporary credential env vars.

### Deployment manual test

Required hardware/services:

- deployment controller API endpoint;
- a target identifier recognized by deployment infrastructure.

Capability provider_config example:

```json
{
  "mode": "real",
  "controller_url": "https://deploy.example.lab",
  "target_id": "board-stm32-a",
  "auth_type": "bearer",
  "bearer_token_env": "TARGETHUB_DEPLOY_TOKEN",
  "timeout_seconds": 30.0
}
```

Verification:

1. Open a valid session with deploy capability.
2. Execute deploy with a safe relative artifact name, then status.
3. Attempt unsafe artifact paths (absolute or ../) and verify rejection.
4. Simulate timeout/unreachable controller and verify clear errors.

Cleanup:

- restore known firmware if needed;
- clear temporary credential env vars.

### Network access manual test

Required hardware/services:

- network access controller API endpoint;
- a channel ID mapped to the intended host/service.

Capability provider_config example:

```json
{
  "mode": "real",
  "controller_url": "https://net.example.lab",
  "channel_id": "linux-lab-a",
  "allowed_commands": ["uname -a", "id"],
  "auth_type": "bearer",
  "bearer_token_env": "TARGETHUB_NET_TOKEN",
  "timeout_seconds": 5.0
}
```

Verification:

1. Open a valid session with ssh/telnet/ftp/network capability.
2. Execute info and an allowlisted exec command.
3. Execute a non-allowlisted command and verify rejection.
4. Simulate unreachable and timeout failures.

Cleanup:

- revoke temporary access channel if created for the test;
- clear temporary credential env vars.

### Debugger / J-Link manual test

Required hardware/services:

- debugger controller API endpoint;
- a probe ID mapped to a physical debug probe/target.

Capability provider_config example:

```json
{
  "mode": "real",
  "controller_url": "https://debug.example.lab",
  "probe_id": "jlink-serial-00012345",
  "auth_type": "bearer",
  "bearer_token_env": "TARGETHUB_DEBUG_TOKEN",
  "timeout_seconds": 8.0
}
```

Verification:

1. Open a valid session with jlink capability.
2. Run status, attach, halt, resume, reset, detach.
3. Remove credential env var and verify auth failure.
4. Simulate unreachable and timeout failures.

Cleanup:

- leave core running and probe detached;
- clear temporary credential env vars.

## Validation results

Focused Phase 8 tests:

```text
python -m pytest -q tests/test_providers.py tests/test_provider_gateway.py tests/test_target_capability_service.py
35 passed
```

Full backend regression:

```text
python -m pytest -q
113 passed
```

## Success criteria status

Success criteria are satisfied for Phase 8:

- each provider has a real adapter mode;
- each provider has explicit simulated mode;
- configuration is validated and safety constrained;
- tests cover normal behavior and failure modes (unavailable, timeout, reconnect path via repeated calls, auth failure);
- manual verification procedures are documented per provider.
