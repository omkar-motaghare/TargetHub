# TargetHub web UI

React 18 + TypeScript + Vite. The production build is copied into the server image and served at `/app`.

```bash
npm ci
npm run dev          # http://localhost:5173; /api and /web are proxied to a backend on :8000
                     # (TARGETHUB_DEV_API=http://other-host:8000 npm run dev to change it)
npm run typecheck
npm test             # Vitest unit tests
npm run build        # dist/ (the Docker build does this for you)
```

Browser smoke test against a real server (from the repository root):

```bash
PLAYWRIGHT_CHANNEL=chrome bash scripts/e2e-ui.sh      # or PLAYWRIGHT_CHROMIUM_PATH=/path/to/chrome
```

Structure: `src/pages` (user pages, `pages/Admin/*` for administration), `src/components`
(serial console, notification bell, badges), `src/services` (API client with token refresh, auth
context, types), `src/utils`.
