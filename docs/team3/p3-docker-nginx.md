# P3: Docker and nginx

Owner: P3 - Branches: `p3/*` - Findings: SEG-H01, SEG-H02, SEG-H07, SEG-H13

## Summary

P3 hardened the container and proxy layer of the To-Do List: what goes into
the backend image, how much data nginx accepts, when the API docs are
published and how the app is exposed on the network. P3 also set up the
`docs/` folder and the commit rules (Conventional Commits and "no code
without docs") used by the whole team.

## Findings

| ID | Title | Status | Pull request |
|---|---|---|---|
| SEG-H01 | Backend image contained `.env` and `.git` | Fixed | [todo-backend#3](https://github.com/Josette320985/todo-backend/pull/3) |
| SEG-H02 | No request body limit in nginx | Fixed | [todo-frontend#3](https://github.com/Josette320985/todo-frontend/pull/3) |
| SEG-H07 | API docs exposed unless `ENVIRONMENT` was exactly `production` | Fixed | [todo-backend#4](https://github.com/Josette320985/todo-backend/pull/4) |
| SEG-H13 | No HTTPS/HSTS, port published on every interface | Fixed for local use, documented for deployment | [todo-backend#5](https://github.com/Josette320985/todo-backend/pull/5) |
| - | No documentation folder or commit rules | Added | [todo-backend#2](https://github.com/Josette320985/todo-backend/pull/2), [todo-frontend#2](https://github.com/Josette320985/todo-frontend/pull/2) |

## Changes

### SEG-H01: `.dockerignore` (todo-backend)

`Dockerfile` runs `COPY . .`, so every file in the folder ended up in `/app`.
The new `.dockerignore` excludes secrets (`.env`, `.env.*`, keeping
`.env.example`), the SQLite data (`data/`, `*.db`), Git and repository tooling,
local virtual environments and caches, `tests/` and `docs/`. The real `.env` is
still injected at runtime by `env_file` in `docker-compose.yml`.

### SEG-H02: `client_max_body_size 16k` (todo-frontend `nginx.conf`)

Added inside `location /api/`. Login and task payloads are a few hundred
bytes, so 16 KB leaves plenty of room while capping the form parsing cost
before the rate limit runs.

### SEG-H07: docs only in development (todo-backend `app/main.py`)

The three `_ENV == "production"` checks were replaced by
`api_docs_urls(env)`, which publishes `/api/docs`, `/api/redoc` and
`/api/openapi.json` only when `env.strip().lower() == "development"`. Every
other value, including typos, disables them (fail-closed). `.env.example`
explains the rule.

### SEG-H13: loopback binding and HTTPS requirement (todo-backend)

`docker-compose.yml` publishes nginx on `127.0.0.1:3000` instead of every
interface. TLS is not configured in this stack, because the real deployment
infrastructure is unknown. [deployment.md](../deployment.md) states that a
TLS proxy with HSTS is mandatory for any real deployment.

### Team rules: docs folder, hook and CI (both repositories)

- `docs/` with an index, [CONTRIBUTING.md](../CONTRIBUTING.md),
  [CHANGELOG.md](../CHANGELOG.md) and the member report template.
- `.githooks/commit-msg`: rejects non-Conventional or longer than 72
  character headers, and code changes without documentation (exception:
  `Docs-Exempt: <reason>` trailer).
- `.github/workflows/commit-rules.yml`: same checks on every pull request
  (exception: `docs-exempt` label).

## Evidence

All commands were run on Windows 11 with Docker 29.7.2, with both
repositories on the `p3/*` branches and `docker compose up -d --build`.

### SEG-H01

```text
# Before (equipo3, no .dockerignore), image 749 MB
$ docker run --rm --entrypoint ls <image> -la /app
.env  .env.example  .git  .gitattributes  .githooks  .github  .gitignore
.pytest_cache  .venv  Dockerfile  ...  app  data  docs  tests
/app/data: todo.db

# After, image 348 MB
$ docker run --rm --entrypoint ls todo-backend-backend -A /app
.dockerignore .env.example .gitignore Dockerfile README.md SECURITY_REPORT.md
SECURITY_REPORT_ACTUALIZADO.md Tipado_Report.md app data docker-compose.yml
pyproject.toml requirements-dev.txt requirements.txt
/app/data: (empty)
```

### SEG-H02

```text
100 KB POST /api/v1/auth/login   -> 413
login (correct password)         -> 200
login (wrong password)           -> 401
```

### SEG-H07

```text
$ pytest -q
32 passed   (18 existing + 14 in tests/test_api_docs.py)

Through nginx:
ENVIRONMENT=development  /api/openapi.json 200  /api/redoc 200  /api/docs 200
ENVIRONMENT=Production   /api/openapi.json 404  /api/redoc 404  /api/docs 404  /api/health 200
ENVIRONMENT=production   /api/openapi.json 404  /api/redoc 404  /api/docs 404  /api/health 200
```

### SEG-H13

```text
$ docker compose port frontend 80
127.0.0.1:3000
$ curl http://127.0.0.1:3000/api/health      -> 200
$ curl http://<LAN IP>:3000/api/health        -> connection refused
```

### No regressions

Through nginx: `GET /` 200, register 201, login 200, create task 201,
list tasks 200, health 200.

### Commit rules

```text
code change without docs        -> rejected
header "updated stuff"          -> rejected
header of 85 characters         -> rejected
code change + Docs-Exempt       -> accepted
code change + docs/CHANGELOG.md -> accepted
```

## Pending

| Item | Why it is pending | Suggested owner |
|---|---|---|
| Real TLS termination and HSTS | Needs the deployment infrastructure (domain, certificates, cloud proxy), which is out of scope for Team 3. Requirements are in [deployment.md](../deployment.md). | Team 4 |
| Merge order with P2 | P2 edits the same `location /api/` block in `nginx.conf` and adds a fixed subnet in `docker-compose.yml`. The changes touch different lines; the second PR to merge rebases. | P2 / P3 |
| README update | Agreed to update the README at the end, from `docs/CHANGELOG.md` and these reports. | Team 3 |
| Create the `docs-exempt` label | Only needed the first time a pull request uses the exception. | Any member |

## AI prompts used

AI assistance (Claude Code) was used to plan, implement and verify this block.
Prompts, translated to English:

1. "Here are the project repositories. We are Team 3 and the repositories
   were updated by Team 2. The security report says what we have to do; I got
   P3 - Docker and nginx. Work in short, well-documented commits, on branches
   and with PRs, following every requirement of the challenge document."
2. "Our base branch is `equipo3`, which already includes P8. If there is no
   documentation, create it, and add a requirement that everything new must be
   documented before it can be committed. Commits must be short and follow
   the standard, in English. All documentation must be written in English."
