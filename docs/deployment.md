# Deployment

How to run the To-Do List stack (FastAPI backend + nginx frontend) safely,
locally and in a real deployment.

## Architecture

```text
browser --HTTP--> nginx (todo_frontend, port 80)
                    |-- /      -> React build (static files)
                    '-- /api/  -> FastAPI (todo_backend, port 8000, internal only)
```

- `docker-compose.yml` lives in this repository and builds the frontend from
  the sibling folder `../todo-frontend`.
- The backend port (8000) is never published; only nginx is reachable.

## Local use

```bash
cp .env.example .env
# Set SECRET_KEY in .env, for example with:
python -c "import secrets; print(secrets.token_urlsafe(48))"
docker compose up -d --build
```

- The app is published on **`http://127.0.0.1:3000`** only (loopback). Other
  machines on the network cannot reach it (SEG-H13).
- With `ENVIRONMENT=development` the API docs are available at
  `http://127.0.0.1:3000/api/docs`, `/api/redoc` and `/api/openapi.json`.

## Requirements for a real deployment

1. **HTTPS is mandatory (SEG-H13).** nginx in this stack only speaks plain
   HTTP on port 80 and does not send HSTS. Without TLS, passwords and JWTs
   travel in clear text. Put a TLS-terminating proxy or load balancer in front
   of the `frontend` service and have it:
   - redirect HTTP to HTTPS;
   - send `Strict-Transport-Security: max-age=31536000; includeSubDomains`;
   - forward requests to the frontend container, which must not be published
     on a public interface.
2. **`ENVIRONMENT=production` (SEG-H07).** The API docs are only published
   when `ENVIRONMENT` is `development` (case-insensitive). Any other value
   disables them, but set `production` explicitly so the intent is clear.
3. **A unique `SECRET_KEY`.** Never reuse the value from `.env.example` or
   from another environment.
4. **Do not change the port binding to `0.0.0.0`** unless a TLS proxy runs on
   the same host and the port is firewalled from the outside.

## Built-in protections

| Protection | Where | Finding |
|---|---|---|
| `.env`, `.git`, `data/` and caches never enter the backend image | `.dockerignore` | SEG-H01 |
| API request bodies above 16 KB are rejected with `413` | `todo-frontend/nginx.conf` (`client_max_body_size 16k`) | SEG-H02 |
| API docs only in `development` | `app/main.py` (`api_docs_urls`) | SEG-H07 |
| Frontend port bound to `127.0.0.1` | `docker-compose.yml` | SEG-H13 |
| Backend runs as non-root user (uid 1000) | `Dockerfile` | Team 2, SEC-09 |
| Security headers and CSP | `todo-frontend/nginx.conf`, `app/main.py` | Team 2, SEC-07 |

## Quick checks

```bash
# The image holds no secrets or database files.
docker run --rm --entrypoint ls todo-backend-backend -A /app

# Bodies above 16 KB are rejected.
python -c "print('a'*102400, end='')" > big.txt
curl -s -o /dev/null -w '%{http_code}\n' -X POST --data-binary @big.txt \
  http://127.0.0.1:3000/api/v1/auth/login            # 413

# Docs are off outside development.
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:3000/api/openapi.json  # 404 in production

# The port only listens on loopback.
docker compose port frontend 80                      # 127.0.0.1:3000
```
