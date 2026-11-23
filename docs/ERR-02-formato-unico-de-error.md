# ERR-02 · Single error format, in Spanish

**Story:** Shortcut #118 · **Branch:** `fabianrdzh/sc-118/err-02-un-solo-formato-de-error-en-espanol` → `equipo3`

## Summary

Every API error now uses one JSON shape:

```json
{
  "detail": "Mensaje para el usuario",
  "code": "validation_error",
  "errors": [
    { "field": "title", "message": "El título es obligatorio" }
  ]
}
```

`detail` is still a plain string, so the current frontend keeps working. The
`errors` array is only present for validation failures. All user-facing text is
in Spanish.

## Handlers in `app/core/errors.py`

- `RequestValidationError`: translates Pydantic error types (`missing`,
  `string_too_short`, `string_too_long`, `value_error`, `json_invalid`, date and
  number parsing, `greater_than_equal`, `less_than_equal`, ...) into Spanish
  messages. It removes the `Value error, ` prefix and maps invalid emails to a
  Spanish message. Field names are labeled in Spanish inside the message while
  `errors[].field` keeps the API field name.
- `StarletteHTTPException`: translates `Not Found`, `Method Not Allowed` and
  `Not authenticated` (plus other common statuses) into the same shape and
  preserves headers such as `WWW-Authenticate: Bearer`.
- `DomainError`: unchanged. `SEG-H05` duplicate email (`400`,
  `email_already_registered`) and `ValidationFailed` (`422`,
  `validation_error`) already use this format.

## Task date errors

A combined date-range failure keeps returning HTTP 422 with
`code: "validation_error"` and `errors[0].field == "end_date"`. The message comes
from the shared `date_range_error` rule, so the schema check and the service
check say exactly the same thing.

## Coordination

- `SEG-H05` and `SEG-H06` do not need separate error formats: their 400/422
  responses now flow through these handlers.
- `ERR-01` and `ERR-02` share `app/core/errors.py`; this change only adds the
  two framework handlers.

## Tests

- `pytest tests/test_error_handling.py -q` (extended by TEST-05 with the 401,
  409, 429, 500 and 503 rows): one parametrized test walks every case
  from the story table, checks the exact key set, code, detail, per-field
  messages, preserved auth header, and that no English text leaks into the
  user-facing strings.
- Full suite and `mypy` must pass before the PR.
