# TargetHub Frontend (experimental)

This frontend is currently an experimental React scaffold.

The **recommended prototype UI** is the backend-served dashboard at:

- http://localhost:8000/dashboard

For normal development and validation, use the Docker workflow from the repository root and continue through the built-in dashboard.

This is a minimal React + TypeScript (Vite) scaffold implementing role-based routing and basic admin/user pages.

Run locally:

```bash
cd frontend
npm install
npm run dev
```

If the backend is running on a different origin, set `VITE_API_URL` before starting, for example:

```bash
VITE_API_URL=http://localhost:8000/api/v1 npm run dev
```

What I implemented:
- Role-based auth store (`src/services/auth.tsx`)
- Mock API for targets/reservations (`src/services/mockApi.ts`)
- Pages: Login, Targets, My Reservations
- Admin dashboard with tabs: Targets, Agents, Activity, Config
- Basic styling in `src/styles.css`

Next steps I can implement:
- Hook UI to backend APIs and enforce server-side permissions
- Add WebSocket/SSE real-time updates
- Improve UX and add unit/E2E tests
- Replace mock storage with real agent/target management flows

If you'd like, I'll now:
- Integrate with the backend API (preferred) or
- Produce wireframes for the admin pages first

Tell me which and I'll continue.
