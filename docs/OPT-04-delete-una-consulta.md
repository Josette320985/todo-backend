# OPT-04 · `DELETE` en una sola consulta

**Responsable:** Ángel Quezada · **Historia:** Shortcut #108 · **Rama:** `opt-04-delete-una-consulta` → `equipo3`

## Problema

`TaskRepository.delete_owned` primero cargaba la tarea (`SELECT ... WHERE id = ? AND
owner_id = ?`) y luego la borraba con `db.delete()` (`DELETE ... WHERE id = ?`). Eran
dos viajes a la base para algo que se resuelve con uno.

## Solución

Un solo `DELETE` con la verificación de dueño dentro del `WHERE`:

```python
delete(Task).where(Task.id == task_id, Task.owner_id == owner_id)
```

Si `rowcount == 0` (la tarea no existe o es de otro usuario), el método regresa
`False` y el servicio responde **404**, igual que antes. El control de acceso no cambia:
la tarea de otro usuario simplemente no coincide con el `WHERE`.

## Resultado

| Endpoint | Antes | Después |
|---|---|---|
| `DELETE /tasks/{id}` | 3 consultas (usuario + SELECT + DELETE) | **2** (usuario + DELETE) |

## Pruebas (`tests/test_opt04_single_delete.py`)

- **Criterio de aceptación:** borrar la tarea de otro usuario devuelve **404** y la tarea
  sigue existiendo.
- El borrado hace exactamente 2 consultas y la última es `DELETE FROM tasks`.
- Borrar dos veces la misma tarea: la segunda vez da 404.
- Solo se borra la tarea indicada; las demás del usuario siguen ahí.
- Las pruebas de control de acceso existentes (`tests/security/test_access_control.py`) y de
  `test_repositories.py` siguen pasando sin cambios.

## Notas

- Es un `DELETE` "masivo" de SQLAlchemy: no pasa por los eventos ni cascadas del ORM. Las
  tareas no tienen tablas hijas, así que no hay nada que cascadear.
- Archivo modificado: `app/repositories/task_repository.py` (gracias a ARQ-02, el endpoint y
  el servicio no cambian).
