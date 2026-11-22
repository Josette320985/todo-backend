# OPT-01 · Índice en `tasks.owner_id`

**Responsable:** Ángel Quezada · **Historia:** Shortcut #105 · **Rama:** `opt-01-indice-owner-id` → `equipo3`

## Problema

Todas las consultas de tareas filtran por dueño (`WHERE tasks.owner_id = ?`). Sin
un índice en esa columna, SQLite recorre la tabla completa (`SCAN tasks`) en cada
`GET /tasks`, aunque el usuario solo tenga unas pocas tareas. El costo crece con
el total de tareas de **todos** los usuarios.

## Solución

El índice ya existe desde ARQ-03:

- Modelo: `Task.owner_id = mapped_column(ForeignKey("users.id"), index=True)`.
- Migración `0003_tasks_owner_id_index.py`: `CREATE INDEX ix_tasks_owner_id`.
  Las bases existentes lo reciben solas al arrancar la app, sin perder datos.

Lo que agrega esta historia es la **prueba del criterio de aceptación**.

## Criterio de aceptación

> `EXPLAIN QUERY PLAN` muestra `SEARCH tasks USING INDEX`.

`tests/test_opt01_owner_index.py` toma **la consulta real** que ejecuta `GET /tasks`
(la captura con `count_queries`) y revisa su plan:

| Caso | Plan de SQLite |
|---|---|
| Con el índice (estado actual) | `SEARCH tasks USING INDEX ix_tasks_owner_id (owner_id=?)` |
| Sin el índice (antes de ARQ-03/OPT-01) | `SCAN tasks` |

Si alguien borra el índice o cambia la consulta de forma que ya no lo use, la
primera prueba falla.

## Coordinación con OPT-05

La historia sugería una sola PR de base de datos junto con OPT-05 (PRAGMAs de
SQLite, de Elias Cardona). Como el índice ya llegó con la migración de ARQ-03,
OPT-01 queda independiente y OPT-05 puede ir en su propia PR sin conflicto.

## Archivos

- Nuevos: `tests/test_opt01_owner_index.py`, `docs/OPT-01-indice-owner-id.md`
- Sin cambios de código de la aplicación.
