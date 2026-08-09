# FEATURE-003 — Session + Authorization Foundation

## Purpose

A TargetHub reservation grants ownership of a target for a time window. A session is the explicit authorization boundary used by future access providers.

```text
Reservation
    |
    | active + owned by user
    v
Session request
    |
    +-- reservation active?
    +-- reservation owner?
    +-- reservation started?
    +-- target enabled?
    +-- requested capability enabled?
    |
    v
Authorized Session
    |
    v
Future provider enforcement
```

## Current implementation

- `TargetSession` persistence model
- Session repository
- Session service
- Session REST API
- Alembic migration
- Reservation ownership validation
- Reservation time-window validation
- Target capability validation
- Session expiry based on reservation end time
- Owner-only session close

## API

```text
POST /api/v1/sessions
GET  /api/v1/sessions
GET  /api/v1/sessions/{session_id}
POST /api/v1/sessions/{session_id}/close?user_id=<user>
```

Create a session:

```json
{
  "reservation_id": "<reservation-id>",
  "user_id": "developer",
  "capability_type": "serial"
}
```

## Important limitation

`user_id` is still an opaque development identity. Authentication and production identity are deliberately not implemented in FEATURE-003. The production flow must replace this input with an authenticated principal before access-control enforcement is considered complete.

## Verification

Start the project using Docker:

```bash
docker compose up --build -d
```

Open Swagger:

```text
http://localhost:8000/docs
```

Create a target with an enabled `serial` capability, create a current reservation for `developer`, then create a session using that reservation and `capability_type: serial`.

Expected result: HTTP 201 with an `active` session whose `expires_at` matches the reservation end time.

Negative checks:

1. Use a different `user_id` — request must be rejected.
2. Use a non-active reservation — request must be rejected.
3. Use a reservation that has not started — request must be rejected.
4. Request a capability not configured on the target — request must be rejected.
5. Close the session as its owner — session becomes `closed`.

This feature establishes authorization semantics; it does not yet connect a session to real serial, SSH, FTP, J-Link, or power operations.
