# ARQ-03 · Migraciones con Alembic

**Responsable:** Ángel Quezada · **Historia:** Shortcut #48 · **Rama:** `arq-03-alembic` → `equipo3`

## Problema

El esquema se creaba con `Base.metadata.create_all()` al arrancar. `create_all` crea
tablas que faltan, pero **nunca agrega columnas ni índices a tablas que ya existen**.
Por eso SEG-H10 tuvo que agregar `users.token_version` con un parche manual
(`add_token_version_column`) que corría en cada arranque, y lo mismo pasaría con el
índice de OPT-01 y con cualquier cambio futuro.

## Solución

El esquema ahora lo controlan migraciones versionadas de Alembic.

| Revisión | Cambio |
|---|---|
| `0001` | Esquema inicial (users, tasks) tal como lo entregó el Equipo 1 |
| `0002` | `users.token_version` (SEG-H10). Idempotente: no falla si el parche anterior ya la agregó |
| `0003` | Índice `ix_tasks_owner_id` (OPT-01) |

- La app migra sola al arrancar (`app/db/migrations.py`, llamado desde el `lifespan`
  de `create_app`). Funciona igual en Docker, en local y en cada prueba.
- **Bases existentes** (tienen tablas pero no `alembic_version`): se marcan con
  `stamp 0001` y luego `upgrade head`. No se recrea ninguna tabla ni se pierden datos.
- `render_as_batch=True`, porque SQLite no soporta la mayoría de los `ALTER TABLE`.
- Se eliminaron `create_all` y `add_token_version_column` de `app/main.py`.
- `Task.owner_id` ahora tiene `index=True`, para que el modelo y la migración coincidan.

## Archivos

- Nuevos: `alembic.ini`, `migrations/env.py`, `migrations/script.py.mako`,
  `migrations/versions/0001…0003`, `app/db/migrations.py`, `tests/test_migrations.py`
- Modificados: `app/main.py`, `app/models/task.py`, `requirements.txt` (+`alembic`)

## Cómo agregar un cambio de esquema a partir de ahora

1. Modifica el modelo en `app/models/`.
2. `alembic revision --autogenerate -m "descripcion"` y revisa el archivo generado.
3. Corre `pytest`. `test_models_match_migrations` falla si el modelo y las migraciones no coinciden.

## Pruebas (`tests/test_migrations.py`)

- Base nueva: se crean las tablas, el índice y queda en la revisión `head`.
- **Criterio de aceptación:** una base con el esquema viejo y datos queda en `head`, con
  el índice y con sus datos intactos.
- Base que ya tenía el parche de SEG-H10: migra sin error.
- Reiniciar la app no vuelve a aplicar nada.
- La API funciona sobre el esquema migrado.
- Los modelos y las migraciones coinciden (detecta migraciones olvidadas).

## Desbloquea

- **OPT-01**: el índice ya existe (migración 0003). Solo queda medir y documentar la mejora.
- **SEG-H10**: su columna ya queda bajo migración; se puede quitar el parche.

## Pendiente / notas

- Una base creada por `create_all` *después* de SEG-H10 y antes de esta rama ya tiene
  `token_version`. La migración 0002 lo detecta y no la vuelve a agregar.
- Si se corren varios workers de uvicorn, todos intentarían migrar al mismo tiempo. Hoy
  se usa un solo proceso. Si eso cambia, hay que mover la migración a un paso previo
  (`alembic upgrade head && uvicorn …`).
