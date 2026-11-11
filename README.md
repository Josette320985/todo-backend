# To-Do List Application — Equipo 1 (Build It)

Aplicación completa de gestión de tareas (To-Do List) construida con **React (Frontend)** y **FastAPI + SQLite (Backend)**. Todo el sistema está dockerizado y orquestado para levantarse con un solo comando.

Este repositorio contiene el **Backend y la configuración de Docker Compose**. El código del Frontend vive en un repositorio separado.

---

## Requisitos previos

Antes de empezar, asegúrate de tener instalado y ejecutándose:

- **Git** (para clonar los repositorios).
- **Docker Desktop** (con el motor de Docker encendido y en estado "Running").

---

## 1. Obtener el proyecto (Clonar repositorios)

**IMPORTANTE:** Debido a que el proyecto está dividido en dos repositorios (Frontend y Backend) y usamos Docker Compose para unirlos, **ambos deben ser clonados dentro de la misma carpeta raíz** (deben ser carpetas hermanas).

Abre tu terminal y ejecuta los siguientes comandos:

```bash
# 1. Crear una carpeta para el proyecto y entrar en ella
mkdir equipo1-todo
cd equipo1-todo

# 2. Clonar ambos repositorios
git clone https://github.com/Josette320985/todo-backend.git
git clone https://github.com/Josette320985/todo-frontend.git
```

La estructura de tus carpetas debe verse así:

```text
equipo1-todo/
├── todo-backend/
└── todo-frontend/
```

---

## 2. Configurar y ejecutar la aplicación

Una vez clonados los repositorios, sigue estos pasos para levantar el sistema:

**1. Entra a la carpeta del backend:**

```bash
cd todo-backend
```

**2. Crea tu archivo de variables de entorno a partir del ejemplo:**

```bash
cp .env.example .env
```

*Nota: Puedes abrir el archivo `.env` y cambiar `SECRET_KEY` por cualquier cadena de texto larga y segura.*

**3. Construye y levanta los contenedores de Docker (Frontend, Backend y Base de Datos):**

```bash
docker compose up -d --build
```

*Nota: El comando `-d` levanta los servicios en segundo plano. La primera vez tardará un poco porque descarga las imágenes y compila React.*

---

## 3. Usar la aplicación

Una vez que la terminal te devuelva el control, el sistema estará listo. Abre tu navegador web y accede a las siguientes direcciones:

-  **Aplicación Web (UI):** http://localhost:3000
  - Aquí podrás registrarte, iniciar sesión, crear, completar y eliminar tareas.

-  **Documentación de la API (Swagger UI):** http://localhost:3000/api/docs
  - Aquí podrás probar los endpoints (GET, POST, PUT, DELETE) directamente.

-  **Estado del Servidor (Health Check):** http://localhost:3000/api/health

---

##  4. Detener la aplicación

Cuando termines de usar la aplicación o necesites apagarla, ejecuta el siguiente comando desde la carpeta `todo-backend`:

```bash
docker compose down
```

---

## 5. Estructura y explicación de archivos

### Archivos en la raíz

| Archivo | Descripción |
|---|---|
| `Dockerfile` | Define la imagen de Python 3.14, instala las dependencias y configura Uvicorn para correr la API. |
| `docker-compose.yml` | Orquesta el backend y el frontend. Expone el frontend en el puerto 3000 y crea la red interna para que Nginx se comunique con FastAPI. |
| `requirements.txt` | Lista las librerías de Python (FastAPI, SQLAlchemy, Pytest, entre otras). |
| `.env.example` | Plantilla de variables de entorno (URL de la BD, clave secreta y tiempo de expiración del token). |


### Carpeta `app/` (Código fuente)

- `main.py`: Punto de entrada de la aplicación. Configura CORS, inicializa la base de datos (crea las tablas) y une los routers de la API.

#### `app/api/` (Endpoints)

- `deps.py`: Dependencias compartidas. Contiene la función `get_current_user`, que valida el token JWT en las peticiones protegidas.
- `v1/auth.py`: Endpoints de autenticación (`/register` y `/login`). Maneja el hashing de contraseñas y la creación de tokens.
- `v1/tasks.py`: Endpoints del CRUD de tareas. Importante: filtra las tareas por `owner_id` para que un usuario no pueda ver ni editar las tareas de otro.

#### `app/core/` (Configuración y seguridad)

- `config.py`: Lee las variables de entorno utilizando Pydantic.
- `security.py`: Funciones para proteger contraseñas mediante bcrypt y generar/validar tokens JWT (HS256).

#### `app/db/` (Base de datos)

- `base.py`: Clase base de SQLAlchemy para los modelos.
- `session.py`: Configura el motor asíncrono de SQLite (`aiosqlite`) y la sesión de la base de datos.

#### `app/models/` (Tablas SQLAlchemy)

- `user.py`: Define la tabla `users` (id, email, password y relación con tareas).
- `task.py`: Define la tabla `tasks` (id, título, descripción, estado y relación con usuario).

#### `app/schemas/` (Validación Pydantic)

- `user.py`: Valida los datos de entrada y salida para usuarios (por ejemplo, que el email tenga un formato correcto).
- `task.py`: Valida los datos de entrada y salida para las tareas.
- `token.py`: Define la estructura de la respuesta del token JWT.

---

## 👥 Equipo de desarrollo

- **Elisa Aguilar Valadez**
- **Josette Nayla Hernández Cazarín**
- **Erika Reyes González** 
- **Glafira Rodríguez Esparza** 
- **Janette Valenzuela González**