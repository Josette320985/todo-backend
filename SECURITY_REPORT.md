# Reporte de Auditoría de Seguridad — To-Do List (Equipo 2: "Break It & Secure It")

## 1. Resumen del Stack y Alcance Analizado
- **Backend (`todo-backend/`):** Python 3.14, FastAPI 0.115, Pydantic v2, SQLAlchemy 2.0 Async + SQLite (`aiosqlite`), autenticación JWT (`python-jose`) y hashing `bcrypt` (`passlib`). Tipado estático con `mypy --strict`.
- **Frontend (`todo-frontend/`):** React 19, Vite 8, TypeScript 5.9 (`strict`), `react-bootstrap`, `axios`, servido en producción con Nginx (`nginx:1.27-alpine`).
- **Infraestructura:** Docker y `docker-compose.yml`.

### Controles que el proyecto YA implementa correctamente
- **Autorización / Prevención de IDOR:** En `app/api/v1/tasks.py` todas las operaciones (`GET`, `PUT`, `DELETE`) filtran por `Task.owner_id == current_user.id` obtenido del JWT validado; un usuario no puede leer, modificar ni eliminar tareas de otro usuario.
- **Prevención de SQL Injection:** Todas las consultas usan el ORM de SQLAlchemy 2.0 con parámetros enlazados (`select(User).where(...)`, `select(Task).where(...)`); no existe concatenación de strings SQL.
- **Escapado por defecto en el Frontend:** React escapa automáticamente las expresiones JSX (`{task.title}`, `{error}`) y no se utiliza `dangerouslySetInnerHTML` ni `innerHTML`.
- **Ocultamiento de documentación OpenAPI en producción y logging de fallos de login:** Recientemente añadidos en `app/main.py` (`ENVIRONMENT=production`) y `app/api/v1/auth.py` (con `USER appuser` en `todo-backend/Dockerfile`).

---

## 2. Tabla Resumen de Vulnerabilidades Detectadas

| ID | Severidad | Categoría (OWASP Top 10) | Archivo(s) y Línea(s) | Estado |
|---|---|---|---|---|
| **SEC-01** | **Crítica** | A06: Vulnerable and Outdated Components | `todo-backend/requirements.txt` (L6-L8), `app/core/security.py` (L4), `app/api/deps.py` (L4) | Pendiente |
| **SEC-02** | **Crítica** | A02: Cryptographic Failures / Manejo de Secretos | `todo-backend/app/core/config.py` (L16-L24), `todo-backend/.env` (L6) | Pendiente |
| **SEC-03** | **Alta** | A07: Identification and Authentication Failures (Brute Force / DoS) | `todo-backend/app/api/v1/auth.py` (L19, L56) | Pendiente |
| **SEC-04** | **Alta** | A07: Identification and Authentication Failures (Política de Contraseñas y Truncamiento Bcrypt 72B) | `todo-backend/app/schemas/user.py` (L13) | Pendiente |
| **SEC-05** | **Alta** | A04 / A03: Validación de Entrada en Runtime (`TaskUpdate` Nulos + Cruce de Fechas) | `todo-backend/app/schemas/task.py` (L41-L50), `todo-backend/app/api/v1/tasks.py` (L66-L108) | Pendiente |
| **SEC-06** | **Media** | A09: Security Logging Failures (Log Injection / CRLF) y Excepción 500 en `deps.py` | `todo-backend/app/api/v1/auth.py` (L86-L90), `todo-backend/app/api/deps.py` (L49-L63) | Pendiente |
| **SEC-07** | **Media** | A05: Security Misconfiguration (CORS y Cabeceras de Seguridad HTTP) | `todo-backend/app/main.py` (L46-L52), `todo-frontend/nginx.conf` (L4-L28) | Pendiente |
| **SEC-08** | **Media** | A07: Manejo de Sesión e Invalidación de JWT en Frontend | `todo-frontend/src/api/client.ts` (L1-L30), `todo-frontend/src/App.tsx` (L12-L22) | Pendiente |
| **SEC-09** | **Baja** | A05: Security Misconfiguration (Permisos de directorio SQLite con `appuser` en Docker) | `todo-backend/Dockerfile` (L13-L15) | Pendiente |

---

## 3. Detalle Técnico de Hallazgos

