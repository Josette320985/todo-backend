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

*Note: Open the `.env` file and replace `SECRET_KEY` with a strong, randomly generated secret key of at least 32 characters.*

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
  - Explore and test the available API endpoints (GET, POST, PUT, DELETE).

- **Server Status (Health Check):** http://localhost:3000/api/health
  - Check whether the API service is responding.

---

## 4. Stop the Application

When you finish using the application or need to stop the services, run the following command from the `todo-backend` directory:

```bash
docker compose down
```

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

- `main.py`: Main application entry point. Configures CORS, initializes database tables, registers API routers, and defines the health-check endpoint.

#### `app/api/` (API Endpoints)

- `deps.py`: Shared API dependencies. Contains the `get_current_user()` function, which validates JWT access tokens and retrieves the authenticated user for protected endpoints.
- `v1/auth.py`: Authentication endpoints (`/register` and `/login`). Handles user registration, password verification, and JWT access token generation.
- `v1/tasks.py`: Task CRUD endpoints. Filters tasks by `owner_id` to ensure users can only access and modify their own tasks.

#### `app/core/` (Configuration and Security)

- `config.py`: Loads application settings from environment variables using Pydantic Settings.
- `security.py`: Provides password hashing and verification using bcrypt, along with JWT access token generation using the configured signing algorithm (HS256 by default).

#### `app/db/` (Database)

- `base.py`: Defines the SQLAlchemy declarative base class used by the database models.
- `session.py`: Configures the asynchronous SQLAlchemy database engine and session factory using SQLite with `aiosqlite`.

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
