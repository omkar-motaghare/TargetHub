# Phase 1 M0 Canonical Runtime Record

**Project:** TargetHub  
**Repository:** `/home/omkar_motaghare/TargetHub`  
**Date:** 2026-09-22  
**Milestone:** M0 - Repository hygiene / canonical runtime

## Summary

Phase 1 completed the repository-hygiene milestone by confirming that `backend/app/` is the live runtime package and that the repository-root `app/` tree is not referenced by active runtime code, Docker configuration, or local scripts.

The root `app/` tree was preserved by moving it to `archive/app-root-legacy/` rather than deleting it. This keeps the historical tree available for future reference while avoiding a second active runtime surface.

## What Changed

- Archived the unused root `app/` tree to `archive/app-root-legacy/`.
- Added `archive/app-root-legacy/README.md` to document why the tree was archived.
- Marked M0 complete in `docs/development/ROADMAP.md`.
- Left runtime code and Docker configuration unchanged because they already pointed to the canonical backend layout.

## Reference Check

The phase-1 audit confirmed:

- No active repository file required the root `app/` tree at runtime.
- Docker builds from `./backend`.
- Backend entrypoints import the backend-local `app` package.
- Backend compile and test commands can be run against `backend/app` without the root `app/` tree.
- Docker Compose files remain valid.

## Validation

### Passed

- `python3 -m compileall -q backend/app`
- `cd backend && python3 -m pytest -q`
- `docker compose config`
- `docker compose -f docker-compose.team.yml config`

### Repository checks

- Root `app/` absent after archival.
- `backend/app/` present and canonical.
- `archive/app-root-legacy/README.md` present.
- `docs/development/ROADMAP.md` updated.

## Remaining Risks

- The repository still contains other in-progress changes unrelated to M0.
- Backend dependency reproducibility and broader production-hardening phases are still pending.
- The archived root tree should remain read-only unless a later audit proves a unique needed file exists there.

## Next Safe Phase

Proceed to the next roadmap phase only after the backend dependency environment is reproducible enough to trust test results. The next smallest safe work is the setup/reproducibility phase before deeper product work.