### [SEC-01] Dependencias Criptográficas Abandonadas y con CVEs (`python-jose` y `passlib`)
- **Severidad:** Crítica
- **Ubicación:**
  - `todo-backend/requirements.txt` (líneas 6–8: `python-jose[cryptography]==3.3.*`, `passlib==1.7.4`, `bcrypt==4.2.*`)
  - `todo-backend/app/core/security.py` (líneas 4–11)
  - `todo-backend/app/api/deps.py` (líneas 4, 48–56)
- **Descripción:**
  1. `python-jose 3.3.0` no recibe mantenimiento y presenta vulnerabilidades críticas reportadas: **CVE-2024-33663** (confusión de algoritmos con claves ECDSA/HMAC) y **CVE-2024-33664** (denegación de servicio por bombas de compresión JWE). Además depende de `ecdsa` (`0.19.2`), librería vulnerable a ataques de canal lateral (Minerva / CVE-2024-23342).
  2. `passlib 1.7.4` está abandonada y es incompatible con `bcrypt >= 4.1` (arroja `AttributeError: module 'bcrypt' has no attribute '__about__'` al inicializar el backend).
- **Cómo se explota:** Un atacante puede enviar tokens maliciosos diseñados para explotar debilidades del parser de `python-jose` o provocar errores internos al verificar hashes con `bcrypt` 4.x.
- **Cómo se corrige:** Reemplazar `python-jose` por `PyJWT` (o usar `bcrypt` directamente en `security.py` sin `passlib`, eliminando el fallo de `__about__`) y validar explícitamente los claims requeridos (`sub`, `exp`) y el tipo del algoritmo permitido.

---

### [SEC-02] Falta de Validación de Entropía/Longitud de `SECRET_KEY` y Secreto Débil por Defecto
- **Severidad:** Crítica
- **Ubicación:**
  - `todo-backend/app/core/config.py` (líneas 16–24)
  - `todo-backend/.env` (línea 6)
- **Descripción:** `Settings` en `config.py` define `SECRET_KEY: str` sin validar longitud mínima ni rechazar valores de plantilla. En el entorno actual `.env` tiene exactamente el placeholder público de `.env.example` (`SECRET_KEY=reemplaza-esta-clave-por-una-larga-y-aleatoria-de-al-menos-32-caracteres`), y `Settings` tampoco declara `ENVIRONMENT` ni `CORS_ORIGINS` tipados.
- **Cómo se explota:** Cualquier atacante que conozca el placeholder de `.env.example` o fuerce una clave corta puede firmar tokens JWT arbitrarios (`{"sub": "1"}`) con `HS256` y suplantar a cualquier usuario.
- **Cómo se corrige:** Agregar validación con Pydantic (`Field(min_length=32)` y un `@field_validator` que rechace valores débiles o placeholders conocidos en producción) en `app/core/config.py`, y generar una clave aleatoria criptográficamente segura (`secrets.token_urlsafe(48)`) en `.env`.

---

### [SEC-03] Ausencia de Rate Limiting en Autenticación (`/login` y `/register`)
- **Severidad:** Alta
- **Ubicación:** `todo-backend/app/api/v1/auth.py` (líneas 19–53 y 56–96)
- **Descripción:** Los endpoints `POST /api/v1/auth/login` y `POST /api/v1/auth/register` no aplican ningún límite de peticiones por IP. Además, cuando un email no existe en `/login`, el endpoint salta directamente `verify_password()` (diferencia de tiempo entre ~0.5 ms y ~250 ms de `bcrypt`), permitiendo enumerar usuarios por *timing attack* además del mensaje explícito de `/register`.
- **Cómo se explota:** Un atacante puede ejecutar ataques de fuerza bruta o *credential stuffing* a alta velocidad contra `/api/v1/auth/login`, agotar CPU mediante hashing masivo de `bcrypt` en `/register`, o medir el tiempo de respuesta de `/login` para descubrir correos registrados.
- **Cómo se corrige:** Implementar un limitador de tasa por IP (rate limiting en memoria por ventana deslizante) en los endpoints de autenticación y ejecutar una verificación `bcrypt` contra un hash *dummy* cuando el usuario no exista en `/login` para igualar el tiempo de respuesta.

---

