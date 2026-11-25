#!/bin/sh
set -eu

: "${DOMAIN:?DOMAIN environment variable is required}"

CERT_DIR="/etc/letsencrypt/live/${DOMAIN}"
CERT_FILE="${CERT_DIR}/fullchain.pem"
KEY_FILE="${CERT_DIR}/privkey.pem"

if [ -f "${CERT_FILE}" ] && [ -f "${KEY_FILE}" ]; then
    echo "[reverse-proxy] TLS certificate found for ${DOMAIN}; enabling HTTPS."
    envsubst '${DOMAIN}' < /etc/nginx/templates-custom/ssl.conf.template > /etc/nginx/conf.d/default.conf
else
    echo "[reverse-proxy] No TLS certificate for ${DOMAIN} yet; starting in ACME HTTP-01 challenge mode."
    envsubst '${DOMAIN}' < /etc/nginx/templates-custom/acme.conf.template > /etc/nginx/conf.d/default.conf
fi

nginx -t

# Periodically reload Nginx so renewed Let's Encrypt certificates are picked up
# without requiring Docker socket access inside the certbot container.
(
    while :; do
        sleep 43200
        nginx -s reload 2>/dev/null || true
    done
) &

exec nginx -g "daemon off;"
