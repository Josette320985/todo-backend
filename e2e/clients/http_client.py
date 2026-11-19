"""Minimal HTTP client run inside the client-a / client-b containers (TEST-09, flow 5).

Each container has its own IP on the compose network, so the backend sees two
different clients behind Nginx. Only the standard library is used, so the
backend image can be reused without installing anything.

Usage (via `docker compose exec -T client-a python /e2e-clients/http_client.py ...`):
  register EMAIL PASSWORD
  login EMAIL PASSWORD [--times N] [--xff VALUE]

Prints one JSON object: {"statuses": [...]} with the HTTP status of each request.
"""

import argparse
import json
import os
import urllib.error
import urllib.parse
import urllib.request

BASE: str = os.environ.get("NGINX_URL", "http://frontend").rstrip("/")


def send(path: str, body: bytes, content_type: str, xff: str | None) -> int:
    headers: dict[str, str] = {"Content-Type": content_type}
    if xff is not None:
        headers["X-Forwarded-For"] = xff
    request = urllib.request.Request(
        BASE + path, data=body, headers=headers, method="POST"
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return int(response.status)
    except urllib.error.HTTPError as err:
        return int(err.code)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["register", "login"])
    parser.add_argument("email")
    parser.add_argument("password")
    parser.add_argument("--times", type=int, default=1)
    parser.add_argument("--xff", default=None)
    args = parser.parse_args()

    statuses: list[int] = []
    for _ in range(args.times):
        if args.command == "register":
            body = json.dumps({"email": args.email, "password": args.password})
            statuses.append(
                send("/api/v1/auth/register", body.encode(), "application/json", args.xff)
            )
        else:
            form = urllib.parse.urlencode(
                {"username": args.email, "password": args.password}
            )
            statuses.append(
                send(
                    "/api/v1/auth/login",
                    form.encode(),
                    "application/x-www-form-urlencoded",
                    args.xff,
                )
            )
    print(json.dumps({"statuses": statuses}))


if __name__ == "__main__":
    main()
