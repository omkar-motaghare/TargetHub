# Phase 10 React Frontend Decision and Migration Gate

**Project:** TargetHub  
**Repository:** /home/omkar_motaghare/TargetHub  
**Date:** 2026-09-28  
**Milestone:** Phase 10 - React frontend decision and migration gate

## Decision

React + TypeScript under frontend/src is the canonical and only supported product frontend.

The backend-served dashboard under backend/app/web is temporary migration reference code. It must not receive an independent feature-completion effort. It remains available only until React reaches feature parity and the migration exit criteria pass.

## Why this decision

- Product UX scope is expanding (targets, agents, resources, reservations, sessions, operations, audit, auth states).
- React provides better long-term UI maintainability through reusable components and typed frontend contracts.
- Maintaining two independently evolving UIs would duplicate implementation and testing effort.

## Migration boundary

### In scope for React (Phase 9 implementation)

- All operator-facing workflows that are currently available in the backend-served dashboard.
- Real API integration only (no localStorage or mock business behavior for production workflows).
- Role-aware routing and API-driven authorization handling.
- Production build and test path for frontend.

### Out of scope for backend-served dashboard

- No new workflow completion work.
- No UX-polish track beyond critical break-fix needed to keep migration fallback usable.
- No claim in docs that it is a production-ready canonical UI.

## Required API contracts (React integration surface)

React migration uses and validates these backend routes:

- Auth:
  - POST /api/v1/auth/token
  - GET /api/v1/auth/me
- Targets and capabilities:
  - GET/POST/PUT/DELETE /api/v1/targets
  - GET/POST/PUT/DELETE /api/v1/targets/{target_id}/capabilities
- Agents/resources:
  - GET /api/v1/agents
  - GET /api/v1/agents/enrollments
  - POST /api/v1/agents/enrollments
  - POST /api/v1/agents/{agent_id}/disable
  - POST /api/v1/agents/{agent_id}/enable
  - POST /api/v1/agents/{agent_id}/revoke-credential
- Reservations:
  - GET/POST /api/v1/reservations
  - POST /api/v1/reservations/{reservation_id}/release
  - POST /api/v1/reservations/{reservation_id}/force-release
- Sessions and operations:
  - GET/POST /api/v1/sessions
  - POST /api/v1/sessions/{session_id}/close
  - GET /api/v1/sessions/{session_id}/operations
  - POST /api/v1/sessions/{session_id}/execute
  - POST /api/v1/sessions/{session_id}/serial/open
  - GET /api/v1/sessions/{session_id}/serial/read
  - POST /api/v1/sessions/{session_id}/serial/write
  - POST /api/v1/sessions/{session_id}/serial/close
- Audit/admin visibility:
  - GET /api/v1/audit
- Supporting data:
  - GET /api/v1/labs

## Authentication and permission model

- React stores only bearer token and minimal user identity metadata.
- Source of truth for authorization is server-side role enforcement.
- UI must treat 401 as token-expired/not-authenticated and force re-auth.
- UI must treat 403 as authenticated-but-not-authorized and render explicit permission state.
- Non-admin users must never be offered admin actions in primary UI flows.

## Deployment shape

Final target state:

1. React frontend is built as production static assets.
2. Assets are served by one documented deployment path (to be finalized in Phase 9):
   - either via FastAPI static mounting, or
   - via dedicated frontend container/reverse-proxy path.
3. The chosen path is the only documented production UI path.

During migration:

- backend/app/web remains accessible as fallback only.
- team_start.sh and root docs must not describe backend/app/web as canonical.

## Test strategy for migration

- Frontend unit/component tests for route guards, loading/error states, and role-sensitive actions.
- API-integration tests for typed client behavior and error normalization.
- Browser/API smoke flow:
  - login -> configure target -> reserve -> open session -> execute -> close -> release
- Production build validation on frontend package.

## Backend dashboard retirement criteria

Retire backend/app/web from normal production deployment only when all conditions hold:

1. React implements all supported workflows listed below.
2. Smoke flow passes against real backend APIs.
3. Admin and non-admin permission states are validated.
4. Offline-agent, expired-session, unavailable-resource, conflict, 401, and 403 states are explicitly handled in React.
5. Documentation and runbooks reference only the React path as supported.

## Workflow mapping checklist (dashboard -> React)

Status key: DONE means implemented with real API behavior in React today. GAP means migration work required in Phase 9.

1. Login/logout:
   - React route/component: /login (pages/Login.tsx), auth store (services/auth.tsx)
   - API routes: POST /auth/token, GET /auth/me
   - Status: PARTIAL
   - Gap: add centralized 401 handling and automatic redirect/logout on token expiry across all requests.

2. Target list/details:
   - React route/component: /targets (pages/Targets.tsx)
   - API routes: GET /targets, GET /targets/{id}
   - Status: PARTIAL
   - Gap: add target details view and richer capability/status presentation.

3. Target and capability admin:
   - React route/component: admin targets tab (pages/Admin/Targets.tsx)
   - API routes: /targets + /targets/{target_id}/capabilities CRUD
   - Status: GAP
   - Gap: current admin targets page is read-only + force release. Needs full create/edit/delete and capability CRUD with validation.

4. Agent list, enrollment, status, resources:
   - React route/component: admin agents tab (pages/Admin/Agents.tsx)
   - API routes: /agents, /agents/enrollments, enable/disable/revoke
   - Status: PARTIAL
   - Gap: add resource visibility and filtering, enrollment lifecycle visibility, last-seen/offline indicators.

5. Map discovered resource to capability:
   - React route/component: not implemented
   - API routes: capability create/update payload with agent_id/resource_id
   - Status: GAP
   - Gap: add capability editor UI bound to discovered agent resources.

6. Reservation and release:
   - React route/component: /targets, /my
   - API routes: /reservations list/create/release/force-release
   - Status: PARTIAL
   - Gap: replace inline/manual fetches, normalize conflict errors, show reservation windows and conflict details consistently.

7. Session open/close:
   - React route/component: /my and /sessions
   - API routes: /sessions create/list/close
   - Status: PARTIAL
   - Gap: capability selection and explicit ownership/expiry messaging.

8. Capability operations discovery/execution:
   - React route/component: not implemented
   - API routes: /sessions/{id}/operations and /sessions/{id}/execute (+ serial open/read/write/close)
   - Status: GAP
   - Gap: add operations panel/console with parameter forms and result rendering.

9. Audit/activity for admins:
   - React route/component: admin activity tab (pages/Admin/Activity.tsx)
   - API routes: GET /audit
   - Status: GAP
   - Gap: current view is localStorage mock. Replace with server audit query + filters.

10. Clear error-state handling:
   - React route/component: cross-cutting
   - API routes: all
   - Status: GAP
   - Gap: standardized handling for expired-session, offline-agent, unavailable-resource, 401, 403, and 409 conflict.

## Missing backend API behavior identified at this gate

No blocking backend API gap was found for the Phase 9 core flow. Existing routes cover the required workflow surface.

Follow-up improvements that may help React UX but are not blockers:

- add explicit session-expiry metadata in operation error payloads for easier UX messaging.
- add optional agent/resource summary endpoints if list payloads become too heavy for UI polling.

## Governance rule for Phase 9

Implement each workflow exactly once in React. Do not implement net-new workflow completion in backend/app/web.

## Completion status

Phase 10 decision gate complete:

- React selected as canonical frontend.
- Migration boundary documented.
- API contract surface and permission model documented.
- Deployment shape and dashboard retirement criteria documented.
- Workflow mapping checklist and gap list documented.