### [SEC-04] Política de Contraseñas Débil y Truncamiento Silencioso de 72 Bytes en Bcrypt
- **Severidad:** Alta
- **Ubicación:** `todo-backend/app/schemas/user.py` (línea 13: `password: str = Field(min_length=8, max_length=128)`)
- **Descripción:**
  1. `UserCreate` permite contraseñas de hasta 128 caracteres, pero el algoritmo `bcrypt` solo procesa los primeros **72 bytes** (en UTF-8, menos aún si incluye acentos o emojis). En `bcrypt >= 4.1`, contraseñas de más de 72 bytes pueden lanzar `ValueError: password cannot be longer than 72 bytes` (causando **HTTP 500**) o truncarse silenciosamente.
  2. No se valida complejidad mínima (acepta `"12345678"` o `"        "` de solo espacios).
- **Cómo se explota:** Enviar una contraseña de 73+ bytes en `/api/v1/auth/register` o `/api/v1/auth/login` provoca un error 500 no controlado, o permite registrar cuentas con contraseñas triviales.
- **Cómo se corrige:** En `app/schemas/user.py`, limitar la contraseña a un máximo de 72 bytes UTF-8 (`max_length=72`) y añadir un `@field_validator("password")` que exija al menos una letra y un número (sin espacios puros), además de normalizar el email en minúsculas.

---

### [SEC-05] Validación Incompleta de Entrada en `PUT /api/v1/tasks/{task_id}` (DoS Error 500 y Bypass de Fechas)
- **Severidad:** Alta
- **Ubicación:**
  - `todo-backend/app/schemas/task.py` (líneas 41–50)
  - `todo-backend/app/api/v1/tasks.py` (líneas 66–108)
- **Descripción:**
  1. En `TaskUpdate`, los campos `title: str | None = None` y `completed: bool | None = None` aceptan `null` explícito en el JSON (`{"title": null}` o `{"completed": null}`). Como `update_task` itera sobre `payload.model_dump(exclude_unset=True)`, asigna `task.title = None` o `task.completed = None` sobre columnas `NOT NULL` en SQLite, disparando un `sqlalchemy.exc.IntegrityError` no capturado (**HTTP 500 Internal Server Error**).
  2. Tampoco se valida que `description` en `TaskUpdate` tenga `max_length=1000` (a diferencia de `TaskCreate`), permitiendo enviar megabytes de texto en una actualización.
  3. `TaskUpdate.validate_dates` solo compara `self.start_date` y `self.end_date` del payload, pero si el usuario actualiza solo una de las dos fechas, no se compara contra la fecha ya almacenada en la base de datos (`task.start_date` / `task.end_date`), permitiendo dejar una tarea con `end_date < start_date`.
- **Cómo se explota:** Con una petición `PUT /api/v1/tasks/1` enviando `{"title": null, "description": "A" * 5000000}`, el servidor lanza una excepción 500 de base de datos o almacena payloads desproporcionados sin límite.
- **Cómo se corrige:**
  - En `app/schemas/task.py`: agregar `max_length=1000` a `TaskUpdate.description`, hacer strip de títulos vacíos (solo espacios) y rechazar `None` explícito cuando `title` o `completed` vienen en el JSON.
  - En `app/api/v1/tasks.py`: validar la consistencia entre las fechas resultantes (`task.start_date` y `task.end_date`) antes de confirmar la transacción, devolviendo HTTP 422 si `end_date < start_date`.

---

### [SEC-06] Inyección de Logs (CRLF Log Forging) en `/login` y Excepción 500 por `sub` Manipulado en `deps.py`
- **Severidad:** Media
- **Ubicación:**
  - `todo-backend/app/api/v1/auth.py` (líneas 86–90)
  - `todo-backend/app/api/deps.py` (líneas 49–63)
- **Descripción:**
  1. En `auth.py`, `logger.warning("Failed login attempt | email=%s ip=%s", form.username, client_ip)` registra `form.username` sin sanitizar saltos de línea (`\r`, `\n`), porque `OAuth2PasswordRequestForm` acepta cualquier `str` arbitrario (no pasa por `EmailStr`). Un atacante puede inyectar líneas falsas en los logs.
  2. En `deps.py`, `int(user_id)` se ejecuta fuera del `try/except`: si un token contiene un `sub` no numérico o con formato inesperado, `int(user_id)` lanza `ValueError` (**HTTP 500**) en lugar de `HTTP 401`.
