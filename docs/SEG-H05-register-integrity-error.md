# SEG-H05 · Registration: email enumeration and race-condition 500

**Owner:** Equipo 3 · **Story:** Shortcut #72 · **Branch:** `fabianrdzh/sc-72/seg-h05-registro-enumeracion-de-emails-y` → `equipo3`

## Problem

`POST /api/v1/auth/register` had two related issues:

1. The `400` response for a duplicate email says `"El email ya está registrado"`,
   so the endpoint reveals whether an email has an account (email enumeration).
2. Two simultaneous registrations with the same email can both pass the
   `get_by_email` pre-check. The second `INSERT` then violates the unique index
   on `users.email`, and the unhandled `IntegrityError` ends in `500`.

The story originally pointed at `app/api/v1/auth.py`, but ARQ-04 moved the
registration use case to `AuthService`. The fix follows that architecture: the
endpoint stays thin, the service translates the database error, and the
repository owns the transaction.

## Decision: email enumeration is accepted on registration

The explicit `400` is kept and documented instead of returning a generic
success response. Rationale:

- The frontend needs a clear "email already registered" message to send the
  user to login or password recovery.
- Login already returns the same `401` for an unknown email and a wrong
  password (SEC-04), so the main credential-checking flow does not enumerate.
- Registration is rate-limited to 5 attempts per 60 seconds per client IP,
  which bounds automated probing.
- The response only reveals account existence; it never exposes the password
  hash, task data, or any other account detail.
- A generic response would change the current API contract and the
  characterization tests in `tests/api/test_auth_api.py`.

This decision is recorded in the `register` docstring in
`app/api/v1/auth.py` and in this document.

## Solution

- `app/services/auth_service.py`: `AuthService.register` now catches
  `sqlalchemy.exc.IntegrityError` from `UserRepository.add` and raises
  `EmailAlreadyRegistered` (HTTP 400, `code=email_already_registered`). The
  pre-check remains for the common case; the unique index is the source of
  truth for the race.
- `app/repositories/user_repository.py`: `UserRepository.add` rolls back the
  failed transaction before re-raising `IntegrityError`, so the session remains
  usable after the constraint violation.
- `app/api/v1/auth.py`: no database logic added. Its `register` docstring now
  states that the explicit `400` is intentional (accepted enumeration) and
  that the race is handled by the service.

Flow for the losing request:

1. Both requests pass `get_by_email` (no user yet).
2. The winner commits the new user.
3. The loser's `commit` raises `IntegrityError`.
4. `UserRepository.add` rolls back and re-raises.
5. `AuthService.register` raises `EmailAlreadyRegistered`.
6. The domain error handler answers `400` with
   `{"detail": "El email ya está registrado", "code": "email_already_registered"}`.

## Files

- Modified: `app/services/auth_service.py`, `app/repositories/user_repository.py`,
  `app/api/v1/auth.py` (docstring), `tests/services/test_auth_service.py`,
  `tests/security/README.md`, `README.md`
- New: `tests/security/test_register_integrity.py`,
  `docs/SEG-H05-register-integrity-error.md`

## Tests

- `tests/security/test_register_integrity.py::test_integrity_error_on_register_is_400`
  simulates the losing request by monkeypatching `UserRepository.add` to raise
  `IntegrityError`; the endpoint answers `400` with
  `code=email_already_registered`, not `500`.
- `tests/services/test_auth_service.py::test_register_race_rolls_back_session`
  bypasses the pre-check once to trigger the real unique constraint, asserts
  `EmailAlreadyRegistered`, and then queries the same session again. That last
  query proves the repository rolled back instead of leaving a failed
  transaction.
- `tests/api/test_auth_api.py::test_register_duplicate_email_is_400` (TEST-02)
  remains unchanged and still covers the sequential duplicate case.

## Verification

- `pytest tests/security/test_register_integrity.py tests/services/test_auth_service.py -q`
  → **7 passed**.
- `pytest -q` → **215 passed**.
- `mypy` → **Success: no issues found in 30 source files**.

## Notes and risks

- Catching `IntegrityError` in `AuthService.register` would also translate any
  future constraint violation on the `users` table into a `400`. Today the
  table only has the primary key and the unique email index, so the mapping is
  accurate. If another constraint is added, narrow the catch or inspect
  `exc.orig` before translating.
- The explicit rollback is required for callers that reuse the session after a
  failed `add` (the service test does). The request-scoped session still closes
  at the end of the dependency, as before.
- `ERR-02` can centralize the error body format later; this story does not
  change the response shape, only the status code for the race.
