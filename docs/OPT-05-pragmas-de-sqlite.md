# OPT-05 · Configurar SQLite al conectar

**Responsable:** Elias Cardona · **Rama:** → `equipo3`
**Desbloquea:** PERF-03 (WAL para que varios procesos usen SQLite)

## Problema

SQLite arranca cada conexión con valores de fábrica: sin WAL, una escritura
bloquea las lecturas; `synchronous` en FULL hace cada escritura más lenta de lo
necesario con WAL; y `foreign_keys` viene **apagado**, así que la base nunca
verificaba las llaves foráneas y el `cascade` de `User.tasks` solo funcionaba
por el ORM.

## Solución

`app/db/session.py`: un listener `connect` en `engine.sync_engine`, solo si el
dialecto es SQLite, que ejecuta en cada conexión nueva:

| PRAGMA | Para qué |
|---|---|
| `journal_mode=WAL` | Las lecturas no se bloquean mientras se escribe. El modo queda guardado en el archivo de la base, así que solo cambia la primera vez |
| `synchronous=NORMAL` | Seguro con WAL (un corte de luz puede perder las últimas transacciones, no corromper el archivo) y más rápido al escribir |
| `foreign_keys=ON` | La base rechaza filas huérfanas. Es **por conexión**, por eso va en el listener |

El listener usa el cursor del DBAPI, fuera de SQLAlchemy: los PRAGMAs no
aparecen en `count_queries` ni en los logs de consultas.

### Cambio necesario en las migraciones

Con `foreign_keys=ON`, la migración `0002` (que hace `batch_alter_table("users")`)
**falla** en una base con datos: Alembic copia `users` a una tabla temporal, hace
`DROP TABLE users` y renombra la copia, y SQLite no deja borrar `users` mientras
`tasks` apunta a ella (`FOREIGN KEY constraint failed`). Lo comprobé con `sqlite3`
puro, y es justo el caso "base anterior a Alembic con datos" de ARQ-03.

La receta de SQLite para alterar tablas es apagar las llaves foráneas durante
la migración. Por eso:

- `run_migrations` (`app/db/migrations.py`) ejecuta `PRAGMA foreign_keys=OFF` al
  empezar, solo en SQLite. Funciona porque aún no hay escrituras en la
  transacción: SQLite ignora ese PRAGMA dentro de una transacción.
- No se puede volver a encender desde ahí (la transacción ya tiene escrituras),
  así que `migrate` (`app/main.py`) hace `await engine.dispose()` al terminar: la
  conexión usada se cierra y las siguientes salen del listener, con las llaves
  foráneas encendidas.

## Comportamiento que cambia

- Insertar una tarea con un `owner_id` que no existe ahora falla con
  `IntegrityError`.
- Borrar un usuario con tareas **con SQL directo** falla (la llave no tiene
  `ON DELETE CASCADE`). Por el ORM sigue funcionando, porque `cascade="all,
  delete-orphan"` borra primero las tareas. Hoy la aplicación no tiene
  endpoint para borrar usuarios.
- Aparecen los archivos `*.db-wal` y `*.db-shm` junto a la base.

## Limitaciones y riesgos

- **Respaldos:** copiar solo `todo.db` con la aplicación en marcha puede perder
  las últimas escrituras, que viven en el `-wal`. Hay que copiar los tres
  archivos, o usar `sqlite3 todo.db ".backup copia.db"`.
- **Docker Desktop (Mac y Windows):** WAL usa memoria compartida en el archivo
  `-shm`, y SQLite advierte que no funciona sobre sistemas de archivos de red.
  El `./data:/app/data` de compose es una carpeta del anfitrión; en Linux no hay
  problema, pero en Docker Desktop puede dar `disk I/O error` o `database is
  locked`. Si pasa, un volumen con nombre en vez de la carpeta lo evita.
- Una base con filas huérfanas anteriores sigue leyéndose bien; solo fallaría
  al modificar esas filas. `PRAGMA foreign_key_check` las lista.
- Un `ON DELETE CASCADE` real en la llave `tasks.owner_id` sería una migración
  aparte (batch); no está en esta historia.

## Archivos

- Nuevos: `tests/test_opt05_sqlite_pragmas.py`, `docs/OPT-05-pragmas-de-sqlite.md`
- Modificados: `app/db/session.py`, `app/db/migrations.py`, `app/main.py`,
  `README.md`, `.gitignore`, `.dockerignore`

## Pruebas

- `tests/test_opt05_sqlite_pragmas.py`: WAL, `synchronous=NORMAL` y
  `foreign_keys=1` en la conexión de la app; en **cada** conexión nueva; la base
  rechaza una tarea con dueño inexistente y el borrado de un usuario con tareas
  por SQL; el borrado por el ORM sigue eliminando sus tareas; una base anterior a
  Alembic con datos migra y, después, las conexiones vuelven a tener las llaves
  foráneas encendidas.
- Criterio de aceptación: `python scripts/perf/bench.py` imprime, en la sección
  SQLite, `journal_mode=wal, foreign_keys=1` (y `synchronous=1`).