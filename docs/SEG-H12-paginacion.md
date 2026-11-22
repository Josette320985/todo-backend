# SEG-H12 · Sin paginación ni límite de tareas

**Responsable:** Ángel Quezada · **Historia:** Shortcut #79 · **Rama:** `seg-h12-paginacion` → `equipo3`
**Origen:** reporte de seguridad del equipo 3 (incluye OPT-07)

## Problema

- `GET /tasks` devolvía **todas** las tareas del usuario en una sola respuesta, sin tope.
- Un usuario podía crear tareas **sin límite**.

Juntos permiten un abuso sencillo: llenar la base con millones de tareas y hacer que
cada `GET /tasks` lea y serialice todas, gastando memoria y CPU del servidor
(denegación de servicio).

## Solución

### `GET /api/v1/tasks/`: paginación y filtro

| Parámetro | Valores | Por defecto |
|---|---|---|
| `limit` | 1 a 500 (`MAX_PAGE_SIZE`) | 500 |
| `offset` | 0 a 500 | 0 |
| `completed` | `true` / `false` | sin filtro |

- Un `limit` mayor al máximo (por ejemplo `limit=1000000`) responde **422** con el formato
  único de error (ERR-02). El servicio además recorta cualquier página al máximo.
- Las páginas siguen el orden de **OPT-02** (pendientes primero, por vencimiento, `id` como
  desempate). Sin ese orden fijo las páginas podrían repetir o saltarse tareas.
- `?completed=` (pedido en la historia para P5) filtra pendientes o completadas.

### `POST /api/v1/tasks/`: tope por usuario

- Máximo **500 tareas por usuario** (`MAX_TASKS_PER_USER`). La tarea 501 responde
  **409** con `code: "task_limit_reached"`.
- El tope es por usuario: los demás no se ven afectados, y borrar una tarea libera espacio.

### Compatibilidad con el frontend (decisión)

El tamaño máximo de página es **igual** al tope por usuario. Así, un cliente que no manda
parámetros (como el frontend actual) recibe todas sus tareas en una sola página y **no se
rompe nada**. La respuesta sigue siendo una lista, igual que antes.

## Capas (ARQ-02 / ARQ-04)

| Capa | Cambio |
|---|---|
| `app/api/v1/tasks.py` | Parámetros `limit`, `offset` y `completed` con validación (`Query`) |
| `app/services/task_service.py` | `MAX_TASKS_PER_USER` y `MAX_PAGE_SIZE`; recorta la página y aplica el tope al crear |
| `app/repositories/task_repository.py` | Filtro `completed` en `list_by_owner`; nuevo `count_by_owner` |
| `app/core/errors.py` | Nueva excepción de dominio `TaskLimitReached` (409) |

## Pruebas (`tests/test_segh12_pagination.py`)

- **Criterio:** `?limit=1000000` → 422. También `limit=0`, `limit=-1`, `offset=-1` y un `offset` gigante.
- **Criterio:** crear más tareas que el tope → **409**, sin afectar a otros usuarios.
- Sin parámetros se devuelven todas las tareas (compatibilidad con el frontend).
- Las páginas `limit=2` cubren la lista completa sin huecos ni repetidos.
- `?completed=true/false` filtra correctamente.
- La paginación nunca muestra tareas de otro usuario.
- Borrar una tarea libera espacio bajo el tope.

`tests/test_opt03_no_refresh.py` se actualizó: `POST` ahora hace 3 consultas (usuario +
`COUNT` del tope + `INSERT`). Sigue sin haber `refresh`, porque el `INSERT` es la última consulta.

## Pendiente

- **Frontend** (`TaskList.tsx`): la historia pide adaptarlo para pedir páginas y mostrar el
  error 409. Se deja para hacerlo junto con **UX-07/UX-08** (mismo responsable), después de
  que **ARQ-07** (Andre) reestructure `TaskList`, para no chocar con ese refactor. Mientras
  tanto el frontend actual funciona sin cambios.
- **Carrera en el tope:** dos `POST` exactamente simultáneos del mismo usuario con 499 tareas
  podrían dejarlo en 501. Es un exceso mínimo y acotado; cerrarlo requeriría un bloqueo o
  un trigger en la base, que no se justifica para este riesgo.
- El costo de `POST` sube de 2 a 3 consultas por el `COUNT`, que usa el índice de OPT-01.
