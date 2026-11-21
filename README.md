# To-Do List Application — Team 1 (Build It)

A complete task management application (To-Do List) built with **React (Frontend)** and **FastAPI + SQLite (Backend)**. The entire system is containerized and orchestrated using Docker Compose, allowing it to be started with a single command.

This repository contains the **Backend and Docker Compose configuration**. The Frontend source code is maintained in a separate repository.

---

## Prerequisites

Before getting started, make sure you have the following installed and ready:

- **Git:** Required to clone the repositories.
- **Docker Desktop:** Must be installed and running, with the Docker engine active.

---

## 1. Get the Project (Clone Repositories)

**IMPORTANT:** Since the project is divided into two repositories (Frontend and Backend), and Docker Compose is used to run them together, **both repositories must be cloned into the same parent directory** (as sibling folders).

Open your terminal and run the following commands:

```bash
# 1. Create a project directory and navigate into it
mkdir equipo1-todo
cd equipo1-todo

# 2. Clone both repositories
git clone https://github.com/Josette320985/todo-backend.git
git clone https://github.com/Josette320985/todo-frontend.git
```

Your folder structure should look like this:

```text
equipo1-todo/
├── todo-backend/
└── todo-frontend/
```

---

## 2. Configure and Run the Application

After cloning both repositories, follow these steps to start the system:

**1. Navigate to the backend directory:**

```bash
cd todo-backend
```

**2. Create your environment configuration file from the provided example:**

```bash
cp .env.example .env
```

*Note: The app refuses to start until `SECRET_KEY` is set. Generate a strong, random secret key into the `.env` file with:*

```bash
python -c "import secrets; print('SECRET_KEY=' + secrets.token_urlsafe(48))" >> .env
```

**3. Build and start the Docker containers (Frontend and Backend):**

```bash
docker compose up -d --build
```

*Note: The `-d` flag runs the services in the background. The first execution may take longer because Docker needs to download the base images, install dependencies, and build the React application.*

SQLite is used as the database and does not require a separate database server container.

---

## 3. Use the Application

Once the containers are running and the services are ready, open your web browser and visit the following URLs:

- **Web Application (UI):** http://localhost:3000
  - Register, log in, create, edit, complete, and delete tasks.

- **API Documentation (Swagger UI):** http://localhost:3000/api/docs
  - Only with `ENVIRONMENT=development` in `.env`; the default (`production`) answers 404 so the API schema is not public (SEG-H07).
  - Behind Nginx the Content-Security-Policy blocks the CDN that Swagger UI and ReDoc load from, so the page stays blank; `/api/openapi.json` works. To use the interactive UI, run the backend directly (`uvicorn app.main:app --reload`) and open http://localhost:8000/api/docs.

- **Server Status (Health Check):** http://localhost:3000/api/health
  - Liveness: the API process is responding. It does not touch the database.
- **Readiness:** http://localhost:3000/api/health/ready
  - `200` when the API can reach its database (`SELECT 1` within 2 s), `503` otherwise (ERR-05). Docker Compose uses it as the backend healthcheck, so `docker compose ps` shows `unhealthy` and Nginx does not start while the database is unavailable. The reason is in `docker compose logs backend`.

The stack is published only on `127.0.0.1:3000`, so it is reachable from this machine and not from the rest of the network (SEG-H13).

---

## Deploying with HTTPS (required)

Nginx in this stack serves **plain HTTP only**. Without TLS, passwords and JWT tokens travel in clear text, so **any deployment that other people can reach must put an HTTPS proxy in front** (Caddy, Traefik, a cloud load balancer or another Nginx with a certificate). Never change the port mapping to `3000:80` or `0.0.0.0:3000:80` to "publish" the app.

The proxy must:

1. Terminate TLS and forward to `http://127.0.0.1:3000`.
2. Redirect HTTP (port 80) to HTTPS.
3. Set (overwrite, not append) `X-Forwarded-Proto: https`. With it, the stack's Nginx adds `Strict-Transport-Security: max-age=31536000` to every response. Without it, HSTS is not sent.

Minimal example with Caddy (automatic certificates):

```caddyfile
todo.example.com {
    reverse_proxy 127.0.0.1:3000 {
        header_up X-Forwarded-Proto https
    }
}
```

Check after deploying:

