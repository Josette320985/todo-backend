#!/usr/bin/env bash
set -euo pipefail

# Host firewall hardening (Nube 3):
# Allow ONLY HTTP (80), HTTPS (443), and administrative SSH (22 by default).
# Port 8000 (FastAPI) and port 3000 (dev frontend) remain strictly internal.
#
# Note: Remember to ALSO restrict ports in your cloud provider's Security Group
# / VPC Firewall (only 80 and 443 public; SSH 22 restricted to admin IPs), since
# Docker manages iptables chains independently of UFW for published ports.

if [ "$(id -u)" -ne 0 ]; then
    echo "Run as root (e.g. sudo ./deploy/setup-firewall.sh)" >&2
    exit 1
fi

if ! command -v ufw >/dev/null 2>&1; then
    echo "ufw is not installed. Install it first: apt-get update && apt-get install -y ufw" >&2
    exit 1
fi

SSH_PORT="${SSH_PORT:-22}"

echo "==> Configuring UFW default policies..."
ufw default deny incoming
ufw default allow outgoing

echo "==> Allowing SSH (${SSH_PORT}/tcp), HTTP (80/tcp), and HTTPS (443/tcp)..."
ufw allow "${SSH_PORT}/tcp" comment "SSH administration and CD"
ufw allow 80/tcp comment "HTTP (ACME challenge + HTTPS redirect)"
ufw allow 443/tcp comment "HTTPS (TLS reverse proxy)"

echo "==> Explicitly denying 8000/tcp and 3000/tcp on host firewall..."
ufw deny 8000/tcp comment "Backend internal only"
ufw deny 3000/tcp comment "Frontend dev port disabled in prod"

echo "==> Enabling UFW..."
ufw --force enable
ufw status verbose
