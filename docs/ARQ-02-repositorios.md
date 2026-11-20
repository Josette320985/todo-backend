# ARQ-02 · Repositorios

**Responsable:** Ángel Quezada · **Historia:** Shortcut #47 · **Rama:** `arq-02-repositorios` → `equipo3`

## Problema

Los endpoints (`app/api/v1/tasks.py`, `auth.py` y `app/api/deps.py`) armaban y
ejecutaban sus propias consultas SQL. La misma consulta ("la tarea X si es del
usuario Y") estaba copiada en dos lugares, y cualquier mejora a una consulta
(orden, paginación, un DELETE más eficiente) había que hacerla endpoint por
endpoint. Si a alguien se le olvidaba el filtro por dueño, un usuario podía ver
o borrar tareas de otro.

## Solución: patrón Repository

Todas las consultas viven ahora en `app/repositories/`. Los endpoints piden lo
que necesitan y no saben cómo se obtiene.

| Repositorio | Métodos |
|---|---|
| `TaskRepository` | `list_by_owner(owner_id, limit, offset)`, `get_owned(task_id, owner_id)`, `add(task)`, `delete_owned(task_id, owner_id) -> bool` |
| `UserRepository` | `get_by_id`, `get_by_email`, `add` |

- Cada lectura y borrado de tareas filtra por dueño **dentro del repositorio**.
  La tarea de otro usuario se trata igual que una que no existe (404).
- Se inyectan con `Depends(get_task_repository)` y `Depends(get_user_repository)`.
  FastAPI reutiliza la misma sesión de base de datos durante toda la petición.

## Comportamiento: sin cambios (decisión)

ARQ-02 es solo una mudanza. La API responde exactamente igual y las pruebas de
caracterización de TEST-02 pasan sin tocarlas. Las mejoras que dependen de esta
historia quedan para sus propias historias, ya ubicadas en un solo lugar:

| Historia | Dónde se hace ahora |
|---|---|
| OPT-02 · Orden determinista | `TaskRepository.list_by_owner` |
| OPT-03 · Quitar `db.refresh()` | `TaskRepository.add` |
| OPT-04 · DELETE en una consulta | `TaskRepository.delete_owned` |
| SEG-H12 · Paginación | `list_by_owner` ya acepta `limit`/`offset`; falta exponerlos en `GET /tasks` |

## Archivos

- Nuevos: `app/repositories/__init__.py`, `task_repository.py`, `user_repository.py`,
  `tests/test_repositories.py`
- Modificados: `app/api/v1/tasks.py`, `app/api/v1/auth.py`, `app/api/deps.py`

## Pruebas

- `tests/api/` (TEST-02): sin cambios y en verde. Demuestra que el comportamiento no cambió.
- `tests/test_repositories.py`: cada método de los dos repositorios, incluido que
  no se pueden leer ni borrar tareas de otro usuario.
- **Criterio de aceptación:** `test_no_queries_in_api_layer` falla si alguien vuelve a escribir
  `select(`, `db.execute` o `db.delete` dentro de `app/api`. Es el mismo `grep` de la historia,
  pero automatizado en la CI.

## Pendiente

- `logout` guarda el cambio de `token_version` con `UserRepository.add`, que también hace un
  `refresh` innecesario. Es inofensivo y se puede limpiar junto con OPT-03.
- Las reglas de negocio (validar rango de fechas, campos permitidos al editar) siguen en el
  endpoint. Moverlas a servicios es ARQ-04, de otro integrante.
