# ARQ-09 · API: PATCH and /auth/me

**Story:** Shortcut #54 · **Branch:** `fabianrdzh/sc-54/arq-09-api-patch-y-auth-me` → `equipo3`

## Summary

Task updates were only available through `PUT`, even though the handler already
applied a partial update. This story adds `PATCH /tasks/{task_id}` as the
canonical method and keeps `PUT` as a deprecated alias so the frontend can
migrate without a breaking change. It also adds `GET /auth/me` so UX-14 can show
the authenticated user's email in the navigation bar.

## Endpoints

| Method | Path | Response | Notes |
|---|---|---|---|
| `PATCH` | `/api/v1/tasks/{task_id}` | `TaskRead` | Canonical partial update. |
| `PUT` | `/api/v1/tasks/{task_id}` | `TaskRead` | Deprecated alias of `PATCH`. |
| `GET` | `/api/v1/auth/me` | `UserRead` | Public profile of the current user. |

## Behavior

- `PATCH` and `PUT` share the same handler and call `TaskService.update_task`.
  Only allowlisted fields explicitly present in the request are changed, and
  the combined start/end date validation keeps running in the service.
- The task id keeps the SQLite signed 64-bit bounds from SEG-H06 (`422` for an
  out-of-range id) on both methods.
- `PUT` is marked `deprecated: true` in the OpenAPI schema. No frontend code
  needs to change immediately.
- `GET /auth/me` uses the existing `get_current_user` dependency, which
  validates the JWT and the token version. It returns only `id` and `email`,
  never the password hash.
- CORS `allow_methods` now includes `PATCH` so a browser frontend can call the
  new endpoint from an allowed origin.

## Compatibility

There is no breaking change. Existing `PUT` clients keep working, and new
clients can move to `PATCH` at their own pace. UX-14 is unblocked by `/auth/me`.

## Tests

- `tests/api/test_arq09_api.py`: `PATCH` partial update, `PUT` alias, missing and
  out-of-range ids, invalid payloads, unauthenticated access, `/auth/me`
  response shape, and the OpenAPI deprecation flag.
- `tests/test_cors.py`: preflight allows `PATCH`.
- `tests/test_security_headers.py`: security headers also cover `PATCH`.
- `pytest -q` and `mypy` must pass before the PR.

## Files

- Modified: `app/api/v1/tasks.py`, `app/api/v1/auth.py`, `app/main.py`,
  `tests/test_cors.py`, `tests/test_security_headers.py`, `README.md`,
  `SECURITY_REPORT_ACTUALIZADO.md`.
- Added: `docs/ARQ-09-api-patch-y-auth-me.md`,
  `tests/api/test_arq09_api.py`.
