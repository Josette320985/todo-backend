# E2E con Playwright (TEST-09)

Pruebas de punta a punta sobre el stack real de `docker-compose.yml`: el mismo
Nginx (`todo-frontend/nginx.conf` + build de Vite) y el mismo backend
(`Dockerfile`), con una base de datos descartable.

## Cómo correrlas

Requisitos: Docker con Compose ≥ 2.24 (usa `!reset` / `!override`), Node ≥ 20 y
los dos repos clonados como hermanos (`todo-backend/` y `todo-frontend/`).

```sh
cd todo-backend/e2e
npm ci
npx playwright install --with-deps chromium   # la primera vez
npm test                                      # levanta el stack, corre y lo borra
```

Para iterar más rápido, deja el stack arriba y reutilízalo:

```sh
npm run stack:up
E2E_REUSE_STACK=1 npx playwright test tests/04-headers-seguridad.spec.ts
npm run stack:down
```

| Variable | Default | Para qué |
| --- | --- | --- |
| `E2E_PORT` | `3100` | Puerto del host donde se publica Nginx (solo en `127.0.0.1`) |
| `E2E_REUSE_STACK=1` | — | No levanta ni borra el stack |
| `E2E_KEEP_STACK=1` | — | No lo borra al terminar (para ver `docker compose -p todo-e2e logs`) |

Reporte HTML con trazas de los fallos: `npm run report`.

## Qué cambia respecto al stack de desarrollo

Todo está en `e2e/docker-compose.e2e.yml`, que se aplica **encima** del
`docker-compose.yml` real (no lo reemplaza):

- Proyecto propio `todo-e2e`: no choca con un `docker compose up` de desarrollo.
- BD en `tmpfs`: se pierde en cada `down` y en cada parada del backend.
- `SECRET_KEY` de prueba: no hace falta `.env` (CI no tiene).
- `BCRYPT_ROUNDS=4`, `ENVIRONMENT=production`.
- Healthchecks en backend y Nginx para `up --wait`.
- `client-a` y `client-b`: dos contenedores con la imagen del backend (sin
  descargar nada) que hacen peticiones a Nginx desde **IPs distintas**
  (`clients/http_client.py`, solo biblioteca estándar).

## Flujos

Corren en serie, en orden de archivo, con un solo worker: comparten el proceso
del backend (y su rate limit en memoria) y el flujo 3 lo detiene.

| Archivo | Flujo | Criterio que cubre |
| --- | --- | --- |
| `01-flujo-completo` | Registro → crear → marcar → editar → eliminar → deshacer → cerrar sesión. Cada paso se verifica también tras recargar, y al final que el token viejo da 401 | UX-04, SEG-H10 |
| `02-sesion-expirada` | Token inválido en `localStorage` (JWT con otra clave y basura) → login con "Tu sesión expiró. Vuelve a iniciar sesión." | UX-06 |
| `03-backend-caido` | Backend detenido y navegador sin red → el aviso no dice "Revisa los datos" | ERR-06 (y ERR-07) |
| `04-headers-seguridad` | Headers de seguridad en `/`, una ruta del SPA, cada `/assets/…` y `/api/health` | Nota 3 del mapa de cruces, OPT-06, SEG-H15 |
| `05-rate-limit-por-ip` | 10 fallos de A no bloquean el login de B; un `X-Forwarded-For` inventado no saca a A del bloqueo | SEG-02 |

El flujo 5 va al final a propósito: mientras SEG-02 no esté corregido, los
fallos de A bloquean a **todos** durante 60 s.

Los selectores aceptan el texto actual y el que proponen las tareas de UX
(`/modificar|editar/`, `/eliminar|borrar/`), para no romperse con UX-07.

## Relación con los montajes del reporte de seguridad

`browser_fixture.sh` y `proxy_fixture.py` (sección 9 del reporte) levantan la
misma topología a mano en una red `--internal`. Aquí se reemplazaron por el
compose real más el override, para que CI corra exactamente lo que se
despliega. La idea de los clientes en contenedores separados para tener IPs
distintas viene de `proxy_fixture.py`.
