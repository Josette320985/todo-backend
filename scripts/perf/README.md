# Benchmarks del backend (PERF-07)

Los scripts con los que se midieron las secciones 2 (consultas) y 3 (rendimiento)
de `tareas-equipo3.md`. Están aquí para que **cada PR de esas secciones pegue
su tabla antes/después**.

Todos usan una BD SQLite temporal con datos sembrados y la borran al terminar.
**Nunca tocan `data/todo.db`.** El esquema sale de las migraciones reales
(Alembic, ARQ-03).

| Script | Qué mide | Tiempo |
| --- | --- | --- |
| `bench.py` | En proceso: consultas SQL por endpoint, tamaño, plan y latencia de `GET /tasks`, bloqueo del event loop durante logins y PRAGMAs de SQLite | ~1 min con los valores por defecto (siembra 99k tareas) |
| `ab.sh` | Carga real: uvicorn + Apache Bench con 50 conexiones keep-alive. `/api/health`, `GET /tasks` y `GET /tasks` mientras 10 usuarios inician sesión | ~30 s |
| `prof.py` | `cProfile` de 1,000 `GET /tasks`: ms por request y reparto por librería | ~10 s |
| `seed.py` | Auxiliar de `ab.sh`: crea la BD sembrada e imprime `SECRET_KEY` y un token | — |

## Requisitos

Desde `todo-backend/`, con las dependencias de desarrollo instaladas:

```sh
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
```

`ab.sh` necesita además `ab` y `curl`. macOS ya los trae; en Debian o Ubuntu,
`sudo apt install apache2-utils`.

## Cómo correrlos

```sh
python scripts/perf/bench.py                 # 50 usuarios × 2000 tareas; el usuario 1 tiene 1000
python scripts/perf/bench.py --users 10 --tasks-per-user 200 --target-tasks 100   # versión rápida

scripts/perf/ab.sh                           # 1 worker
scripts/perf/ab.sh 4                         # 4 workers (PERF-03)
PORT=18300 CONCURRENCY=100 scripts/perf/ab.sh

python scripts/perf/prof.py                  # 1000 requests
python scripts/perf/prof.py --requests 3000 --top 25
```

Todos imprimen Markdown listo para pegar.

## Antes/después en un PR

Mide las dos versiones **en la misma máquina, una detrás de otra**, con el
mismo script. El script se toma de tu rama, porque `main`/`equipo3` puede no
tenerlo todavía. `git worktree` deja la versión base al lado sin cambiar de rama:

```sh
# Desde todo-backend/, en tu rama, con el venv activo
git worktree add /tmp/perf-base origin/equipo3

# Antes: el código base con los scripts de tu rama
mkdir -p /tmp/perf-base/scripts && cp -r scripts/perf /tmp/perf-base/scripts/
(cd /tmp/perf-base && scripts/perf/ab.sh)  > /tmp/antes.md

# Después: tu rama
scripts/perf/ab.sh > /tmp/despues.md

git worktree remove --force /tmp/perf-base
```

Para que la comparación valga:

- Corre cada versión **3 veces** y reporta la mediana. `ab` varía un 5–10 % entre corridas.
- Cierra lo que consuma CPU (builds, Docker, el navegador con muchas pestañas).
- No compares números de `bench.py` o `prof.py` (en proceso, sin red ni
  uvicorn) con los de `ab.sh`. Compara cada script solo consigo mismo.
- Si tu cambio requiere una migración nueva, ya va incluida: los scripts
  migran la BD al arrancar.

Plantilla para el PR:

```markdown
### Medición (`scripts/perf/ab.sh`, 1 worker, mediana de 3)
| Escenario | Antes | Después |
| --- | ---: | ---: |
| `/api/health` | 10,949 req/s | … |
| `GET /tasks` | 629 req/s · p95 131 ms | … |
| `GET /tasks` + 10 logins | 658 req/s · máx 430 ms | … |
```

## Qué cambió respecto a los scripts originales

Los originales vivían en `/tmp/pf-bench/` y estaban hechos para el código del
Equipo 2. Se adaptaron al código actual: `create_app(settings)`, migraciones
de Alembic, `token_version` y `create_access_token(sub, ver, settings)`.

- **`load.py` no se trajo.** Su cliente httpx se saturaba en ~200 req/s y medía
  al cliente, no al servidor (sección 3). Para carga se usa `ab.sh`. El sembrado
  que hacía pasó a `common.py`.
- **`bench.py` ya no prueba el rate limit.** En proceso no hay Nginx, así que no
  representa SEG-02. Eso lo cubre el flujo 5 del E2E (`e2e/`). Tampoco crea un
  índice temporal: `ix_tasks_owner_id` ya existe (OPT-01, migración 0003), así
  que se muestra el plan real.

`tests/test_perf_scripts.py` corre los tres scripts con datos mínimos en cada
CI, para que un refactor no los rompa sin que nadie se entere.