```bash
curl -sI https://todo.example.com/ | grep -i strict-transport-security
curl -sI http://todo.example.com/  # must be a redirect to https://
```

---

## 4. Stop the Application

When you finish using the application or need to stop the services, run the following command from the `todo-backend` directory:

```bash
docker compose down
```

### Run the tests

Every test builds its own app with `create_app(settings)`: a temporary SQLite database, a random `SECRET_KEY` and the minimum bcrypt cost (`BCRYPT_ROUNDS=4`), so tests never touch `.env` or `data/todo.db` and the whole suite runs in seconds:

```bash
pip install -r requirements-dev.txt
pytest                      # everything
pytest -m "not slow"        # what the CI runs on every push
pytest tests/security       # security regression suite
```

Shared fixtures live in `tests/conftest.py`:

| Fixture | What it gives you |
|---|---|
| `settings`, `app` | The test settings and the app built from them. |
| `client` | In-process `httpx.AsyncClient`, inside the app lifespan. |
| `make_user(email)` | Registers and logs in a user; returns a `TestUser` (`id`, `email`, `token`, `headers`). |
| `user`, `auth_headers` | The default user and its Bearer header. |
| `other_user` | A second user, to test access to someone else's data. |
| `count_queries` | List of the SQL statements the app executed (call `.clear()` before the request you measure). |

Mark long-running tests with `@pytest.mark.slow`. Security tests and their checklist live in `tests/security/`.

---

## 5. Project Structure and File Descriptions

### Root Files

| File | Description |
|---|---|
| `Dockerfile` | Defines the Python 3.14 container image, installs the required dependencies, and configures Uvicorn to run the FastAPI application. |
| `docker-compose.yml` | Orchestrates the backend and frontend services. Exposes the frontend on port 3000 and provides internal networking so Nginx can communicate with FastAPI. |
| `requirements.txt` | Lists the Python dependencies required by the project, including FastAPI, SQLAlchemy, and other supporting libraries. |
| `.env.example` | Template containing the environment variables required by the application, including the database URL, secret key, and JWT expiration time. |
| `.gitignore` | Specifies files and directories excluded from version control, such as virtual environments, local databases, and sensitive configuration files. |

### `app/` Directory (Source Code)

- `main.py`: Main application entry point. `create_app(settings)` builds an app with its own settings, database engine and session factory, configures CORS and security headers, registers the API routers and the liveness (`/api/health`) and readiness (`/api/health/ready`) endpoints. `app = create_app()` is the instance served by uvicorn; tests can create several apps with different settings in the same process.

#### `app/api/` (API Endpoints)

- `deps.py`: Shared API dependencies. Contains the `get_current_user()` function, which validates JWT access tokens and retrieves the authenticated user for protected endpoints.
- `v1/auth.py`: Authentication endpoints (`/register` and `/login`). Handles user registration, password verification, and JWT access token generation.
- `v1/tasks.py`: Task CRUD endpoints. Filters tasks by `owner_id` to ensure users can only access and modify their own tasks.

#### `app/core/` (Configuration and Security)

- `config.py`: Loads application settings from environment variables using Pydantic Settings. `get_settings()` (cached) is the FastAPI dependency that endpoints use; `create_app()` overrides it with the settings it receives.
- `security.py`: Provides password hashing and verification using bcrypt, along with JWT access token generation using the configured signing algorithm (HS256 by default).

#### `app/db/` (Database)

- `base.py`: Defines the SQLAlchemy declarative base class used by the database models.
- `session.py`: Creates the asynchronous SQLAlchemy engine and session factory (SQLite with `aiosqlite`). `get_db()` opens a session from the factory of the app that received the request.

#### `app/models/` (SQLAlchemy Models)

- `user.py`: Defines the `users` table, including the user ID, email address, hashed password, and relationship with tasks.
- `task.py`: Defines the `tasks` table, including the task ID, title, description, completion status, and relationship with its owner.

#### `app/schemas/` (Pydantic Validation)

- `user.py`: Defines schemas for validating user registration data and returning user information without exposing password hashes.
- `task.py`: Defines schemas for creating, updating, and returning task information.
- `token.py`: Defines the structure of the JWT authentication response.

---

## 👥 Development Team

- **Elisa Aguilar Valadez**
- **Josette Nayla Hernández Cazarín**
- **Erika Reyes González**
- **Glafira Rodríguez Esparza**
- **Janette Valenzuela González**
