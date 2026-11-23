# ERR-01 · Global exception handler

**Story:** Shortcut #117 · **Branch:** `fabianrdzh/sc-117/err-01-handler-global-de-excepciones` → `equipo3`

## Summary

`app/main.py` now registers two global handlers:

- `Exception` → HTTP 500 with the single ERR-02 error shape.
- `sqlalchemy.exc.OperationalError` → HTTP 503 with `Retry-After: 1`.

Both responses are user-facing Spanish messages and never include the exception
text, SQL statement, stack trace or internal paths.

## 500 response

```json
{
  "detail": "Ocurrió un error inesperado. Intenta de nuevo.",
  "code": "internal_error"
}
```

The handler logs the full traceback with the `app.request` logger, including the
request id, method and path. The same request id is returned in
`X-Request-ID`, so the line can be found in the log and quoted by the client.

Starlette installs the `Exception` handler in `ServerErrorMiddleware`, which is
outside the user middleware stack and re-raises after sending its response.
`RequestIdMiddleware` therefore catches unhandled exceptions and renders them
with the injected global handler, while the handler adds the security headers
itself. This keeps the 500 response consistent with every other response
(PERF-02/SEC-07) without leaking the exception through the ASGI transport.

## 503 response

```json
{
  "detail": "El servicio no está disponible temporalmente. Intenta de nuevo.",
  "code": "service_unavailable"
}
```

`OperationalError` means the database cannot serve the request right now. The
handler logs the event without exposing internals and tells the client to retry
after one second. Other `SQLAlchemyError` subclasses are not treated as outages:
a broken migration script or a bug still reaches the 500 path.

## Coordination

- ERR-02 defines the shared JSON shape; ERR-01 only adds the two catch-all
  cases.
- ERR-04 keeps the `X-Request-ID` correlation: the id is generated or reused by
  `RequestIdMiddleware`, then reattached by the 500 handler because it runs
  outside that middleware.
- `/api/health/ready` keeps its own ERR-05 probe; it does not go through these
  handlers because it catches database failures locally.

## Tests

- `tests/test_error_handlers.py`: a test endpoint raises `RuntimeError` and
  checks the exact 500 body, request id, security headers, generic message and
  traceback in the log; another endpoint raises `OperationalError` and checks
  the 503 body, `Retry-After`, security headers and absence of internal details.
- `tests/test_request_id.py` and `tests/test_security_headers.py` still cover
  the existing correlation and header criteria.
- Full suite and `mypy` must pass before the PR.