- **Cómo se explota:** Enviando `username=admin@test.com\nINFO:root: Login successful` al endpoint `/api/v1/auth/login` se falsifican entradas de auditoría.
- **Cómo se corrige:** Sanitizar caracteres de control (`\r`, `\n`) y truncar `form.username` antes de escribirlo en el logger en `auth.py`; en `deps.py`, capturar `(JWTError, ValueError, TypeError)` al convertir `user_id` a `int`.

---

### [SEC-07] Configuración Insegura de CORS en FastAPI y Falta de Security Headers en Backend/Nginx
- **Severidad:** Media
- **Ubicación:**
  - `todo-backend/app/main.py` (líneas 46–52)
  - `todo-frontend/nginx.conf` (líneas 4–28)
- **Descripción:**
  1. En `app/main.py`, `CORSMiddleware` tiene `allow_methods=["*"]` y `allow_headers=["*"]` combinados con `allow_credentials=True`, y orígenes hardcodeados (`["http://localhost:8080"]`, que ni siquiera coincide con el puerto 3000 de Docker ni el 5173 de Vite).
  2. Ni las respuestas de la API ni el servidor Nginx en `todo-frontend/nginx.conf` incluyen cabeceras de defensa en profundidad (`X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: strict-origin-when-cross-origin`, `Content-Security-Policy`, ni `server_tokens off`).
- **Cómo se explota:** Permite ataques de Clickjacking (incrustar la app en un `<iframe>`), MIME-sniffing y expone la versión exacta de Nginx en las cabeceras HTTP.
- **Cómo se corrige:** Restringir `allow_methods` y `allow_headers` a los estrictamente necesarios en `app/main.py` (leyendo los orígenes permitidos desde `settings`), agregar un middleware de cabeceras de seguridad HTTP en FastAPI y configurar las cabeceras de seguridad + `server_tokens off;` en `todo-frontend/nginx.conf`.

---

### [SEC-08] Manejo Inseguro de Tokens Expirados/Inválidos (401) en el Cliente Frontend
- **Severidad:** Media
- **Ubicación:**
  - `todo-frontend/src/api/client.ts` (líneas 1–30)
  - `todo-frontend/src/App.tsx` (líneas 12–22)
  - `todo-frontend/src/components/TaskList.tsx` (líneas 101–116)
- **Descripción:**
  1. `App.tsx` determina si el usuario está autenticado únicamente con `!!localStorage.getItem('token')`, sin verificar si el JWT expiró ni escuchar eventos de cierre de sesión cuando el backend devuelve `401 Unauthorized`.
  2. `client.ts` no tiene un interceptor de respuesta para limpiar el token inválido/expirado de `localStorage` cuando la API responde `401`.
  3. En `TaskList.tsx`, `toggleTask` y `deleteTask` no capturan errores de red/autorización (`try/catch`), dejando promesas rechazadas sin manejar.
- **Cómo se explota:** Si un token expira o es manipulado en `localStorage`, la interfaz permanece en la vista privada fallando silenciosamente en cada operación.
- **Cómo se corrige:** Añadir un interceptor de respuesta en `src/api/client.ts` que ante un `401` (fuera de `/auth/login`) elimine el token de `localStorage` y dispare un evento para que `App.tsx` cierre la sesión inmediatamente, y añadir manejo de errores en `toggleTask` y `deleteTask` en `TaskList.tsx`.

---

### [SEC-09] Permisos de Escritura para `appuser` sobre la Base de Datos SQLite en `Dockerfile`
- **Severidad:** Baja
- **Ubicación:** `todo-backend/Dockerfile` (líneas 13–15)
- **Descripción:** En `todo-backend/Dockerfile` se añadió `RUN useradd -m -u 1000 appuser` y `USER appuser`, pero el directorio `/app` y `/app/data` pertenecen a `root:root`. Cuando el contenedor intenta crear la base de datos SQLite o los archivos journal/WAL en `/app/data/todo.db` como `appuser`, SQLite puede fallar con `OperationalError: attempt to write a readonly database`.
- **Cómo se explota:** Provoca denegación de servicio al iniciar el contenedor en entornos donde el volumen `/app/data` no exista previamente con permisos del UID 1000.
- **Cómo se corrige:** Crear `/app/data` y asignar la propiedad de `/app` a `appuser:appuser` (`chown -R appuser:appuser /app`) en `todo-backend/Dockerfile` antes de cambiar a `USER appuser`.
