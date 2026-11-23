# Reporte de Auditoría de Seguridad (Actualizado) — To-Do List (Equipo 2: "Break It & Secure It")

## 1. Resumen del Stack y Alcance Analizado
- **Backend (`todo-backend/`):** Python 3.14, FastAPI 0.115, Pydantic v2, SQLAlchemy 2.0 Async + SQLite (`aiosqlite`), autenticación JWT (`python-jose` con `HS256` restringido y claims obligatorios) y hashing directo con `bcrypt`. Tipado estático verificado con `mypy --strict` (0 errores).
- **Frontend (`todo-frontend/`):** React 19, Vite 8, TypeScript 5.9 (`strict`), `react-bootstrap`, `axios`, servido en producción con Nginx (`nginx:1.27-alpine`). Verificado con `tsc --noEmit` (0 errores) y `eslint` (0 errores).
- **Infraestructura:** Docker y `docker-compose.yml`.

### Controles que el proyecto ya implementaba desde la entrega inicial
- **Autorización / Prevención de IDOR:** En `app/api/v1/tasks.py` todas las operaciones (`GET`, `PUT`, `DELETE`) filtran por `Task.owner_id == current_user.id` obtenido del JWT validado; un usuario no puede leer, modificar ni eliminar tareas de otro usuario.
- **Prevención de SQL Injection:** Todas las consultas usan el ORM de SQLAlchemy 2.0 con parámetros enlazados (`select(User).where(...)`, `select(Task).where(...)`); no existe concatenación de strings SQL.
- **Escapado por defecto en el Frontend:** React escapa automáticamente las expresiones JSX (`{task.title}`, `{error}`) y no se utiliza `dangerouslySetInnerHTML` ni `innerHTML`.
- **Ocultamiento de documentación OpenAPI en producción y usuario no-root en Docker:** Implementados mediante `ENVIRONMENT=production` en `app/main.py` y `USER appuser` en `todo-backend/Dockerfile`.

---

## 2. Tabla Resumen de Vulnerabilidades y Estado Actual

| ID | Severidad | Categoría (OWASP Top 10) | Archivo(s) y Línea(s) | Estado |
|---|---|---|---|---|
| **SEC-01** | **Crítica** | A06: Vulnerable and Outdated Components (`passlib` + Validación Estricta JWT) | `todo-backend/app/core/security.py`, `todo-backend/app/api/deps.py` | **Corregido** |
| **SEC-02** | **Crítica** | A02: Cryptographic Failures / Validación de `SECRET_KEY` y Algoritmo | `todo-backend/app/core/config.py` | **Corregido** |
| **SEC-03** | **Alta** | A07: Identification and Authentication Failures (Rate Limiting y Mitigación de Timing Attack) | `todo-backend/app/api/v1/auth.py`, `todo-backend/app/core/security.py` | **Corregido** |
| **SEC-04** | **Alta** | A07: Identification and Authentication Failures (Política de Contraseñas y Límite 72B Bcrypt) | `todo-backend/app/schemas/user.py`, `todo-backend/app/core/security.py` | **Corregido** |
| **SEC-05** | **Alta** | A04 / A03: Validación de Entrada en Runtime (`TaskUpdate` Nulos, Longitud y Cruce de Fechas) | `todo-backend/app/schemas/task.py`, `todo-backend/app/api/v1/tasks.py` | **Corregido** |
| **SEC-06** | **Media** | A09: Security Logging Failures (Sanitización CRLF) y Manejo de `sub` Malformado en `deps.py` | `todo-backend/app/api/v1/auth.py`, `todo-backend/app/api/deps.py` | **Corregido** |
| **SEC-07** | **Media** | A05: Security Misconfiguration (CORS Explícito y Cabeceras de Seguridad HTTP + CSP) | `todo-backend/app/main.py`, `todo-frontend/nginx.conf` | **Corregido** |
| **SEC-08** | **Media** | A07: Manejo de Sesión e Invalidación de JWT en Frontend ante `401 Unauthorized` | `todo-frontend/src/api/client.ts`, `src/App.tsx`, `src/components/TaskList.tsx` | **Corregido** |
| **SEC-09** | **Baja** | A05: Security Misconfiguration (Permisos de Directorio SQLite con `appuser` en Docker) | `todo-backend/Dockerfile` | **Corregido** |

