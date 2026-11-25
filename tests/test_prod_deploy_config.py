"""Static checks for production cloud deployment (F4, Nube 1, Nube 3)."""

import re
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]


def _read(relative_path: str) -> str:
    return (BACKEND_DIR / relative_path).read_text(encoding="utf-8")


def _published_ports(compose: str) -> list[str]:
    ports: list[str] = []
    in_ports = False
    ports_indent = 0
    for line in compose.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        indent = len(line) - len(line.lstrip())
        if re.match(r"^\s*ports:\s*$", line):
            in_ports = True
            ports_indent = indent
            continue
        if in_ports:
            if indent <= ports_indent:
                in_ports = False
            else:
                match = re.match(r'^\s*-\s*"?([^"#]+?)"?\s*$', line)
                if match:
                    ports.append(match.group(1).strip())
    return ports


def test_prod_compose_restricts_public_ports_to_80_and_443() -> None:
    compose = _read("docker-compose.prod.yml")

    assert _published_ports(compose) == ["80:80", "443:443"]

    # Frontend dev port binding from base compose must be cleared in production.
    assert "ports: !reset []" in compose
    # Backend must never publish port 8000 in production override.
    assert "8000:" not in compose
    assert "3000:" not in compose


def test_prod_compose_includes_reverse_proxy_and_certbot() -> None:
    compose = _read("docker-compose.prod.yml")
    assert "reverse-proxy:" in compose
    assert "certbot:" in compose
    assert "certbot renew" in compose
    assert "build: !reset null" in compose


def test_ssl_template_enforces_https_hsts_and_internal_proxy_headers() -> None:
    ssl_conf = _read("deploy/nginx/templates/ssl.conf.template")

    assert "listen 80;" in ssl_conf
    assert "return 301 https://$host$request_uri;" in ssl_conf
    assert "/.well-known/acme-challenge/" in ssl_conf

    assert "listen 443 ssl;" in ssl_conf
    assert "ssl_certificate /etc/letsencrypt/live/${DOMAIN}/fullchain.pem;" in ssl_conf
    assert "ssl_protocols TLSv1.2 TLSv1.3;" in ssl_conf
    assert 'Strict-Transport-Security "max-age=31536000"' in ssl_conf

    # /api/ goes directly to backend:8000 with non-spoofable X-Forwarded-For.
    assert "proxy_pass http://backend:8000/api/;" in ssl_conf
    assert "proxy_set_header X-Forwarded-For $remote_addr;" in ssl_conf
    assert "proxy_set_header X-Forwarded-Proto https;" in ssl_conf


def test_acme_bootstrap_template_never_serves_app_over_http() -> None:
    acme_conf = _read("deploy/nginx/templates/acme.conf.template")
    assert "/.well-known/acme-challenge/" in acme_conf
    assert "return 503;" in acme_conf
    assert "proxy_pass" not in acme_conf


def test_shell_scripts_use_lf_line_endings() -> None:
    scripts = [
        "deploy/init-letsencrypt.sh",
        "deploy/setup-firewall.sh",
        "deploy/nginx/entrypoint.sh",
    ]
    for script in scripts:
        raw = (BACKEND_DIR / script).read_bytes()
        assert b"\r\n" not in raw, f"{script} must use LF line endings for Linux"


def test_backend_cd_workflow_has_verify_push_and_deploy_jobs() -> None:
    workflow = _read(".github/workflows/backend-cd.yml")
    assert "packages: write" in workflow
    assert "ghcr.io" in workflow
    assert "verify:" in workflow
    assert "build-and-push:" in workflow
    assert "deploy:" in workflow
    assert "docker-compose.prod.yml" in workflow
