# SEG-H06 · `task_id` gigante devuelve 500

**Responsable:** Equipo 3 · **Historia:** Shortcut #73 · **Rama:** `fabianrdzh/sc-73/seg-h06-task-id-gigante-devuelve-500` → `equipo3`

## Problema

SQLite guarda `INTEGER` como un entero con signo de 64 bits. Si la ruta trae un
`task_id` mayor que `2**63 - 1`, el driver de SQLite no puede convertirlo,
lanza `OverflowError` y la API responde **500**.

Ejemplo confirmado:

```text
PUT /api/v1/tasks/99999999999999999999  ->  500 Internal Server Error
```

Aplica a `PUT /tasks/{task_id}` y `DELETE /tasks/{task_id}`: ambos pasan el id
directamente a la consulta.

## Solución

El parámetro de ruta se declara con los límites que SQLite puede manejar:

```python
TaskId = Annotated[int, Path(ge=1, le=2**63 - 1)]
```

y se usa en los dos endpoints:

```python
async def update_task(task_id: TaskId, ...)
async def delete_task(task_id: TaskId, ...)
```

FastAPI valida la ruta **antes** de ejecutar el handler, así que un id fuera de
rango se rechaza con **422** y nunca llega a SQLite. El límite inferior
(`ge=1`) también descarta ids que no pueden existir (`0` y negativos).

## Comportamiento

| Caso | Antes | Ahora |
|---|---|---|
| `PUT /tasks/99999999999999999999` | 500 | **422** |
| `DELETE /tasks/99999999999999999999` | 500 | **422** |
| `PUT /tasks/9223372036854775807` (`2**63 - 1`) | 404 | 404 (consulta válida, no existe) |
| `PUT /tasks/0` o `/tasks/-1` | 404 | **422** (no puede existir) |
| Id normal existente | 200/204 | Sin cambios |

El 422 es el de validación de FastAPI (`{"detail": [...]}`). ERR-02 lo
unificará con el resto de errores; este cambio no adelanta ese formato.

## Archivos

- `app/api/v1/tasks.py`: alias `TaskId` con `Path(ge=1, le=2**63 - 1)` y su uso
  en `update_task` y `delete_task`; docstrings actualizados.
- `tests/security/test_task_id_bounds.py`: pruebas del 422 en `PUT`/`DELETE`,
  del límite máximo (`2**63 - 1` → 404, no 500), de `0`/negativos y un control
  con un id válido.
- `tests/security/README.md`: SEG-H06 marcado como cubierto.
- `README.md`: descripción de `v1/tasks.py` con el límite.

## Pruebas

```bash
pytest tests/security/test_task_id_bounds.py -q
pytest tests/api -q
pytest -q
mypy app
```

Resultados esperados:

- `tests/security/test_task_id_bounds.py`: todas en verde.
- `tests/api`: TEST-02 sigue pasando sin cambios.
- `pytest -q`: suite completa en verde.
- `mypy app`: sin errores.

## Coordinación

- **OPT-03** y **OPT-04** modifican los mismos endpoints de `tasks.py`. Este
  cambio (P6) va primero para que sus ramas partan de un `tasks.py` estable.
- **ERR-02** reutiliza el handler de errores de dominio; el 422 de ruta seguirá
  siendo el de FastAPI hasta que esa historia lo unifique.
