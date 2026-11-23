# SEG-H09 · Email normalization differs between registration and login

**Owner:** Equipo 3 · **Story:** Shortcut #76 · **Branch:** `fabianrdzh/sc-76/seg-h09-normalizacion-de-email-distinta-en` → `equipo3`

## Problem

Registration and login normalized the email differently:

- `UserCreate.email` used Pydantic `EmailStr` (email-validator), which applies
  Unicode normalization and converts an IDN/punycode domain to its Unicode
  form. The schema then applied `strip().lower()`.
- `AuthService.authenticate` only applied `email.strip().lower()`.

For most ASCII emails both paths produce the same value, but they diverge for
Unicode and IDN addresses:

| Input | Stored at registration | Login looked up |
|---|---|---|
| `user@bu\u0308cher.de` (decomposed) | `user@b\u00fccher.de` | `user@bu\u0308cher.de` |
| `user@xn--bcher-kva.de` (punycode) | `user@b\u00fccher.de` | `user@xn--bcher-kva.de` |

A user who registered with a decomposed Unicode email could not log in with the
same string, and a user who typed the punycode form could not reach an account
stored in Unicode form.

The story originally pointed at `app/api/v1/auth.py`, but ARQ-04 moved the login
use case to `AuthService`. The endpoint stays thin; the fix is in the service
and in the shared normalization module.

## Solution

### Shared function (`app/core/emails.py`)

`normalize_email(value)` is now the only email normalization rule:

1. Strip surrounding whitespace.
2. Validate with `email_validator.validate_email(..., check_deliverability=False)`.
3. Return `validated.normalized.lower()`.

`email-validator` handles Unicode normalization (NFC) and converts IDN/punycode
domains to their Unicode form. Lowercasing the local part preserves the API
contract that already treats emails as case-insensitive.

Invalid input raises `ValueError`; registration turns that into a Pydantic 422
and login treats it as an unknown account.

### Registration (`app/schemas/user.py`, `app/services/auth_service.py`)

- `UserCreate.email` is `Annotated[EmailStr, AfterValidator(normalize_email)]`,
  so the schema keeps the `EmailStr` format check and applies the shared
  normalization.
- `AuthService.register` also calls `normalize_email(payload.email)` before the
  duplicate check and the insert. The second call is idempotent and keeps the
  service correct if it is used outside the API.

### Login (`app/services/auth_service.py`, `app/api/v1/auth.py`)

- `AuthService.authenticate` calls `normalize_email(email)`.
- An invalid email sets the normalized value to `None`; the existing unknown
  account path runs (dummy bcrypt hash, failure log, `InvalidCredentials` 401).
  This avoids turning a malformed login into a 422 or 500.
- `app/api/v1/auth.py` only documents the behavior in the `login` docstring.

### Why the function is not in `auth_service.py`

`auth_service.py` already imports `UserCreate` from `app.schemas.user`. If the
schema imported the normalizer back from `auth_service.py`, the import would be
circular. `app/core/emails.py` is a neutral module that both layers can use.

## Files

- New: `app/core/emails.py`,
  `tests/security/test_email_normalization.py`,
  `docs/SEG-H09-email-normalization.md`
- Modified: `app/schemas/user.py`, `app/services/auth_service.py`,
  `app/api/v1/auth.py` (docstring), `tests/security/README.md`, `README.md`

## Tests

- `tests/security/test_email_normalization.py::test_normalize_email_handles_unicode_and_idn`
  checks ASCII case/space normalization, decomposed Unicode (NFC), and
  punycode-to-Unicode conversion.
- `tests/security/test_email_normalization.py::test_unicode_email_can_log_in`
  registers `user@bu\u0308cher.de` and logs in with the same decomposed string.
  This is the acceptance criterion.
- `tests/security/test_email_normalization.py::test_idn_punycode_login_matches_unicode_registration`
  registers the Unicode form and logs in with the punycode form.
- `tests/security/test_email_normalization.py::test_invalid_email_login_is_401`
  verifies that malformed login input still gets the generic 401.
- `tests/api/test_auth_api.py` (TEST-02) remains unchanged: registration still
  normalizes `User@Example.COM` to `user@example.com`, and login remains
  case-insensitive.

## Verification

- `pytest tests/security/test_email_normalization.py tests/api/test_auth_api.py tests/services/test_auth_service.py -q`
  → **22 passed**.
- `pytest -q` → **219 passed**.
- `mypy` → **Success: no issues found in 31 source files**.

## Notes and risks

- The local part is lowercased, as it already was at registration. Changing to
  case-sensitive local parts would be a separate API change.
- IDN/punycode and composed/decomposed variants collapse to the same stored
  Unicode form, so the existing unique email index also catches duplicates
  written in a different representation.
- Invalid login emails are treated as unknown accounts (401 + dummy hash) to
  keep the response generic and the timing comparable.
- `UserRead.email` is unchanged; the stored value is already canonical.
- If `email-validator` changes its normalization rules in a future version, both
  registration and login change together because they share this function.
