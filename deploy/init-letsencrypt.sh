#!/usr/bin/env bash
set -euo pipefail

# Obtain the initial Let's Encrypt TLS certificate for DOMAIN using webroot
# verification, then switch reverse-proxy from ACME bootstrap mode to HTTPS.
#
# Usage:
#   ./deploy/init-letsencrypt.sh
#   CERTBOT_STAGING=1 ./deploy/init-letsencrypt.sh   # dry test against staging

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${PROJECT_DIR}"

if [ -f .env ]; then
    set -a
    # shellcheck disable=SC1091
    . ./.env
    set +a
fi

: "${DOMAIN:?Set DOMAIN in .env or environment (e.g. todo.example.com)}"
: "${CERTBOT_EMAIL:?Set CERTBOT_EMAIL in .env or environment (e.g. admin@example.com)}"

COMPOSE="docker compose -f docker-compose.yml -f docker-compose.prod.yml"

echo "==> Starting stack (reverse-proxy starts in ACME challenge mode if no cert exists)..."
${COMPOSE} pull
${COMPOSE} up -d --no-build backend frontend reverse-proxy

STAGING_ARG=""
if [ "${CERTBOT_STAGING:-0}" = "1" ]; then
    echo "==> Using Let's Encrypt STAGING environment"
    STAGING_ARG="--staging"
fi

echo "==> Requesting TLS certificate for ${DOMAIN}..."
${COMPOSE} run --rm --entrypoint certbot certbot certonly \
    --webroot \
    -w /var/www/certbot \
    --email "${CERTBOT_EMAIL}" \
    -d "${DOMAIN}" \
    --rsa-key-size 4096 \
    --agree-tos \
    --no-eff-email \
    --non-interactive \
    ${STAGING_ARG}

echo "==> Restarting reverse-proxy to enable HTTPS..."
${COMPOSE} restart reverse-proxy

echo "==> Starting automatic certbot renewal service..."
${COMPOSE} up -d --no-build certbot

echo "==> Done. Verify HTTPS and HTTP->HTTPS redirect:"
echo "    curl -I https://${DOMAIN}/"
echo "    curl -I http://${DOMAIN}/"
