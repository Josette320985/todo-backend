#!/usr/bin/env bash
# Load test with uvicorn + Apache Bench (PERF-07, section 3 "Carga real").
#
# Starts the CURRENT source with uvicorn on a throwaway database (20 users x
# 20 tasks), runs ab with 50 concurrent keep-alive connections and prints one
# Markdown table row per scenario:
#   - /api/health
#   - GET /api/v1/tasks/
#   - GET /api/v1/tasks/ while 10 users log in (bcrypt at production cost)
#
# Usage, from todo-backend/ with the dependencies installed (venv active):
#   scripts/perf/ab.sh [WORKERS]          # default 1
#   PORT=18300 scripts/perf/ab.sh 4
#
# ab, not a Python client: an httpx client capped at ~200 req/s and measured
# itself instead of the server (section 3). ab ships with macOS; on Debian or
# Ubuntu install apache2-utils.
set -euo pipefail

WORKERS="${1:-1}"
PORT="${PORT:-18200}"
CONCURRENCY="${CONCURRENCY:-50}"
PYTHON="${PYTHON:-python}"
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"

command -v ab >/dev/null || { echo "ab not found (macOS: built in; Debian/Ubuntu: apt install apache2-utils)" >&2; exit 1; }

TMP="$(mktemp -d "${TMPDIR:-/tmp}/perf-ab.XXXXXX")"
UVICORN_PID=""
cleanup() {
  if [ -n "$UVICORN_PID" ]; then
    kill "$UVICORN_PID" 2>/dev/null || true
    wait "$UVICORN_PID" 2>/dev/null || true
  fi
  rm -rf "$TMP"
}
trap cleanup EXIT

# SECRET_KEY and TOKEN for user 1.
eval "$("$PYTHON" "$HERE/seed.py" --db "$TMP/bench.db")"

cd "$ROOT"
DATABASE_URL="sqlite+aiosqlite:///$TMP/bench.db" SECRET_KEY="$SECRET_KEY" \
  ENVIRONMENT=production LOG_LEVEL=WARNING \
  "$PYTHON" -m uvicorn app.main:app --host 127.0.0.1 --port "$PORT" \
  --workers "$WORKERS" --log-level warning --no-access-log &
UVICORN_PID=$!

for _ in $(seq 100); do
  curl -sf -o /dev/null "http://127.0.0.1:$PORT/api/health/ready" && break
  sleep 0.1
done
curl -sf -o /dev/null "http://127.0.0.1:$PORT/api/health/ready" || { echo "uvicorn did not become ready" >&2; exit 1; }
sleep 1  # let every worker finish starting

# ab output -> "| req/s | p95 ms | max ms | failed |"
bench() {
  ab -q -k -n "$1" -c "$CONCURRENCY" -H "Authorization: Bearer $TOKEN" "http://127.0.0.1:$PORT$2" |
    awk '/Requests per second/{rps=$4} /Failed requests/{f=$3} / 95%/{p95=$2} / 100%/{mx=$2}
         END{printf "%s | %s ms | %s ms | %s |\n", int(rps), p95, mx, f}'
}

bench 2000 /api/health >/dev/null  # warm-up

echo "### $(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo source) · $WORKERS worker(s)"
echo
echo "| Escenario | req/s | p95 | máx | fallos |"
echo "| --- | ---: | ---: | ---: | ---: |"
printf "| \`/api/health\` | ";  bench 20000 /api/health
printf "| \`GET /tasks\` | ";   bench 10000 /api/v1/tasks/
printf "| \`GET /tasks\` + 10 logins | "
(
  sleep 0.5
  for i in $(seq 10); do
    curl -s -o /dev/null --data-urlencode "username=u$i@example.com" --data-urlencode "password=Password123" \
      "http://127.0.0.1:$PORT/api/v1/auth/login" &
  done
  wait
) &
LOGINS=$!
bench 6000 /api/v1/tasks/
wait "$LOGINS"
