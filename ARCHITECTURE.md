# Arquitectura del backend

API de tareas en FastAPI con SQLAlchemy async y SQLite. Este documento dice
**dónde va cada cosa**; revísalo en cada PR (ARQ-10).

## Capas

```text
HTTP ─► app/api/v1/        routers: auth, rate limiting, códigos HTTP
           │  Depends(...)  (app/api/deps.py arma servicios y repositorios)
           ▼
        app/services/      reglas de negocio, sin FastAPI
           │
           ▼
        app/repositories/  consultas SQLAlchemy, siempre filtradas por owner_id
           │
           ▼
        app/models/        tablas ORM ── migrations/ (Alembic) es el dueño del esquema
```

Transversal: `app/core/` (config, errores de dominio, seguridad, logging,
fechas, emails) y `app/schemas/` (Pydantic de entrada y salida).

## Reglas

1. **Las dependencias solo bajan.** Un router llama a un servicio, un servicio
   a un repositorio. Nunca al revés, ni un router directo a la sesión de BD.
2. **Los servicios no conocen HTTP.** Nada de `fastapi` ni `HTTPException` en
   `app/services/`: lanzan `DomainError` (`NotFoundError`, `ValidationFailed`…)
   y `app/core/errors.py` los traduce a JSON. Lo verifica
   `tests/test_architecture.py`.
3. **El dueño de los datos se filtra en el repositorio.** Una tarea ajena se
   trata igual que una inexistente (404), sin filtrar si existe.
4. **El esquema solo cambia con una migración** en `migrations/versions/`.
   `create_all()` no se usa en la app.
5. **La configuración entra por `Settings`.** `create_app(settings)` recibe la
   suya. Los endpoints la leen con `Depends(get_settings)`, nunca de
   `os.environ`. Si es inválida, el arranque termina con una línea (ERR-09).
6. **Un error, un formato.** Toda respuesta de error sale de los handlers de
   `app/core/errors.py` (ERR-01/ERR-02), en español.
7. **Nada sensible en logs.** Pasa por `sanitize_for_log`; nunca tokens,
   contraseñas ni la `SECRET_KEY`.

## Dónde va el código nuevo

| Tipo de cambio | Dónde |
|---|---|
| Endpoint nuevo o cambio de ruta/status | `app/api/v1/<recurso>.py` |
| Regla de negocio (validar, limitar, decidir) | `app/services/<recurso>_service.py` |
| Consulta nueva a la BD | `app/repositories/<recurso>_repository.py` |
| Columna, tabla o índice | `app/models/` + migración nueva en `migrations/versions/` |
| Campo de entrada/salida de la API | `app/schemas/` |
| Error nuevo para el cliente | subclase de `DomainError` en `app/core/errors.py` |
| Variable de entorno | `Settings` en `app/core/config.py` + `.env.example` |
| Middleware, CORS, headers, health | `app/main.py` (`create_app`) |
| Hash, JWT, contraseñas | `app/core/security.py` |
| Prueba de API / servicio / regresión | `tests/api/`, `tests/services/`, `tests/security/` |
| Prueba de punta a punta con el frontend | `e2e/` (Playwright) |
| Decisión o evidencia de una historia | `docs/<ID>-<slug>.md` |

## Checklist de PR

- [ ] El cambio está en la capa que dice la tabla.
- [ ] `pytest` y `mypy` pasan (los corre `.github/workflows/backend-ci.yml`).
- [ ] Si tocaste el esquema, hay migración y `tests/test_migrations.py` pasa.
- [ ] Si agregaste una carpeta o regla, actualizaste este archivo.
