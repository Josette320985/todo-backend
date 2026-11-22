# OPT-02 · Orden determinista en `GET /tasks`

**Responsable:** Ángel Quezada · **Historia:** Shortcut #106 · **Rama:** `opt-02-orden-determinista` → `equipo3`

## Problema

`GET /tasks` no tenía `ORDER BY`. Sin él, SQL no garantiza ningún orden: SQLite hoy
suele devolver por `id`, pero puede cambiar con un índice nuevo, un `VACUUM` o
cualquier cambio en el plan. Además:

- el frontend tenía que reordenar por su cuenta;
- la paginación (SEG-H12) es imposible sin orden fijo: las páginas podrían repetir o
  saltarse tareas.

## Solución

`TaskRepository.list_by_owner` ordena con `TASK_LIST_ORDER`:

```python
order_by(Task.completed, Task.end_date.is_(None), Task.end_date, Task.id)
```

1. **Pendientes primero**, completadas al final (`completed`: `false` < `true`).
2. Dentro de cada grupo, **por fecha de vencimiento**; las tareas **sin fecha van al final**
   (`end_date IS NULL`), porque SQLite pondría los `NULL` primero.
3. **`id` como desempate**, así nunca hay dos tareas "iguales" y el orden es total.

## Índice compuesto: evaluado y descartado

La historia pide evaluar un índice `(owner_id, completed, end_date)`. Se descartó:

- El plan actual sigue usando `ix_tasks_owner_id` para encontrar las tareas del usuario
  (se comprueba en `test_order_by_still_uses_owner_index`), y SQLite ordena en memoria
  solo las filas de ese usuario.
- Un índice compuesto **no** elimina ese ordenamiento, porque el orden incluye la
  expresión `end_date IS NULL`, que no está en ninguna columna del índice.
- Cada usuario tiene pocas tareas (y con SEG-H12 se leerán por páginas), así que ordenar
  en memoria es despreciable, mientras que otro índice encarece cada `INSERT`/`UPDATE`.

Conclusión: **nos quedamos con el índice de OPT-01**, como sugiere la historia.

## Pruebas (`tests/test_opt02_task_order.py`)

- Tareas creadas en desorden salen como: vence pronto → vence tarde → sin fecha (por id)
  → completadas.
- **Criterio de aceptación:** el orden es idéntico en 6 recargas seguidas.
- Marcar una tarea como completada la mueve al final.
- El `ORDER BY` se envía a la base y el plan sigue usando `ix_tasks_owner_id`.

## Coordinación

- **UX-10** (frontend, contador y filtros): el backend ya entrega la lista ordenada; el
  frontend no necesita reordenar.
- **Desbloquea SEG-H12** (paginación).
