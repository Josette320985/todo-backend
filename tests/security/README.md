# Security regression suite (TEST-03)

Every acceptance criterion in the Team 3 security report
(`reporte-seguridad-equipo3`) becomes a test. The person who fixes a
finding writes its test (report section 1) and ticks it here in the same
pull request.

Run only this suite:

```bash
pytest tests/security
```

## What already works (report section 4)

These behaviours were verified by the audit. The tests keep the refactor
from breaking them.

| Behaviour | Test |
|---|---|
| SQL payload `x' OR 1=1; DROP TABLE tasks;--` is stored verbatim | `test_injection_payloads.py::test_sql_payload_is_stored_verbatim` |
| The payload does not alter the tables | `test_injection_payloads.py::test_sql_payload_does_not_alter_tables` |
| SQL payload in login is a normal 401 | `test_injection_payloads.py::test_sql_payload_in_login_is_rejected` |
| 4 XSS payloads are stored and returned as JSON text | `test_injection_payloads.py::test_xss_payload_is_returned_as_json_text` |
| 11 kinds of invalid JWT are rejected (alg `none`, HS512, wrong key, no `exp`, expired, no `sub`, non-numeric `sub`, unknown user, `nbf` in the future, tampered payload, not a JWT) | `test_jwt_rejection.py::test_invalid_token_is_401` |
| A valid token is accepted (control) | `test_jwt_rejection.py::test_valid_token_is_accepted` |
| Unknown email and wrong password give the same response | `test_auth_hardening.py::test_unknown_email_and_wrong_password_look_the_same` |
| `owner_id` and `id` in the body are ignored | `test_access_control.py::test_create_ignores_owner_id_and_id`, `test_update_ignores_owner_id_and_id` |
| Another user gets 404 when reading, editing or deleting | `tests/api/test_tasks_api.py::test_other_user_cannot_see_update_or_delete` (TEST-02) |
| Passwords over 72 UTF-8 bytes are rejected (SEC-04) | `test_auth_hardening.py::test_password_over_72_bytes_is_rejected`, `test_login_with_password_over_72_bytes_is_401` |
| Register never returns the password or its hash | `test_auth_hardening.py::test_register_response_never_exposes_password` |
| API security headers on 200 and 401 responses (SEC-07) | `test_auth_hardening.py::test_security_headers_on_api_responses` |

## Findings to fix (report sections 6 and 7)

`[x]` means a test exists and passes. Tests that need Docker or a browser
belong to the E2E suite (TEST-09) or the CI (TEST-10).

| ID | Acceptance criterion | Owner | Test |
|---|---|---|---|
| SEG-01 | `Settings(SECRET_KEY=<example>)` raises `ValidationError`; a token signed with the example key gets 401 | P1 | [x] `tests/test_config.py::test_rejects_weak_or_example_secret_key`, `test_example_secret_key.py::test_token_signed_with_example_key_is_401` |
| SEG-02 | After 10 failures from client A, client B logs in; a forged `X-Forwarded-For` does not change the IP | P2 | [ ] pending (E2E, TEST-09) |
| SEG-H01 | The backend image has no `.env`, `.git` or `data/todo.db` | P3 | [ ] pending (Docker check in CI) |
| SEG-H02 | A 100 KB POST to `/api/v1/auth/login` gets 413 | P3 | [ ] pending (E2E, TEST-09) |
| SEG-H03 | `/api/health` answers during a login | P5 | [ ] pending (`slow`, TEST-06) |
| SEG-H04 | `pip-audit` clean; JWT tests still pass | P4 | [ ] pending (`pip-audit` in CI, TEST-10) |
| SEG-H05 | A simulated `IntegrityError` gets 400 | P6 | [x] `test_register_integrity.py::test_integrity_error_on_register_is_400`, `tests/services/test_auth_service.py::test_register_race_rolls_back_session` |
| SEG-H06 | `PUT /api/v1/tasks/99999999999999999999` gets 422 | P6 | [x] `test_task_id_bounds.py::test_put_out_of_range_task_id_is_422`, `test_delete_out_of_range_task_id_is_422` |
| SEG-H07 | `/api/openapi.json` gets 404 with `ENVIRONMENT=production` | P3 | [x] `test_api_docs.py::test_docs_are_404_outside_development`, `test_docs_are_served_in_development` |
| SEG-H08 | A login with `\x1b[31m` in the email is logged escaped | P8 | [x] `tests/test_log_sanitization.py::test_failed_login_logs_escaped_email` |
| SEG-H09 | A user registered with a Unicode email can log in | P6 | [x] `test_email_normalization.py::test_unicode_email_can_log_in`, `test_idn_punycode_login_matches_unicode_registration`, `test_invalid_email_login_is_401` |
| SEG-H10 | After logout, the previous token gets 401 | P8 | [x] `tests/test_logout.py::test_logout_revokes_previous_token`, `tests/test_token_version.py` |
| SEG-H11 | The browser console does not show `Authorization` | P7 | [ ] pending (frontend, TEST-08) |
| SEG-H12 | `?limit=1000000` gets 422 or is capped; creating past the cap gets 4xx | P5 | [ ] pending |
| SEG-H13 | HTTPS requirement documented; local port bound to `127.0.0.1` | P3 | [x] README "Deploying with HTTPS", `docker-compose.yml` on `127.0.0.1:3000`; HSTS behind a TLS proxy in `e2e/tests/04-headers-seguridad.spec.ts` (TEST-09) |
| SEG-H14 | `npm audit` with no high vulnerabilities; build and lint pass | P7 | [ ] pending (CI, TEST-10) |
| SEG-H15 | CORS without `allow_credentials` | P8 | [x] `tests/test_cors.py::test_allowed_origin_without_credentials` |
