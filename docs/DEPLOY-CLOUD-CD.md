# Despliegue en la Nube y Pipeline de CD (F4, Nube 1 y Nube 3)

Esta guía describe cómo desplegar la aplicación completa (`todo-frontend` + `todo-backend`) en un servidor Linux en la nube cumpliendo:

- **F4:** Pipeline de Entrega Continua (CD) en GitHub Actions (`ghcr.io` + despliegue por SSH).
- **Nube 1:** Dominio público con TLS/SSL obligatorio (Nginx + Let's Encrypt / Certbot, redirección HTTP → HTTPS y HSTS).
- **Nube 3:** Restricción de puertos públicos (solo **443** y **80** expuestos al público; el puerto **8000** del backend permanece estrictamente interno en la red Docker `10.250.250.0/24`).

---

## Arquitectura de red y tráfico

```text
Internet
  │
  ├── :80  ──▶ reverse-proxy (Nginx) ──▶ /.well-known/acme-challenge/ (Certbot)
  │                                  └── 301 Redirect a https://$host$request_uri
  │
  └── :443 ──▶ reverse-proxy (Nginx + TLS Let's Encrypt + HSTS)
                 ├── /api/ ──▶ backend:8000   (solo red interna 10.250.250.0/24)
                 └── /     ──▶ frontend:80    (solo red interna 10.250.250.0/24)
```

> **Importante (SEG-02):** `reverse-proxy` envía `/api/` directamente a `backend:8000` dentro de la subred fija `10.250.250.0/24` sobrescribiendo `X-Forwarded-For` con `$remote_addr`. Así FastAPI identifica la IP real de cada cliente para el rate limit sin que pueda falsificarse.

---

## 1. Requisitos previos en el servidor (VPS / VM)

1. Crear una VM Linux (Ubuntu 22.04/24.04 recomendado) con Docker Engine, Docker Compose v2 y Git instalados.
2. Apuntar un dominio o subdominio (registro DNS `A`) hacia la IP pública del servidor (por ejemplo, `todo.tudominio.com`).

---

## 2. Nube 3: Restringir puertos públicos

### A. Firewall del proveedor Cloud (Security Group / VPC Firewall / NSG)
En la consola de tu proveedor (AWS EC2, DigitalOcean, GCP, Azure, etc.), permite únicamente:
- **80/TCP** (`0.0.0.0/0`): necesario para desafíos HTTP-01 de Let's Encrypt y redirección a HTTPS.
- **443/TCP** (`0.0.0.0/0`): tráfico HTTPS de la aplicación.
- **22/TCP** (SSH): restringido a tu IP de administración o necesario para el despliegue por CD.
- **No abrir** los puertos `8000` ni `3000`.

### B. Firewall del sistema operativo (`ufw`)
Dentro del servidor, ejecuta:

```bash
sudo ./deploy/setup-firewall.sh
```

### C. Verificación en Docker
En `docker-compose.prod.yml`:
- `reverse-proxy` es el **único** servicio con `ports:` (`80:80` y `443:443`).
- `frontend` elimina el mapeo local (`ports: !reset []`) y usa solo `expose: ["80"]`.
- `backend` usa exclusivamente `expose: ["8000"]`.

Verifica desde el servidor que el puerto `8000` no está escuchando en el host:

```bash
ss -tulpn | grep -E ':(80|443|3000|8000)\b'
```

---

## 3. Nube 1: Dominio público y certificado TLS (Let's Encrypt)

1. Clona `todo-backend` en el servidor (por ejemplo en `/opt/todo-app/todo-backend`):

```bash
sudo mkdir -p /opt/todo-app
sudo chown -R "$USER":"$USER" /opt/todo-app
git clone https://github.com/Josette320985/todo-backend.git /opt/todo-app/todo-backend
cd /opt/todo-app/todo-backend
```

2. Crea `.env` a partir de `.env.example` y completa los valores obligatorios:

```bash
cp .env.example .env
python3 -c "import secrets; print('SECRET_KEY=' + secrets.token_urlsafe(48))" >> .env
```

Asegúrate de definir en `.env`:
- `DOMAIN=todo.tudominio.com`
- `CERTBOT_EMAIL=tu-correo@tudominio.com`
- `ENVIRONMENT=production`
- (Opcional si usas un fork) `BACKEND_IMAGE=ghcr.io/<tu-usuario>/todo-backend:latest` y `FRONTEND_IMAGE=ghcr.io/<tu-usuario>/todo-frontend:latest`

3. Si tus imágenes en GitHub Container Registry (`ghcr.io`) son privadas, inicia sesión una vez en el servidor:

```bash
echo "<TU_TOKEN_CON_READ_PACKAGES>" | docker login ghcr.io -u "<TU_USUARIO_GITHUB>" --password-stdin
```

4. Emite el certificado TLS inicial con Let's Encrypt:

```bash
./deploy/init-letsencrypt.sh
```

*(Para probar primero sin consumir cuota de Let's Encrypt, usa `CERTBOT_STAGING=1 ./deploy/init-letsencrypt.sh`.)*

5. Verifica TLS, redirección obligatoria y HSTS:

```bash
curl -sI "http://${DOMAIN}/"  | grep -iE 'HTTP/|location'   # Debe responder 301 a https://
curl -sI "https://${DOMAIN}/" | grep -iE 'HTTP/|strict-transport-security'
curl -s "https://${DOMAIN}/api/health/ready"                # Debe responder {"status":"ok"}
```

El servicio `certbot` renueva automáticamente el certificado cada 12 horas y `reverse-proxy` recarga la configuración periódicamente para aplicar el certificado renovado.

---

## 4. F4: Pipeline de CD en GitHub Actions

Ambos repositorios incluyen su workflow de entrega continua:
- Frontend: `.github/workflows/frontend-cd.yml`
- Backend: `.github/workflows/backend-cd.yml`

Cada push a `main` (o ejecución manual con **Run workflow**):
1. **`verify`:** ejecuta validaciones completas (`typecheck`, `lint`, `tests`, `audit` / `mypy`, `pytest`, cobertura >= 80%, `pip-audit`).
2. **`build-and-push`:** construye la imagen Docker y la publica en `ghcr.io` etiquetada con `latest` y `sha-<commit>`.
3. **`deploy`:** se conecta por SSH al servidor, descarga la nueva imagen (`docker compose pull`), actualiza los contenedores sin reconstruir en el servidor y verifica `/api/health/ready`.

### Secrets requeridos en GitHub (en ambos repositorios)

En **Settings → Secrets and variables → Actions → Repository secrets**, configura:

| Secret | Obligatorio | Descripción |
|---|---|---|
| `DEPLOY_HOST` | Sí (para SSH) | IP pública o dominio del servidor (ej. `203.0.113.10`). |
| `DEPLOY_USER` | Sí (para SSH) | Usuario SSH en el servidor (con permiso en Docker). |
| `DEPLOY_SSH_KEY` | Sí (para SSH) | Llave privada SSH (PEM/OpenSSH) cuya llave pública esté en `~/.ssh/authorized_keys` del servidor. |
| `DEPLOY_PORT` | Opcional | Puerto SSH (por defecto `22`). |
| `DEPLOY_PATH` | Opcional | Ruta de `todo-backend` en el servidor (por defecto `/opt/todo-app/todo-backend`). |
| `DEPLOY_KNOWN_HOSTS` | Opcional | Salida de `ssh-keyscan -H <DEPLOY_HOST>` para verificación estricta de host. |
| `GHCR_USER` | Opcional | Usuario de GitHub si los paquetes de GHCR son privados. |
| `GHCR_TOKEN` | Opcional | PAT con permiso `read:packages` si los paquetes de GHCR son privados. |

> Si aún no configuras `DEPLOY_HOST`, `DEPLOY_USER` y `DEPLOY_SSH_KEY`, los workflows seguirán ejecutando `verify` y `build-and-push` hacia GHCR correctamente y mostrarán un aviso indicando que falta configurar los secrets de SSH.
