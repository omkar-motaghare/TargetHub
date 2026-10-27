# Frontend Browser Smoke Test

Use this checklist against the React frontend at http://localhost:5173.

Prerequisites:

1. Backend API running at http://localhost:8000.
2. React frontend running via `npm run dev` in `frontend/`.
3. Admin user available.

Flow:

1. Login:
- Open `/login`.
- Authenticate with admin credentials.
- Confirm navigation to targets page.

2. Configure target:
- Go to admin page.
- Create a target with one enabled serial capability.
- Assign an agent/resource if available.
- Confirm target appears in target list.

3. Reserve:
- Open targets page.
- Reserve the created target for a valid time range.
- Confirm status changes to reserved.

4. Open session:
- Go to My Reservations.
- Open a session for an enabled capability.
- Confirm session appears in Sessions page with active status.

5. Execute:
- In Sessions page, open operations.
- Run one supported operation (serial read/write or provider execute).
- Confirm output appears in Session output console.

6. Close:
- Close the active session.
- Confirm session status is no longer active.

7. Release:
- Return to My Reservations.
- Release reservation.
- Confirm target returns to available.

Expected error/state checks:

- 401/expired token: user is logged out and redirected to login.
- 403 action: clear permission message displayed.
- Conflict (409): clear conflict message displayed.
- Offline API: connectivity error message displayed.
- Empty states: targets/sessions/activity pages render empty-state cards or table rows.
