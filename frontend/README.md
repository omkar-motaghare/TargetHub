# TargetHub Frontend (Canonical)

React + TypeScript in this package is the only supported product frontend.

The backend dashboard under backend/app/web is migration fallback/reference only and must not receive independent feature-completion work.

## Local development

```bash
cd frontend
npm install
npm run dev
```

Default dev URL: http://localhost:5173

If backend runs on another origin:

```bash
VITE_API_URL=http://localhost:8000/api/v1 npm run dev
```

## Validation

Unit tests:

```bash
npm run test
```

Production build:

```bash
npm run build
```

API smoke flow (from repository root):

```bash
TARGETHUB_ADMIN_USER=admin TARGETHUB_ADMIN_PASS=change-me-now ./scripts/frontend_smoke_api.sh
```

This smoke verifies:

- login
- target creation with capability
- reservation
- session open
- operation discovery/read
- session close
- reservation release

Browser smoke checklist:

- docs/FRONTEND_BROWSER_SMOKE_TEST.md

## Deployment notes

- React is the canonical UI path for operations.
- Canonical backend-served UI route is http://localhost:8000/app (with /dashboard as alias).
- Legacy fallback remains reachable at http://localhost:8000/legacy-dashboard during migration.
- Production docs and operations runbooks must describe React as the supported frontend.
