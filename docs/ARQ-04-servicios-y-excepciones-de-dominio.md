# ARQ-04 · Servicios y excepciones de dominio

**Responsable:** Equipo 3 · **Historia:** Shortcut #49 · **Rama:** `fabianrdzh/sc-49/arq-04-servicios-y-excepciones-de-dominio` → `equipo3`

## Problema

Los endpoints todavía mezclaban tres responsabilidades: autenticar la petición,
aplicar reglas de negocio y decidir el código HTTP del error.

- `tasks.py` validaba el rango de fechas combinando los valores guardados con
  los del `PATCH`, y lanzaba `HTTPException` desde la capa de API.
- `auth.py` hacía la verificación de bcrypt, la normalización del email, el
  chequeo de duplicados y el logging del login fallido.
- Cada error se construía a mano (`HTTPException` con `detail`), así que
  ERR-01 y ERR-02 no tenían un punto único donde centralizar el formato.

## Solución

### Capa de servicios (`app/services/`)

| Servicio | Métodos | Reglas que concentra |
|---|---|---|
| `TaskService` | `list_tasks`, `create_task`, `update_task`, `delete_task` | Campos permitidos al editar y validación del rango de fechas combinando lo guardado con lo recibido |
| `AuthService` | `register`, `authenticate` | Chequeo de email duplicado, hash/verificación de bcrypt en hilo y logging del login fallido |

Los endpoints quedan delgados: autentican, aplican rate limiting y llaman al
servicio. Las dependencias nuevas (`get_task_service`, `get_auth_service`) viven
en `app/api/deps.py` y reutilizan los repositorios de ARQ-02 y la misma sesión
de base de datos de la petición.

### Excepciones de dominio (`app/core/errors.py`)

Los servicios ya no conocen códigos HTTP: lanzan `NotFoundError`,
`ValidationFailed`, `EmailAlreadyRegistered` o `InvalidCredentials`. Un único
handler las traduce a JSON:

| Excepción | HTTP | `code` | `detail` |
|---|---|---|---|
| `NotFoundError` | 404 | `not_found` | `Tarea no encontrada` (o el que reciba) |
| `ValidationFailed` | 422 | `validation_error` | el mensaje de la regla |
| `EmailAlreadyRegistered` | 400 | `email_already_registered` | `El email ya está registrado` |
| `InvalidCredentials` | 401 | `invalid_credentials` | `Credenciales incorrectas` + `WWW-Authenticate: Bearer` |

Cuerpo: `{"detail": "...", "code": "...", "errors": [{"field", "message"}]}`.
`errors` solo aparece en `ValidationFailed`. Este archivo es la base de ERR-01
(handler global) y ERR-02 (formato único): ambas historias solo agregan casos
aquí, sin tocar endpoints ni servicios.

### Validación de fechas compartida (`app/core/dates.py`)

`date_range_error(start, end)` devuelve el mensaje (o `None`) y lo usan tanto
`app/schemas/task.py` (validación de entrada) como `TaskService.update_task`
(validación contra los valores ya guardados). Una sola comparación y un solo
mensaje.

## Comportamiento: sin cambios (decisión)

ARQ-04 es una mudanza, no un cambio funcional. Las pruebas de caracterización
de TEST-02 (`tests/api/test_tasks_api.py` y `tests/api/test_auth_api.py`) pasan
**sin modificarlas**. Dos tests se ajustaron para apuntar a la nueva ubicación
del código, sin cambiar sus aserciones: `tests/test_bcrypt_offload.py` parchea
bcrypt en `app.services.auth_service`, y `tests/test_log_sanitization.py`
importa `sanitize_for_log` desde `app/core/logging`.

Lo que ARQ-04 **no** hace, a propósito, porque tiene su propia historia:

| Historia | Qué falta | Dónde se hará |
|---|---|---|
| SEG-H05 | Capturar `IntegrityError` en una carrera de registro | `AuthService.register` |
| SEG-H09 | Normalización de email compartida entre registro y login | `AuthService` |
| SEG-H03 / PERF-01 | Ya está: bcrypt corre en `asyncio.to_thread` | `AuthService` |

## Archivos

- Nuevos: `app/core/dates.py`, `app/core/errors.py`, `app/services/__init__.py`,
  `app/services/task_service.py`, `app/services/auth_service.py`,
  `tests/services/test_task_service.py`, `tests/services/test_auth_service.py`,
  `tests/test_architecture.py`
- Modificados: `app/api/v1/tasks.py`, `app/api/v1/auth.py`, `app/api/deps.py`,
  `app/core/logging.py` (`sanitize_for_log`), `app/main.py`,
  `app/schemas/task.py`, `tests/test_bcrypt_offload.py`, `README.md`

## Pruebas

- **Criterio de aceptación:** `grep -rn "fastapi" app/services` no devuelve
  nada. Se automatizó en `tests/test_architecture.py`, que falla si un archivo
  de `app/services` menciona FastAPI.
- `tests/services/test_task_service.py`: crear/listar, actualización parcial,
  rango de fechas combinado, tarea ajena o inexistente (404) y borrado.
- `tests/services/test_auth_service.py`: hash del password, email duplicado,
  credenciales válidas, password incorrecto y email inexistente (401 con
  `WWW-Authenticate`).
- `tests/test_bcrypt_offload.py`: sigue verificando que `/api/health` responde
  mientras bcrypt está bloqueado, ahora contra el servicio.
- `tests/test_log_sanitization.py`: mismas aserciones, importando
  `sanitize_for_log` desde `app/core/logging`.
- `pytest -q` → **206 passed**; `mypy app` → **Success: no issues found in 30
  source files**.

## Pendiente

- `logout` sigue usando `UserRepository` directamente; no es una regla de
  negocio de registro/login, pero puede moverse a `AuthService` junto con
  ARQ-05 (rate limiting por app) si conviene.
- ERR-02 todavía debe unificar el formato de los errores que **no** son de
  dominio (422 de Pydantic, 401 de `OAuth2PasswordBearer`, 429 del rate
  limiter, 500 del handler global). Hoy conservan el formato de FastAPI.