---

## 3. Detalle de Correcciones Aplicadas

### [SEC-01] Reemplazo de `passlib` por `bcrypt` Directo y Endurecimiento de Decodificación JWT — **CORREGIDO**
- **Archivos modificados:** `todo-backend/app/core/security.py`, `todo-backend/app/api/deps.py`
- **Corrección aplicada:**
  1. Se reemplazó `passlib.context.CryptContext` por el uso directo de `bcrypt.hashpw` y `bcrypt.checkpw`, eliminando la dependencia en tiempo de ejecución de `passlib 1.7.4` (abandonada e incompatible con `bcrypt >= 4.1`).
  2. Se añadió el claim `iat` (issued-at) en `create_access_token` y se configuró `options={"require_sub": True, "require_exp": True}` en `jwt.decode` dentro de `app/api/deps.py`, asegurando que ningún token sin fecha de expiración ni sujeto sea aceptado.
- **Nota sobre trabajo futuro (opcional):** Si en el futuro se desea reemplazar también el paquete `python-jose` en `requirements.txt` por `PyJWT`, la superficie actual ya está mitigada al restringir estrictamente el algoritmo a `Literal["HS256"]` y exigir `require_exp` / `require_sub`.

---

### [SEC-02] Validación de Longitud Mínima de `SECRET_KEY` y Restricción de Algoritmo JWT — **CORREGIDO**
- **Archivo modificado:** `todo-backend/app/core/config.py`
- **Corrección aplicada:**
  - `SECRET_KEY` ahora exige `Field(min_length=32)` y un `@field_validator("SECRET_KEY")` que aplica `.strip()` y rechaza claves con menos de 32 caracteres efectivos.
  - `ALGORITHM` se restringió al tipo `Literal["HS256"] = "HS256"`, impidiendo configurar el algoritmo `"none"`.
  - `ACCESS_TOKEN_EXPIRE_MINUTES` se acotó a `Field(default=30, ge=1, le=1440)` y se añadieron `ENVIRONMENT` y `CORS_ORIGINS` tipados.

---

### [SEC-03] Rate Limiting en `/register` y `/login` + Defensa contra Timing Attacks — **CORREGIDO**
- **Archivos modificados:** `todo-backend/app/api/v1/auth.py`, `todo-backend/app/core/security.py`
- **Corrección aplicada:**
  - Se implementó `_enforce_rate_limit()` por ventana deslizante de 60 segundos por IP: máximo **5 registros/min** y **10 intentos de login/min**, devolviendo `HTTP 429 Too Many Requests` al superarse.
  - Se precomputó `DUMMY_PASSWORD_HASH` en `security.py` y, cuando un correo no existe en `/login`, se ejecuta igualmente `verify_password(form.password, DUMMY_PASSWORD_HASH)` para igualar el tiempo de respuesta de `bcrypt` y evitar la enumeración de usuarios por *timing attack*.

---

### [SEC-04] Política de Contraseñas y Protección contra el Límite de 72 Bytes de Bcrypt — **CORREGIDO**
- **Archivos modificados:** `todo-backend/app/schemas/user.py`, `todo-backend/app/core/security.py`
- **Corrección aplicada:**
  - En `UserCreate` (`app/schemas/user.py`), se limitó `password` a `Field(min_length=8, max_length=72)` y se añadió `validate_password_strength` que verifica `len(value.encode("utf-8")) <= 72`, rechaza contraseñas de solo espacios y exige al menos una letra y un número.
  - Se agregó `normalize_email` para normalizar el correo en minúsculas (`strip().lower()`).
  - En `verify_password` (`app/core/security.py`), si una contraseña en login supera 72 bytes UTF-8 o el hash es inválido, retorna `False` de forma segura en lugar de lanzar `ValueError` (HTTP 500).

---

