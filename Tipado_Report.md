# 3. Resumen de archivos tipados

## Backend (todo-backend/)

| Archivo | Cambio realizado |
| --- | --- |
| requirements-dev.txt | Creado con `mypy`, `types-python-jose` y `types-passlib`. |
| pyproject.toml | Creado con configuración `mypy` en modo `strict` y plugin `pydantic.mypy`. |
| .gitignore | Añadido `.mypy_cache/`. |
| app/core/config.py | Tipado explícito `settings: Final[Settings]`. |
| app/core/security.py | Tipados `pwd_context: Final[CryptContext]`, `expire: datetime` y `payload: dict[str, str \| datetime]`. |
| app/db/session.py | Tipados `engine: Final[AsyncEngine]`, `AsyncSessionLocal: Final[async_sessionmaker[AsyncSession]]` y `get_db() -> AsyncGenerator[AsyncSession, None]`. |
| app/schemas/task.py | Retorno `-> Self` en validadores y `ConfigDict(from_attributes=True)`. |
| app/schemas/user.py | `ConfigDict(from_attributes=True)` en `UserRead`. |
| app/api/deps.py | Tipados `oauth2_scheme`, `credentials_exception`, `payload`, `user_id`, `result: Result[tuple[User]]` y `user: User \| None`. |
| app/api/v1/auth.py | Retornos `-> User` y `-> dict[str, str]`, `router: Final[APIRouter]` y resultados SQLAlchemy tipados. |
| app/api/v1/tasks.py | Retornos `-> Sequence[Task]`, `-> Task` y `-> None`, `router: Final[APIRouter]` y consultas tipadas. |
| app/main.py | Tipados `lifespan -> AsyncIterator[None]`, `app: Final[FastAPI]` y `health -> dict[str, str]`. |


## Frontend (todo-frontend/)

| Archivo | Cambio realizado |
| --- | --- |
| package.json y package-lock.json | Añadido script `"typecheck": "tsc --noEmit"` y dependencias `typescript` + `typescript-eslint`. |
| tsconfig.json | Configuración de TypeScript en modo `strict`. |
| src/vite-env.d.ts | Referencia a tipos de cliente de Vite (`vite/client`). |
| src/types/task.ts | Interfaces `Task`, `TaskCreate` y `TaskUpdate`. |
| src/types/auth.ts | Interfaces `UserCreate`, `UserRead`, `TokenResponse` y `ApiErrorResponse`. |
| src/api/client.ts | Migrado de `.js` a `.ts` con `AxiosInstance` e `InternalAxiosRequestConfig`. |
| src/components/LoginForm.tsx | Migrado de `.jsx` a `.tsx` con `LoginFormProps`, eventos, estados y respuestas Axios tipadas. |
| src/components/TaskList.tsx | Migrado de `.jsx` a `.tsx` con estados, funciones auxiliares y llamadas CRUD tipadas con `Task`, `TaskCreate` y `TaskUpdate`. |
| src/main.tsx y index.html | Migrado el punto de entrada a `.tsx` y actualizado el `<script>` en `index.html`. |
| src/App.tsx | Migrado de `.jsx` a `.tsx` con `JSX.Element`, estado booleano y handler `logout: () => void`. |
| eslint.config.js | Habilitado `typescript-eslint` para archivos `.ts` y `.tsx`. |


# Qué sí arreglamos alrededor de localStorage (defensa en profundidad)

## 1. Bloqueo de ejecución de scripts externos con Content-Security-Policy (CSP):
### El único vector por el cual un atacante puede leer localStorage.getItem('token') es logrando ejecutar JavaScript malicioso (XSS).
### En nginx.conf agregamos Content-Security-Policy: default-src 'self'; script-src 'self'; ..., lo que bloquea cualquier script inline (<script>...</script>, onerror=...) o script externo que intente robar localStorage.

## 2. Escapado automático en React + Validación estricta en Backend:
### Verificamos que en ningún componente se use dangerouslySetInnerHTML ni innerHTML, y limitamos longitudes y tipos en Pydantic (TaskCreate, TaskUpdate).

## 3. Purga automática ante 401 Unauthorized:
### Antes, si el token expiraba o era inválido, se quedaba guardado para siempre en localStorage y la pantalla seguía "adentro".
### En client.ts y App.tsx agregamos un interceptor de respuesta que, al primer 401, borra inmediatamente localStorage.removeItem('token') y expulsa al usuario al login.

## 4. Expiración corta y obligatoria en el servidor (exp + iat):
### En deps.py exigimos options={"require_sub": True, "require_exp": True} (30 minutos), por lo que un token robado no tiene validez indefinida.