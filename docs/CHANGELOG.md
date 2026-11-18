# Changelog

All notable changes made by Team 3 are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Each entry names the
finding ID and the team member block (P1-P8) responsible for it.

## [Unreleased]

### Added

- Documentation folder, contributing guide and this changelog (P3).
- `docs/deployment.md`: local setup and production requirements (HTTPS and
  HSTS, `ENVIRONMENT=production`, unique `SECRET_KEY`) (SEG-H13, P3).
- `docs/team3/p3-docker-nginx.md`: P3 report with findings, evidence and
  pending items (P3).
- `commit-msg` Git hook that enforces Conventional Commits and requires a
  documentation change in every commit that touches code (P3).
- `commit-rules` GitHub Actions workflow that runs the same checks on every
  pull request (P3).

### Security

- SEG-H01: `.dockerignore` keeps `.env`, `.git`, the SQLite database and
  local caches out of the backend image (P3).
- SEG-H07: API docs (`/api/docs`, `/api/redoc`, `/api/openapi.json`) are
  only published when `ENVIRONMENT` is `development`, compared
  case-insensitively. Any other value disables them (P3).

### Tests

- SEG-H07: `tests/test_api_docs.py` covers docs exposure per environment and
  checks that the docs routes return 404 outside development (P3).

### Changed

- `.env.example` explains which `ENVIRONMENT` values publish the API docs
  (SEG-H07, P3).
- `docker-compose.yml` publishes the frontend on `127.0.0.1:3000` instead of
  every interface, so the plain-HTTP app is not exposed to the network
  (SEG-H13, P3).