### [SEC-05] Validación de Nulos, Longitud y Consistencia de Fechas en Tareas — **CORREGIDO**
- **Archivos modificados:** `todo-backend/app/schemas/task.py`, `todo-backend/app/api/v1/tasks.py`
- **Corrección aplicada:**
  - En `app/schemas/task.py`: se agregó `max_length=1000` a `TaskUpdate.description`, se validó que `title` no sea vacío tras `.strip()`, y se utilizó `self.model_fields_set` en `TaskUpdate` para rechazar con HTTP 422 cuando el cliente envía explícitamente `{"title": null}` o `{"completed": null}` (que antes causaban `IntegrityError` / HTTP 500 en SQLite).
  - En `app/api/v1/tasks.py`: en `update_task` se valida que el rango resultante (`new_start` y `new_end`, combinando los campos enviados con los ya guardados en la base de datos) cumpla `new_end >= new_start` (devolviendo HTTP 422 si es inválido), y se restringió `setattr` a la lista blanca `ALLOWED_UPDATE_FIELDS`.

---

### [SEC-06] Sanitización contra Log Injection (CRLF) y Captura de `sub` No Numérico — **CORREGIDO**
- **Archivos modificados:** `todo-backend/app/api/v1/auth.py`, `todo-backend/app/api/deps.py`
- **Corrección aplicada:**
  - En `app/api/v1/auth.py`, `_sanitize_for_log()` escapa `\r` y `\n` y trunca la longitud a 120 caracteres antes de escribir `form.username` y `client_ip` en `logger.warning`.
  - En `app/api/deps.py`, se verifica `isinstance(raw_sub, str)` y se captura `(JWTError, ValueError, TypeError)` al convertir `int(raw_sub)`, devolviendo siempre `401 Unauthorized` en lugar de `500 Internal Server Error`.

---

### [SEC-07] Endurecimiento de CORS y Cabeceras de Seguridad HTTP en Backend y Nginx — **CORREGIDO**
- **Archivos modificados:** `todo-backend/app/main.py`, `todo-frontend/nginx.conf`
- **Corrección aplicada:**
  - En `app/main.py`: `CORSMiddleware` ahora usa `settings.CORS_ORIGINS`, `allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"]` y `allow_headers=["Authorization", "Content-Type"]`, y se añadió el middleware `add_security_headers` (`X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: strict-origin-when-cross-origin`, `Cache-Control: no-store`).
  - En `todo-frontend/nginx.conf`: se añadió `server_tokens off;` y las cabeceras `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy` y `Content-Security-Policy` (`default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self';`).

---

### [SEC-08] Manejo Seguro de Expiración de Sesión (`401`) y Errores de API en Frontend — **CORREGIDO**
- **Archivos modificados:** `todo-frontend/src/api/client.ts`, `todo-frontend/src/App.tsx`, `todo-frontend/src/components/TaskList.tsx`
- **Corrección aplicada:**
  - En `src/api/client.ts`: se añadió un interceptor de respuesta que, al recibir un `401 Unauthorized` (fuera de `/auth/login`), borra el token de `localStorage` y emite el evento `AUTH_UNAUTHORIZED_EVENT`.
  - En `src/App.tsx`: se escucha `AUTH_UNAUTHORIZED_EVENT` en un `useEffect` para cambiar `loggedIn` a `false` y regresar automáticamente al login.
  - En `src/components/TaskList.tsx`: se agregaron bloques `try/catch` en `toggleTask` y `deleteTask` y un flag de limpieza `active` en el `useEffect` inicial.
- **Nota arquitectónica pendiente (defensa adicional):** El token JWT se mantiene en `localStorage` para no alterar el contrato actual de la API REST (`OAuth2PasswordBearer` por cabecera `Authorization: Bearer`); el riesgo de robo por XSS quedó mitigado mediante la política `Content-Security-Policy` (`script-src 'self'`) en Nginx y el escapado automático de React.

---

### [SEC-09] Permisos de Escritura para `appuser` sobre `/app/data` en Docker — **CORREGIDO**
- **Archivo modificado:** `todo-backend/Dockerfile`
- **Corrección aplicada:** Se añadió `mkdir -p /app/data && chown -R appuser:appuser /app` antes de `USER appuser` para que el contenedor sin privilegios pueda crear y modificar el archivo SQLite en `/app/data/todo.db`.
