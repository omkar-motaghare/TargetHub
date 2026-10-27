# Phase 2 Setup Reproducibility Record

**Project:** TargetHub  
**Repository:** `/home/omkar_motaghare/TargetHub`  
**Date:** 2026-09-22  
**Milestone:** Phase 2 - Reproducible development and CI setup

## Summary

Phase 2 focused on making the development and validation workflow reproducible without changing product behavior.

The main goal was to ensure the backend test suite and local validation commands are documented in a way that future contributors can reproduce consistently, and to remove hard-coded absolute interpreter paths from scripts.

## What Changed

- Added `scripts/bootstrap-backend.sh` to create or refresh the backend virtual environment and install runtime plus test dependencies.
- Updated `scripts/e2e-demo.sh` to stop using the hard-coded absolute backend Python path.
- Added a repo-relative Python fallback in the e2e script:
  - prefers `backend/.venv/bin/python` when present
  - otherwise falls back to `python3`
- Documented the working backend validation commands in `backend/README.md`.
- Kept dependency declarations and CI structure aligned with the existing setup instead of adding a new packaging system.

## Current Setup Notes

- Backend runtime package remains `backend/app`.
- `scripts/bootstrap-backend.sh` is the supported setup entry point for creating or refreshing `backend/.venv`.
- Backend tests are expected to run from inside `backend/` or via the repository's backend virtual environment.
- The documented `cd backend && python -m pytest -q` command assumes the backend virtual environment is activated first (`source .venv/bin/activate`).
- The frontend build remains part of the validation flow.
- CI now bootstraps the backend environment with `scripts/bootstrap-backend.sh`, then runs lint, compile, and tests from the resulting backend virtual environment.

## Validation

### Passed

- `bash scripts/bootstrap-backend.sh`
- `bash -n scripts/e2e-demo.sh`
- `source backend/.venv/bin/activate && cd backend && python -m pytest -q`
- `backend/.venv/bin/python -m pytest -q backend/tests/`
- `backend/.venv/bin/python -m compileall -q backend/app`
- `cd frontend && npm run build`

### Notes on command context

A direct system-Python invocation may fail if the current interpreter environment does not already include backend dependencies. The repository now documents the working backend validation path and the e2e script no longer hard-codes an absolute interpreter location.

## Remaining Risks

- The backend setup is now reproducible through `scripts/bootstrap-backend.sh`, but a new machine still needs Python 3.12 available to create the environment.
- Future cleanup may still be needed if more scripts contain environment-specific paths.
- This phase deliberately did not change product behavior or runtime architecture.

## Next Safe Phase

Proceed to the next roadmap phase only after validating any additional environment setup changes against the documented backend commands and CI path.
