# OPT-03 · Quitar `db.refresh()` redundante en `POST` y `PUT`

**Responsable:** Ángel Quezada · **Historia:** Shortcut #107 · **Rama:** `opt-03-sin-refresh` → `equipo3`

## Problema

Después de guardar una tarea, `TaskRepository.add` hacía `commit()` y luego
`refresh()`. El `refresh` vuelve a leer la fila con un `SELECT`, pero no aporta nada:

- La fábrica de sesiones usa `expire_on_commit=False` (`app/db/session.py`), así que
  el objeto conserva sus valores después del `commit`.
- Al insertar, SQLAlchemy ya llena en el objeto el `id` generado y los valores por
  defecto de las columnas (`completed=False`, `description=None`, etc.).

Era una consulta extra en cada creación y cada edición.

## Solución

Se quitó el `refresh` de `TaskRepository.add`. Como ARQ-02 dejó el guardado en un
solo lugar, el cambio es de una línea y aplica a `POST`, `PUT` y `PATCH`.

## Resultado

| Endpoint | Antes | Después |
|---|---|---|
| `POST /tasks` | 3 consultas (usuario + INSERT + SELECT) | **2** (usuario + INSERT) |
| `PUT`/`PATCH /tasks/{id}` | 4 consultas (usuario + SELECT + UPDATE + SELECT) | **3** (usuario + SELECT + UPDATE) |

## Pruebas (`tests/test_opt03_no_refresh.py`)

- **Criterio de aceptación:** la respuesta de `POST` incluye `id` y `completed=false`
  sin el refresh, y se ejecutan exactamente 2 consultas sin ningún `SELECT` a `tasks`.
- `PUT` devuelve los valores actualizados con 3 consultas.
- Lo que responde `POST` coincide con lo que realmente quedó guardado (`GET /tasks`).

## Pendiente

- `UserRepository.add` (registro y logout) todavía hace `refresh`. Se dejó fuera porque
  la historia solo cubre tareas, y ese método lo acaba de modificar SEG-H05 (manejo de
  `IntegrityError`). Se puede quitar en una historia aparte con el mismo razonamiento.
